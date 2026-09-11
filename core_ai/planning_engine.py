from dataclasses import replace
from typing import Optional

from core_ai.business_config import (
    BusinessConfig,
    BusinessConfigRepository,
    DEFAULT_BUSINESS_ID,
)
from core_ai.conversation_plan import ConversationPlan
from core_ai.intents import Intent
from core_ai.stages import ConversationStage
from tools.factual_lookup_tool import FactualLookupTool

# Shared, process-lifetime repository for the default (Kaivix)
# BusinessConfig used whenever a caller doesn't pass one explicitly --
# same pattern as core_ai/qualification_engine.py and
# core_ai/prompt_builder.py.
_default_business_config_repository = BusinessConfigRepository()


class PlanningEngine:
    """
    PlanningEngine

    Deterministically decides the AI's next conversational step for the
    current turn: what to pursue (goal/strategy), why (reasoning), what
    to ask next, and what to avoid.

    Important: this engine does not recompute anything another engine
    already owns. It only *sequences* and *acts on* signals that have
    already been produced elsewhere in the pipeline:
      - stage            -> ConversationEngine._detect_stage
      - intent           -> IntentDetector / DecisionEngine
      - goal             -> GoalEngine (echoed through unchanged)
      - score/temperature/objections/buying_signals -> LeadIntelligenceEngine
        (read directly off CustomerState/LeadProfile)
      - qualification progress/missing fields -> QualificationEngine
      - repeat-question avoidance -> WorkingMemory (its
        `last_assistant_message` / `questions_answered`, not a fresh
        scan of raw history)

    `recommended_action` on the returned plan is always generated to
    match the branch's own strategy/next_question rather than echoed
    from `lead.recommended_action`. LeadIntelligenceEngine computes
    that field with its own, slightly different field-priority logic,
    so echoing it directly risked a plan whose recommended_action
    contradicted its own strategy/next_question.

    PromptBuilder consumes the resulting ConversationPlan for phrasing;
    it does not make any of these decisions itself.
    """

    PRICING_TOPIC = "pricing"

    HOT_TEMPERATURE = "Hot"

    # Used when a field has no prompt_hint of its own in the business's
    # qualification schema.
    _DEFAULT_FIELD_QUESTION = "Continue gathering qualification details."

    def __init__(self, business_config: Optional[BusinessConfig] = None):
        """
        Natural-language guidance for each qualification field, used only
        as a *suggestion* for the LLM's next question, is read from the
        business's own qualification schema
        (BusinessConfig.qualification.fields[].prompt_hint).

        This used to be a hardcoded _FIELD_QUESTIONS dict whose five
        entries were byte-identical copies of
        config/businesses/kaivix/qualification.yaml's prompt_hints --
        two places to edit for one fact, and every non-Kaivix business
        silently got Kaivix's wording (or the generic fallback for any
        field Kaivix doesn't have). qualification.yaml is now the single
        source of truth; the priority *order* of missing fields still
        comes from QualificationEngine and is not re-derived here.
        """
        if business_config is None:
            business_config = _default_business_config_repository.load(DEFAULT_BUSINESS_ID)

        self._field_questions = self._build_field_questions(business_config)
        # Which tools this business switched on. Read once here, the
        # same way the field questions are, so deciding whether to
        # request a tool stays a pure in-memory check and this engine
        # keeps performing no I/O.
        tools = getattr(business_config, "tools", None)
        self._enabled_tools = list(getattr(tools, "enabled_tools", None) or [])

    # Requested at the closing moment, when there is a real address to
    # send to. Named here rather than inline so the one string lives in
    # one place alongside the tool's own `name`.
    OVERVIEW_EMAIL_TOOL = "send_overview_email"

    # Answering "what's today's date" mid-conversation. Requested
    # whenever the visitor asks one, at any stage, since a factual
    # question is orthogonal to where qualification has got to.
    FACTUAL_LOOKUP_TOOL = "factual_lookup"

    @staticmethod
    def _build_field_questions(business_config) -> dict:
        """
        Map field id -> prompt_hint from the business's qualification
        schema. Read defensively (getattr rather than attribute access)
        so a partial config never breaks planning -- a field without a
        usable hint simply falls back to _DEFAULT_FIELD_QUESTION.
        """
        qualification = getattr(business_config, "qualification", None)
        fields = getattr(qualification, "fields", None) or []

        field_questions = {}
        for field in fields:
            field_id = getattr(field, "id", None)
            prompt_hint = getattr(field, "prompt_hint", "")
            if field_id and prompt_hint:
                field_questions[field_id] = prompt_hint

        return field_questions

    def plan(
        self,
        stage,
        intent,
        goal,
        lead=None,
        qualification=None,
        history=None,
        working_memory=None,
        user_message="",
    ) -> ConversationPlan:
        """
        Return a structured ConversationPlan for the current turn.

        Args:
            stage: ConversationStage for this turn.
            intent: Detected Intent for this turn.
            goal: Intent already selected by GoalEngine (echoed, not
                recomputed).
            lead: CustomerState/LeadProfile. Read-only here.
            qualification: The qualification progress dict already
                computed by QualificationEngine.qualification_progress()
                for this turn (contains "missing" and "qualified").
                Passed in rather than recomputed to avoid a duplicate
                calculation per turn.
            history: Optional list of {"role", "content"} message dicts
                for this conversation, used only as a fallback to avoid
                suggesting a question that was just asked, when
                `working_memory` isn't supplied.
            working_memory: Optional WorkingMemory for this
                conversation, already updated for this turn by
                ConversationEngine. When supplied, its
                `last_assistant_message` is used (instead of re-scanning
                `history`) to avoid immediately repeating a question.
                Read-only here — PlanningEngine never writes to it.
            user_message: This turn's raw visitor message, used only to
                recognise a simple factual question ("what's today's
                date"). Optional and defaulting to empty so every
                existing caller and test keeps working unchanged;
                without it, factual lookup simply never triggers.
        """
        plan = self._select_plan(
            stage, intent, goal, lead, qualification, history, working_memory
        )

        # Tool requests are attached AFTER the conversational plan is
        # chosen, never instead of it. A visitor asking what day it is
        # has not stopped being mid-qualification, and returning a
        # special "factual lookup" plan would throw away the strategy
        # and next question this turn still needs.
        return self._attach_tool_requests(plan, lead, user_message)

    def _select_plan(
        self,
        stage,
        intent,
        goal,
        lead=None,
        qualification=None,
        history=None,
        working_memory=None,
    ) -> ConversationPlan:
        """
        Choose the conversational plan for this turn. Unchanged branch
        logic, split out from plan() so tool requests can be attached to
        whatever it returns without every branch having to know about
        them.
        """
        goal_value = getattr(goal, "value", goal)
        intent_value = getattr(intent, "value", intent)

        objections = self._as_list(getattr(lead, "objections", None))
        buying_signals = self._as_list(getattr(lead, "buying_signals", None))
        temperature = getattr(lead, "temperature", "Cold") or "Cold"
        score = getattr(lead, "score", 0) or 0

        missing_fields = list((qualification or {}).get("missing", []))

        last_assistant_message = self._resolve_last_assistant_message(working_memory, history)

        # 1. Objections always take priority — including over pricing
        #    and over further qualification questions.
        if objections or stage == ConversationStage.OBJECTION_HANDLING or intent_value == Intent.OBJECTION.value:
            return self._plan_objection_handling(goal_value, objections, missing_fields)

        # 2. Hot leads (or an explicit closing stage) get steered toward
        #    booking, once there's little/nothing left to qualify.
        if stage == ConversationStage.CLOSING or (
            temperature == self.HOT_TEMPERATURE and len(missing_fields) <= 1
        ):
            return self._plan_closing(goal_value, temperature, score, missing_fields)

        # 3. Otherwise, keep collecting missing qualification info.
        if missing_fields:
            return self._plan_qualification(
                goal_value, missing_fields, intent_value, last_assistant_message,
            )

        # 4. Qualification is complete — continue discovery/presentation.
        return self._plan_discovery_or_presentation(goal_value, stage, temperature, buying_signals)

    # ------------------------------------------------------------------
    # Branch builders
    # ------------------------------------------------------------------

    def _plan_objection_handling(self, goal_value, objections, missing_fields):
        reasoning = "Lead has raised an objection; resolving it takes priority over qualification or pricing."
        if objections:
            reasoning += f" Known objections: {', '.join(objections)}."

        return ConversationPlan(
            goal=goal_value,
            strategy="acknowledge_and_reframe_objection",
            reasoning=reasoning,
            next_question="Acknowledge the objection, reframe it briefly, then check if it's resolved.",
            avoid_topics=[self.PRICING_TOPIC] if missing_fields else [],
            recommended_action="Address objections before continuing qualification.",
        )

    def _attach_tool_requests(self, plan, lead, user_message) -> ConversationPlan:
        """
        Attach at most one tool request to an already-chosen plan.

        Factual lookup is checked first and wins, because it answers
        something the visitor asked outright this turn, whereas the
        overview email is something the system decided to do. Answering
        the question in front of you takes precedence over the follow-up
        you had planned.

        Records the request only: no send, no network call, nothing
        checked about deliverability. ConversationEngine does all of
        that one step later, which is what keeps this engine stateless
        and I/O-free exactly as its docstring promises.
        """
        factual = self._factual_lookup_request(user_message)
        if factual is not None:
            return replace(plan, tool_request=factual)

        return self._attach_overview_email_request(plan, lead)

    def _factual_lookup_request(self, user_message):
        """
        A factual-lookup request when the visitor asked a simple factual
        question this turn, else None.

        Restricted to DATE/TIME questions on purpose. Those are the ones
        FactualLookupTool answers from the clock with no API key and no
        network call, so they work everywhere, always. Triggering on
        anything broader would mean routinely requesting a lookup that
        fails for want of WEB_SEARCH_API_KEY -- a tool that usually
        declines is worse than one with a narrow, honest scope.
        """
        if self.FACTUAL_LOOKUP_TOOL not in self._enabled_tools:
            return None

        message = (user_message or "").strip()
        if not message or not FactualLookupTool.is_simple_date_question(message):
            return None

        return {"name": self.FACTUAL_LOOKUP_TOOL, "args": {"question": message}}

    def _attach_overview_email_request(self, plan, lead) -> ConversationPlan:
        """
        Request the follow-up overview email, at the closing moment and
        only then.

        Deliberately narrow. Sending real mail to a real prospect is a
        side effect that cannot be taken back, so the trigger is the one
        point in the conversation where a follow-up is unambiguously the
        right next action: the lead is qualified enough to be driven
        toward booking (this is the closing branch) AND there is a real
        address on file to send to.

        Records the request only. It performs no send, makes no network
        call, and checks nothing about whether mail is actually
        deliverable -- ConversationEngine does all of that one step
        later, and is also what enforces once-per-conversation, since it
        owns the record of what has already been done. This engine stays
        stateless and I/O-free, exactly as its docstring promises.
        """
        if plan.strategy != "drive_to_booking":
            return plan

        if self.OVERVIEW_EMAIL_TOOL not in self._enabled_tools:
            return plan

        recipient = (getattr(lead, "email", "") or "").strip()
        if not recipient:
            return plan

        return replace(
            plan,
            tool_request={"name": self.OVERVIEW_EMAIL_TOOL, "args": {}},
        )

    def _plan_closing(self, goal_value, temperature, score, missing_fields):
        reasoning = (
            f"Lead temperature is {temperature} (score {score}) with "
            f"{len(missing_fields)} qualification field(s) remaining; "
            "moving toward booking a meeting."
        )
        return ConversationPlan(
            goal=goal_value,
            strategy="drive_to_booking",
            reasoning=reasoning,
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
            recommended_action="Move toward booking a meeting or demo.",
        )

    def _plan_qualification(self, goal_value, missing_fields, intent_value, last_assistant_message):
        target_field = missing_fields[0]

        # Avoid immediately repeating the question we just asked.
        if len(missing_fields) > 1 and last_assistant_message:
            candidate_question = self._field_questions.get(target_field, "")
            if candidate_question and candidate_question in last_assistant_message:
                target_field = missing_fields[1]

        next_question = self._field_questions.get(
            target_field, self._DEFAULT_FIELD_QUESTION
        )

        # Don't volunteer pricing while qualification is still incomplete,
        # unless the visitor is the one explicitly asking about it.
        avoid_topics = []
        if intent_value != Intent.PRICING.value:
            avoid_topics.append(self.PRICING_TOPIC)

        reasoning = (
            f"Qualification incomplete (missing: {', '.join(missing_fields)}); "
            f"asking for '{target_field}' next, the highest-priority missing field."
        )

        return ConversationPlan(
            goal=goal_value,
            strategy=f"collect_missing_field:{target_field}",
            reasoning=reasoning,
            next_question=next_question,
            avoid_topics=avoid_topics,
            recommended_action=f"Ask about {target_field}.",
        )

    def _plan_discovery_or_presentation(self, goal_value, stage, temperature, buying_signals):
        if buying_signals:
            reasoning = (
                f"Qualification is complete and the lead has shown buying signals "
                f"({', '.join(buying_signals)}); presenting the solution and next step."
            )
            strategy = "present_solution_and_advance"
            next_question = "Summarize the fit and ask if they'd like to see it in action or book a call."
            action = "Present the solution and suggest the next step."
        elif stage == ConversationStage.GREETING:
            reasoning = "Start of conversation; open with discovery about their business needs."
            strategy = "greet_and_open_discovery"
            next_question = "Ask what's bringing them to look into an AI assistant right now."
            action = "Continue qualification naturally."
        else:
            reasoning = (
                f"Qualification is complete; continuing discovery/presentation "
                f"for a {temperature.lower()} lead."
            )
            strategy = "continue_discovery"
            next_question = "Ask a follow-up question about their current process or pain point."
            action = "Continue qualification naturally."

        return ConversationPlan(
            goal=goal_value,
            strategy=strategy,
            reasoning=reasoning,
            next_question=next_question,
            avoid_topics=[],
            recommended_action=action,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _as_list(value):
        return value if isinstance(value, list) else []

    @classmethod
    def _resolve_last_assistant_message(cls, working_memory, history) -> str:
        """
        Prefer WorkingMemory's already-computed last assistant message
        (so history-scanning logic lives in one place). Fall back to
        scanning `history` directly only when no WorkingMemory was
        supplied, preserving the original behavior for backward
        compatibility.
        """
        if working_memory is not None:
            return getattr(working_memory, "last_assistant_message", "") or ""
        return cls._last_assistant_message(history)

    @staticmethod
    def _last_assistant_message(history):
        if not history:
            return ""
        for turn in reversed(history):
            if turn.get("role") == "assistant":
                return turn.get("content", "") or ""
        return ""