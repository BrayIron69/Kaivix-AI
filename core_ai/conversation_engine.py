from typing import Optional

from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID
from core_ai.lead_profile import LeadProfile
from knowledge.knowledge_base import KnowledgeBase
from utils.llm import LLM
from memory.conversation_memory import ConversationMemory

from core_ai.decision_engine import DecisionEngine
from core_ai.entity_extractor import EntityExtractor
from core_ai.goal_engine import GoalEngine
from core_ai.lead_intelligence_engine import LeadIntelligenceEngine
from core_ai.memory_manager import MemoryManager
from core_ai.planning_engine import PlanningEngine
from core_ai.prompt_builder import PromptBuilder
from core_ai.qualification_engine import QualificationEngine
from core_ai.stages import ConversationStage
from core_ai.working_memory import WorkingMemory
from services.lead_service import LeadService
from utils.logger import Logger


class ConversationEngine:
    """
    ConversationEngine v2.3

    Central orchestration layer for the Kaivix AI Platform.
    It coordinates memory, lead state, knowledge retrieval,
    intent detection, qualification, prompt construction,
    CRM persistence, and LLM response generation.

    As of this milestone, all WorkingMemory / ConversationSummary /
    LongTermMemory scheduling has been extracted into a dedicated
    MemoryManager (see core_ai/memory_manager.py). This is a pure
    refactor: every cadence rule, merge semantic, error-handling
    behavior, and log message is unchanged — only *where* the
    scheduling logic and its per-conversation state dicts live has
    moved. ConversationEngine still decides *when* in the pipeline
    each memory call happens (the call sites below are in the exact
    same order as before); MemoryManager still contains none of their
    internal business logic.
    """

    # Intents that force a specific conversation stage, regardless of
    # qualification progress.
    _OBJECTION_HANDLING_INTENTS = {"objection", "support", "pricing"}
    _CLOSING_INTENTS = {"meeting_request", "buying_signal"}

    # Thresholds used by stage detection.
    _GREETING_HISTORY_LIMIT = 2
    _PRESENTATION_COMPLETION_THRESHOLD = 60
    _PRESENTATION_HISTORY_LIMIT = 8

    # How often (in turns) the richer ConversationSummary narrative is
    # refreshed. Unlike WorkingMemory.summary (refreshed every turn),
    # this is intentionally periodic. Configurable per-instance via the
    # constructor for callers that want a different cadence. Passed
    # straight through to MemoryManager, which owns the actual cadence
    # check.
    _SUMMARY_REFRESH_INTERVAL_TURNS = 5

    def __init__(
        self,
        summary_refresh_interval_turns: int = _SUMMARY_REFRESH_INTERVAL_TURNS,
        business_id: str = DEFAULT_BUSINESS_ID,
        business_config_repository: Optional[BusinessConfigRepository] = None,
    ):
        # Resolved once, at construction, into a cached BusinessConfig —
        # not threaded through process_message per-message. See
        # docs/Decision_Log.md #011: ChatService holds one long-lived
        # ConversationEngine instance and V1 is one deployment per
        # customer, so business_id cannot legitimately vary between
        # messages within a running process.
        business_config_repository = business_config_repository or BusinessConfigRepository()
        self.business_id = business_id
        self.business_config = business_config_repository.load(business_id)

        self.memory = ConversationMemory(business_id=self.business_id)
        self.knowledge = KnowledgeBase(business_config=self.business_config)
        self.llm = LLM()
        self.logger = Logger()

        self.decision_engine = DecisionEngine()
        self.goal_engine = GoalEngine()
        self.entity_extractor = EntityExtractor()
        self.lead_intelligence_engine = LeadIntelligenceEngine()
        self.planning_engine = PlanningEngine()
        self.qualification_engine = QualificationEngine(business_config=self.business_config)
        self.prompt_builder = PromptBuilder()
        self.lead_service = LeadService()

        # Coordinates WorkingMemory (every turn), ConversationSummary
        # (every `summary_refresh_interval_turns` turns), and
        # LongTermMemory (hydrate once per conversation, persist every
        # turn once email is known). See core_ai/memory_manager.py.
        self.memory_manager = MemoryManager(
            summary_refresh_interval_turns=summary_refresh_interval_turns,
            logger=self.logger,
        )

        # How many turns to wait between ConversationSummary refreshes.
        # Kept here too (in addition to living on memory_manager) since
        # it was previously a public-ish instance attribute; preserved
        # for backward compatibility with anything reading it directly.
        self._summary_refresh_interval_turns = summary_refresh_interval_turns

        # Persistent lead state per conversation.
        self._lead_profiles: dict[str, LeadProfile] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_message(self, conversation_id: str, user_message: str) -> str:
        """
        Main entry point for all incoming customer messages.

        Pipeline (unchanged from the previous milestone):
        1. Record the user's message and load history.
        2. Update the lead profile and sync it to the CRM.
        3. Classify intent, stage, and goal.
        4. Assess qualification progress once, then build a deterministic
           conversation plan from stage/intent/goal/lead/qualification.
        5. Gather knowledge context.
        6. Build the prompt and generate the assistant response.
        7. Record the response and log the outcome.
        """

        history = self._record_user_message(conversation_id, user_message)
        lead = self._update_lead_profile(conversation_id, user_message)

        intent = self.decision_engine.detect_intent(user_message)

        # Computed once per turn and reused by stage detection, the
        # planner, and the prompt builder below — no duplicate
        # qualification calculation.
        qualification = self._assess_qualification(lead)

        stage = self._detect_stage(history, intent, qualification["progress"])
        goal = self.goal_engine.determine_goal(stage=stage, intent=intent, lead=lead)

        # Refreshed once per turn, after qualification/goal are known and
        # before planning, so PlanningEngine can consume it. Delegated to
        # MemoryManager; every value WorkingMemory stores is still copied
        # from something computed above — it recalculates nothing itself.
        working_memory = self.memory_manager.update_working_memory(
            conversation_id=conversation_id,
            lead=lead,
            qualification=qualification["progress"],
            goal=goal,
            history=history,
        )

        # Refreshed only every `_summary_refresh_interval_turns` turns
        # (not every turn like working_memory above). The result is
        # stored directly onto `working_memory` by MemoryManager, so
        # PlanningEngine and PromptBuilder pick it up automatically
        # without any new parameter — PlanningEngine continues to read
        # WorkingMemory only, and never touches ConversationSummary
        # directly.
        self.memory_manager.maybe_refresh_conversation_summary(
            conversation_id=conversation_id,
            lead=lead,
            working_memory=working_memory,
            history=history,
        )

        plan = self.planning_engine.plan(
            stage=stage,
            intent=intent,
            goal=goal,
            lead=lead,
            qualification=qualification["progress"],
            history=history,
            working_memory=working_memory,
        )

        knowledge = self._gather_knowledge(conversation_id, user_message)

        long_term_profile = self.memory_manager.get_long_term_profile(conversation_id)

        system_prompt = self.prompt_builder.build(
            stage=stage.value,
            intent=intent.value,
            goal=goal.value,
            knowledge=knowledge,
            missing_fields=qualification["missing"],
            extracted_entities=lead.to_dict(),
            plan=plan,
            working_memory=working_memory,
            long_term_memory=long_term_profile,
            business_config=self.business_config,
        )

        messages = self._build_messages(system_prompt, history)
        response = self._generate_response(conversation_id, messages)

        self.memory.add_assistant_message(conversation_id, response)

        self._log_turn(
            conversation_id=conversation_id,
            stage=stage,
            intent=intent,
            goal=goal,
            qualification=qualification,
            working_memory=working_memory,
            long_term_memory=long_term_profile,
        )

        return response

    # ------------------------------------------------------------------
    # Lead state
    # ------------------------------------------------------------------

    def _get_lead(self, conversation_id: str) -> LeadProfile:
        """Return the active lead profile for this conversation."""
        if conversation_id not in self._lead_profiles:
            self._lead_profiles[conversation_id] = LeadProfile()
        return self._lead_profiles[conversation_id]

    def _get_working_memory(self, conversation_id: str) -> WorkingMemory:
        """
        Return the active WorkingMemory for this conversation.

        Delegates to MemoryManager, which now owns the per-conversation
        WorkingMemory dict. Kept as a method on ConversationEngine for
        backward compatibility with any existing caller (including the
        test harness used to verify this milestone).
        """
        return self.memory_manager.get_working_memory(conversation_id)

    def _update_lead_profile(self, conversation_id: str, user_message: str) -> LeadProfile:
        """
        Load the lead profile for this conversation, merge any newly
        extracted entities into it, hydrate it with any long-term
        memory on record for this contact, compute lead intelligence,
        and sync the result to the CRM and to long-term memory.
        """
        lead = self._get_lead(conversation_id)

        try:
            self.entity_extractor.extract(user_message, lead)
        except Exception as error:
            self.logger.error(
                f"[EntityExtractor] Failed to extract entities "
                f"(conversation_id={conversation_id}): {error}"
            )

        # Long-term memory hydration/persistence scheduling now lives on
        # MemoryManager; call sites and ordering relative to lead
        # intelligence / CRM sync below are unchanged.
        self.memory_manager.hydrate_long_term_memory(
            conversation_id, lead, business_id=self.business_id
        )

        self._apply_lead_intelligence(conversation_id, lead)

        self._sync_lead_to_crm(conversation_id, lead)

        self.memory_manager.persist_long_term_memory(
            conversation_id, lead, business_id=self.business_id
        )

        return lead

    def _apply_lead_intelligence(self, conversation_id: str, lead: LeadProfile) -> None:
        """
        Run deterministic lead-scoring analysis exactly once per turn and
        store the results directly on the CustomerState/LeadProfile object
        (temperature, confidence, score, score_reasons, recommended_action,
        summary). This is the single source of truth read afterward by
        GoalEngine, PromptBuilder, and CRM persistence — no other step
        recomputes it.
        """
        try:
            self.lead_intelligence_engine.apply(lead)
        except Exception as error:
            self.logger.error(
                f"[LeadIntelligenceEngine] Failed to analyze lead "
                f"(conversation_id={conversation_id}): {error}"
            )

    def _sync_lead_to_crm(self, conversation_id: str, lead: LeadProfile) -> None:
        """
        Save the lead to the CRM when we have enough information
        to identify it uniquely. CRM failures are logged but never
        interrupt the conversation.
        """
        if not lead.email or not lead.email.strip():
            return

        try:
            self.lead_service.save(lead, business_id=self.business_id)
        except Exception as error:
            self.logger.error(
                f"[LeadService] Failed to save lead "
                f"(conversation_id={conversation_id}): {error}"
            )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _detect_stage(
        self,
        history: list[dict],
        intent,
        progress: dict,
    ) -> ConversationStage:
        """
        Stage detection based on conversation history,
        lead completeness, and intent.

        `progress` is the qualification progress dict already computed
        once for this turn (see process_message) — it is not
        recalculated here.
        """
        history_len = len(history)

        if history_len <= self._GREETING_HISTORY_LIMIT:
            return ConversationStage.GREETING

        if intent.value in self._OBJECTION_HANDLING_INTENTS:
            return ConversationStage.OBJECTION_HANDLING

        if intent.value in self._CLOSING_INTENTS:
            return ConversationStage.CLOSING

        if not progress["qualified"]:
            if progress["completion_percentage"] >= self._PRESENTATION_COMPLETION_THRESHOLD:
                return ConversationStage.PRESENTATION
            return ConversationStage.QUALIFICATION

        if history_len < self._PRESENTATION_HISTORY_LIMIT:
            return ConversationStage.PRESENTATION

        return ConversationStage.CLOSING

    # ------------------------------------------------------------------
    # Knowledge & qualification
    # ------------------------------------------------------------------

    def _gather_knowledge(self, conversation_id: str, user_message: str) -> str:
        """Retrieve relevant company knowledge for the current message."""
        try:
            return self.knowledge.get_relevant_context(user_message)
        except Exception as error:
            self.logger.error(
                f"[KnowledgeBase] Failed to retrieve context "
                f"(conversation_id={conversation_id}): {error}"
            )
            return ""

    def _assess_qualification(self, lead: LeadProfile) -> dict:
        """Return the lead's qualification progress, including missing fields."""
        progress = self.qualification_engine.qualification_progress(lead)
        return {
            "missing": progress["missing"],
            "progress": progress,
        }

    # ------------------------------------------------------------------
    # Prompt / LLM
    # ------------------------------------------------------------------

    def _build_messages(self, system_prompt: str, history: list[dict]) -> list[dict]:
        """
        Build a standard chat message list for the LLM.
        The system prompt defines behavior; history provides context.
        """
        return [{"role": "system", "content": system_prompt}, *history]

    def _generate_response(self, conversation_id: str, messages: list[dict]) -> str:
        """
        Call the LLM to generate the assistant's reply.

        Errors are logged with conversation context before being
        re-raised, since callers rely on this exception to signal
        a failed turn.
        """
        try:
            return self.llm.generate(messages)
        except Exception as error:
            self.logger.error(
                f"[LLM] Failed to generate response "
                f"(conversation_id={conversation_id}): {error}"
            )
            raise

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _record_user_message(self, conversation_id: str, user_message: str) -> list[dict]:
        """Save the user's latest message and return the updated history."""
        self.memory.add_user_message(conversation_id, user_message)
        return self.memory.get_conversation(conversation_id)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_turn(
        self,
        conversation_id: str,
        stage: ConversationStage,
        intent,
        goal,
        qualification: dict,
        working_memory: WorkingMemory = None,
        long_term_memory: dict = None,
    ) -> None:
        """Lightweight debugging output to help future tuning."""
        progress = qualification["progress"]

        summary_lines = [
            f"Conversation ID: {conversation_id}",
            f"Stage: {stage.value}",
            f"Intent: {intent.value}",
            f"Goal: {goal.value}",
            f"Qualified: {progress['qualified']}",
            f"Completion: {progress['completion_percentage']}%",
            f"Missing fields: {qualification['missing']}",
        ]

        if working_memory is not None:
            summary_lines.append(f"Working memory: {working_memory.summary}")
            if working_memory.conversation_summary:
                summary_lines.append(
                    f"Conversation summary (turn {working_memory.summary_last_updated_turn}): "
                    f"{working_memory.conversation_summary}"
                )

        if long_term_memory:
            previous_count = len(long_term_memory.get("previous_conversations") or [])
            summary_lines.append(
                f"Long-term memory: returning contact, {previous_count} previous conversation(s) on record"
            )

        print("\n" + "=" * 72)
        for line in summary_lines:
            print(line)
        print("=" * 72 + "\n")

        self.logger.info(" | ".join(summary_lines))