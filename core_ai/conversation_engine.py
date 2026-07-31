from dataclasses import replace
from typing import Optional

from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID
from core_ai.conversation_plan import ConversationPlan
from core_ai.lead_profile import LeadProfile
from knowledge.knowledge_base import KnowledgeBase
from utils.llm_provider import get_llm_provider
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
from scheduling.google_calendar_provider import GoogleCalendarProvider
from scheduling.slot_matcher import match_offered_slot
from services.lead_service import LeadService
from utils.logger import Logger, conversation_bodies_enabled, redact_free_text


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

    # Name in BusinessConfig.tools.enabled_tools that gates the calendar
    # scheduling feature. Until now enabled_tools was loaded and then
    # ignored: booking was gated only by whether a Google Calendar
    # happened to be OAuth-connected, so a business could not turn the
    # feature off without disconnecting the calendar entirely.
    _CALENDAR_BOOKING_TOOL = "calendar_booking"

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

        # providers.yaml is now read rather than merely validated. Both
        # fields resolve through a registry, so adding a provider never
        # touches this file -- see utils/llm_provider.py and crm/registry.py.
        # An unrecognised name raises here, at construction, instead of
        # silently serving Groq/SQLite under a different name in config.
        self.llm = get_llm_provider(self.business_config.providers.llm_provider)
        self.logger = Logger()

        self.decision_engine = DecisionEngine()
        self.goal_engine = GoalEngine()
        self.entity_extractor = EntityExtractor()
        self.lead_intelligence_engine = LeadIntelligenceEngine()
        self.planning_engine = PlanningEngine(business_config=self.business_config)
        self.qualification_engine = QualificationEngine(business_config=self.business_config)
        self.prompt_builder = PromptBuilder()
        self.lead_service = LeadService(
            crm_provider=self.business_config.providers.crm_provider
        )
        self.calendar_provider = GoogleCalendarProvider()

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

        # Structured (start, end) datetime pairs behind the display
        # strings most recently offered to each conversation (see
        # _maybe_attach_availability), keyed by conversation_id. Kept
        # separately from WorkingMemory.offered_slots (which only ever
        # holds the display strings -- see its docstring) so
        # _maybe_resolve_booking can book the exact real time window that
        # was actually shown to the visitor, without re-parsing display
        # text back into a date -- inherently ambiguous once more than a
        # few days have passed (which Tuesday?).
        self._offered_slot_windows: dict[str, list[tuple]] = {}

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

        # Resolves a visitor's reply (e.g. "2", "the second one") into a
        # real calendar booking, when a previous turn offered real
        # available time slots (working_memory.offered_slots). Placed
        # right after working_memory is refreshed, independent of
        # intent/stage/goal -- it only needs working_memory, lead, and
        # this turn's raw user_message. Returns None when there is
        # nothing to resolve this turn (no offered slots, or no clear
        # match), in which case working_memory.offered_slots is left
        # untouched so a later turn can still match it.
        booking_result = self._maybe_resolve_booking(
            conversation_id, user_message, lead, working_memory
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

        if booking_result is not None:
            # A booking was just confirmed or failed this turn --
            # PlanningEngine itself never sets these fields (it performs
            # no I/O; see its docstring). Skip _maybe_attach_availability
            # below: a booking resolution and a brand-new availability
            # offer should never both fire in the same turn.
            plan = replace(
                plan,
                booking_confirmation=booking_result["confirmation"],
                booking_failed=booking_result["failed"],
            )
        else:
            # Read-only: attaches real calendar availability to the plan
            # when PlanningEngine has already decided to drive toward
            # booking and this business has a connected calendar.
            # PlanningEngine itself performs no I/O (see its docstring)
            # -- this lookup belongs here, one step after the plan is
            # produced, not inside PlanningEngine.
            plan = self._maybe_attach_availability(conversation_id, plan, working_memory)

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
    # Scheduling / Calendar
    # ------------------------------------------------------------------

    def _calendar_booking_enabled(self) -> bool:
        """
        Whether this business has the calendar_booking tool switched on
        in BusinessConfig.tools.enabled_tools.

        Fails closed: a config with no tools section, or an empty
        enabled_tools, means the feature is off. Read fresh from the
        cached BusinessConfig rather than snapshotted at construction,
        so it stays consistent with how every other config value is
        consumed.
        """
        tools = getattr(self.business_config, "tools", None)
        enabled_tools = getattr(tools, "enabled_tools", None) or []
        return self._CALENDAR_BOOKING_TOOL in enabled_tools

    def _maybe_attach_availability(
        self,
        conversation_id: str,
        plan: ConversationPlan,
        working_memory: WorkingMemory,
    ) -> ConversationPlan:
        """
        When PlanningEngine has decided to drive toward booking
        (plan.strategy == "drive_to_booking") and this business has a
        connected Google Calendar, attach real available time windows to
        the plan so PromptBuilder can have Bray offer them naturally
        instead of a vague "let's book a call." Read-only -- never
        creates or modifies an event.

        Also remembers what was offered: the display strings are written
        onto `working_memory` (set_offered_slots) and the underlying
        structured (start, end) datetimes are cached in
        self._offered_slot_windows, keyed by conversation_id, so a later
        turn's numeric reply can be resolved back into a real booking by
        _maybe_resolve_booking without ever re-parsing display text.

        Mirrors _sync_lead_to_crm's error-handling contract: calendar
        failures are logged and the original plan is returned unchanged,
        never interrupting the conversation. Returns a new plan via
        dataclasses.replace rather than mutating the one PlanningEngine
        returned.
        """
        try:
            if plan.strategy != "drive_to_booking":
                return plan

            # Config gate first -- cheapest check, and no reason to touch
            # the calendar at all for a business with booking switched off.
            if not self._calendar_booking_enabled():
                return plan

            if not self.calendar_provider.is_connected(self.business_id):
                return plan

            windows = self.calendar_provider.get_free_busy_windows(self.business_id)
            slots = [self.calendar_provider.format_slot(start, end) for start, end in windows]

            self._offered_slot_windows[conversation_id] = windows
            working_memory.set_offered_slots(slots)

            return replace(plan, available_slots=slots)
        except Exception as error:
            self.logger.error(
                f"[GoogleCalendarProvider] Failed to fetch availability "
                f"(conversation_id={conversation_id}): {error}"
            )
            return plan

    def _maybe_resolve_booking(
        self,
        conversation_id: str,
        user_message: str,
        lead: LeadProfile,
        working_memory: WorkingMemory,
    ) -> Optional[dict]:
        """
        Attempt to resolve a visitor's reply into a real calendar
        booking, when a previous turn offered real available time slots
        (working_memory.offered_slots, set by _maybe_attach_availability
        above).

        Returns None when there is nothing to resolve this turn (no
        offered slots, or the message doesn't clearly match one of them)
        -- working_memory.offered_slots is left untouched in that case,
        so a later turn can still match it. Otherwise returns
        {"confirmation": str, "failed": bool} describing the outcome,
        for process_message to attach to this turn's ConversationPlan.

        This is the one place in the pipeline with a real, external,
        hard-to-undo side effect (creating an actual calendar event) --
        mirrors _sync_lead_to_crm's error-handling contract regardless:
        failures are logged and never raise past this method, degrading
        to "nothing resolved" rather than breaking the turn.
        """
        try:
            # Same gate as _maybe_attach_availability. Checked here too
            # rather than relying on "nothing was ever offered": slots
            # could have been offered before the tool was switched off,
            # and creating a real calendar event is exactly the side
            # effect a disabled tool must not produce.
            if not self._calendar_booking_enabled():
                return None

            offered_slots = list(working_memory.offered_slots or [])
            if not offered_slots:
                return None

            matched_index = match_offered_slot(user_message, offered_slots)
            if matched_index is None:
                return None

            matched_slot_text = offered_slots[matched_index]
            windows = self._offered_slot_windows.get(conversation_id) or []

            if matched_index >= len(windows):
                # Matched a display string but have no structured
                # start/end to actually book (e.g. stale/desynced cache)
                # -- fail safely rather than guess a time.
                self.logger.error(
                    f"[GoogleCalendarProvider] Matched offered slot "
                    f"{matched_index} but no cached start/end window "
                    f"available (conversation_id={conversation_id})"
                )
                working_memory.set_offered_slots([])
                self._offered_slot_windows.pop(conversation_id, None)
                return {"confirmation": "", "failed": True}

            start_time, end_time = windows[matched_index]

            result = self.calendar_provider.create_event(
                self.business_id,
                summary=f"Kaivix Demo Call - {lead.name or lead.email}",
                start_time=start_time,
                end_time=end_time,
                attendee_email=lead.email,
            )

            working_memory.set_offered_slots([])
            self._offered_slot_windows.pop(conversation_id, None)

            if result.get("success"):
                return {"confirmation": matched_slot_text, "failed": False}

            self.logger.error(
                f"[GoogleCalendarProvider] Booking attempt failed "
                f"(conversation_id={conversation_id}): {result.get('error')}"
            )
            return {"confirmation": "", "failed": True}

        except Exception as error:
            self.logger.error(
                f"[GoogleCalendarProvider] Failed to resolve booking "
                f"(conversation_id={conversation_id}): {error}"
            )
            return None

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
        """
        Lightweight debugging output to help future tuning.

        Unlike `Logger.log_user`/`log_ai`, this runs on the FastAPI serving
        path -- every `/chat/{business_id}` request reaches it -- so it is the
        turn-logging that actually matters for a deployed business.

        The structured fields below are kept in full: a stage, an intent, a
        goal, a completion percentage and a list of missing field *names*
        describe the conversation without describing the person having it.
        That is the same line Decision #026 drew for `log_lead`.

        The two narrative fields are the problem. `working_memory.summary`
        embeds the visitor's most recent objection verbatim, and
        `conversation_summary` is a generated paragraph that opens with the
        lead's name and then lists their known facts -- which is how addresses
        reached `logs/app.log` from here. So the summary is swept, and the
        narrative is withheld by default on the same switch as conversation
        bodies, because a name in prose is not something a sweep can find.

        Both the printed block and the log line are built from the same
        redacted list. Stdout is not a safer destination than the log file --
        under a container runtime it is collected the same way.
        """
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
            summary_lines.append(
                f"Working memory: {redact_free_text(working_memory.summary)}"
            )
            if working_memory.conversation_summary:
                turn = working_memory.summary_last_updated_turn

                if conversation_bodies_enabled():
                    narrative = redact_free_text(working_memory.conversation_summary)
                else:
                    narrative = (
                        f"<{len(working_memory.conversation_summary)} chars withheld>"
                    )

                summary_lines.append(f"Conversation summary (turn {turn}): {narrative}")

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