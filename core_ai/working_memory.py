from __future__ import annotations


class WorkingMemory:
    """
    WorkingMemory

    Tracks *conversational* context for a single conversation: what has
    been asked, answered, and learned so far, and a compact rolling
    view of where the conversation currently stands.

    This is intentionally separate from CustomerState/LeadProfile.
    CustomerState remains the single source of truth for business data
    about the lead (identity, budget, timeline, score, temperature,
    objections, buying_signals, etc.). WorkingMemory owns none of that
    data and recomputes nothing another engine already owns — every
    field here is copied, once per turn, from a value some other
    engine already produced this turn:

      - facts learned                    <- lead.known_facts
                                             (written by EntityExtractor)
      - outstanding qualification items  <- qualification["missing"]
                                             (written by QualificationEngine)
      - current conversation objective   <- goal
                                             (written by GoalEngine)
      - current objection                <- lead.objections
                                             (written by EntityExtractor)
      - buying signals                   <- lead.buying_signals
                                             (written by EntityExtractor)
      - current lead temperature         <- lead.temperature
                                             (written by LeadIntelligenceEngine)
      - questions asked / answered       <- derived from raw conversation
                                             history, since
                                             CustomerState.last_questions is
                                             defined but never populated by
                                             any engine (see handoff §8)
      - conversation_summary             <- ConversationSummary.build(...)
                                             (written by ConversationEngine,
                                             periodically, via
                                             set_conversation_summary(); see
                                             below)

    `conversation_summary` is the one field on this object that is not
    refreshed by `update()` every turn. It holds the latest narrative
    text produced by the separate `ConversationSummary` engine, which
    ConversationEngine refreshes only every N turns (configurable),
    since it is meant to be a denser, periodically-updated summary
    rather than a cheap per-turn recomputation like every other field
    here. `set_conversation_summary()` is the only other way anything
    may write to a WorkingMemory instance besides `update()` itself, and
    it is only ever called by ConversationEngine after
    `ConversationSummary.build(...)` has computed the text —
    WorkingMemory does not build that narrative itself.

    `offered_slots` follows the exact same pattern: `update()` never
    touches it, and `set_offered_slots()` is the only other way anything
    may write to it. It holds the real, human-readable calendar time
    windows (e.g. "Tuesday 2:00 PM - 3:00 PM") that were most recently
    offered to this visitor, so a later turn's numeric reply ("2", "the
    second one") can be resolved back into an actual booking by
    ConversationEngine — see `_maybe_attach_availability` (which sets it)
    and `_maybe_resolve_booking` (which reads and clears it).

    PlanningEngine consumes this object (specifically
    `last_assistant_message` / `questions_answered`) instead of scanning
    raw history itself, so that history-scanning logic for "was this
    already asked/answered" lives in exactly one place. PromptBuilder
    renders a compact summary of it into the system prompt.

    One WorkingMemory instance is kept per conversation_id by
    ConversationEngine, the same way ConversationMemory and lead
    profiles are kept per-conversation.
    """

    def __init__(self) -> None:
        self.facts: list[str] = []
        self.questions_asked: list[str] = []
        self.questions_answered: list[str] = []
        self.outstanding_qualification_items: list[str] = []
        self.objective: str = ""
        self.current_objection: str = ""
        self.buying_signals: list[str] = []
        self.temperature: str = "Cold"
        self.summary: str = ""

        # Richer narrative summary, produced by the separate
        # ConversationSummary engine and refreshed only periodically by
        # ConversationEngine (not every turn, unlike `summary` above).
        # See set_conversation_summary() and the `turn_count` property.
        self.conversation_summary: str = ""
        self.summary_last_updated_turn: int = 0

        # Real calendar time windows most recently offered to this
        # visitor (see set_offered_slots()). Not refreshed by update() --
        # same "explicit setter only" pattern as conversation_summary
        # above.
        self.offered_slots: list[str] = []

        # Not one of the explicitly tracked fields, but needed by
        # PlanningEngine for repeat-question avoidance. Kept here so
        # that raw-history scanning happens in exactly one place
        # instead of being duplicated inside PlanningEngine.
        self.last_assistant_message: str = ""

        self._turn_count: int = 0

    def update(
        self,
        *,
        lead=None,
        qualification: dict | None = None,
        goal=None,
        history: list[dict] | None = None,
    ) -> "WorkingMemory":
        """
        Refresh working memory for the current turn.

        Called once per turn by ConversationEngine, after qualification
        progress and the goal have already been computed, and before
        planning — so PlanningEngine can consume the refreshed object.

        Every argument is a value already produced elsewhere in the
        pipeline this turn; nothing is recalculated here.
        """
        self._turn_count += 1

        if lead is not None:
            self.facts = list(getattr(lead, "known_facts", None) or [])
            self.buying_signals = list(getattr(lead, "buying_signals", None) or [])
            self.temperature = getattr(lead, "temperature", None) or "Cold"
            objections = getattr(lead, "objections", None) or []
            self.current_objection = objections[-1] if objections else ""

        if qualification is not None:
            self.outstanding_qualification_items = list(qualification.get("missing", []))

        if goal is not None:
            self.objective = getattr(goal, "value", goal)

        if history is not None:
            self._update_questions(history)

        self.summary = self._build_summary()

        return self

    def was_answered(self, question_text: str) -> bool:
        """True if `question_text` was already asked and then followed by a reply."""
        return question_text in self.questions_answered

    @property
    def turn_count(self) -> int:
        """
        Number of times `update()` has been called for this conversation
        (i.e. how many turns have been processed). Read-only; used by
        ConversationEngine to decide when a periodic ConversationSummary
        refresh is due, without reaching into a private attribute.
        """
        return self._turn_count

    def set_conversation_summary(self, summary_text: str) -> None:
        """
        Store a narrative summary produced by the separate
        ConversationSummary engine onto this WorkingMemory instance.

        This is the only way anything other than `update()` may write to
        WorkingMemory, and it is only ever called by ConversationEngine
        after `ConversationSummary.build(...)` has computed the text —
        WorkingMemory never builds this narrative itself, matching the
        "no duplicated business logic" rule the rest of this class
        already follows.
        """
        self.conversation_summary = summary_text or ""
        self.summary_last_updated_turn = self._turn_count

    def set_offered_slots(self, slots: list[str]) -> None:
        """
        Store the real calendar time windows just offered to this
        visitor onto this WorkingMemory instance.

        This is the only way anything other than `update()` may write to
        `offered_slots`, and it is only ever called by ConversationEngine
        after `GoogleCalendarProvider.get_free_busy_slots(...)` (or its
        structured equivalent) has computed the available windows —
        WorkingMemory never looks up or formats calendar availability
        itself, matching the "no duplicated business logic" rule the
        rest of this class already follows.
        """
        self.offered_slots = list(slots or [])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_questions(self, history: list[dict]) -> None:
        asked: list[str] = []
        answered: list[str] = []

        for index, turn in enumerate(history):
            if turn.get("role") != "assistant":
                continue

            content = (turn.get("content") or "").strip()
            if not content:
                continue

            # Most recent assistant message overall, question or not —
            # mirrors what PlanningEngine previously scanned history for.
            self.last_assistant_message = content

            if "?" not in content:
                continue

            asked.append(content)

            next_turn = history[index + 1] if index + 1 < len(history) else None
            if next_turn is not None and next_turn.get("role") == "user":
                answered.append(content)

        self.questions_asked = asked
        self.questions_answered = answered

    def _build_summary(self) -> str:
        parts = [f"Turn {self._turn_count}"]

        if self.objective:
            parts.append(f"objective={self.objective}")

        parts.append(f"temperature={self.temperature}")

        if self.outstanding_qualification_items:
            parts.append("missing=" + ",".join(self.outstanding_qualification_items))
        else:
            parts.append("qualification=complete")

        if self.current_objection:
            parts.append(f"objection={self.current_objection}")

        if self.buying_signals:
            parts.append("buying_signals=" + ",".join(self.buying_signals))

        return " | ".join(parts)

    def to_dict(self) -> dict:
        return {
            "facts": list(self.facts),
            "questions_asked": list(self.questions_asked),
            "questions_answered": list(self.questions_answered),
            "outstanding_qualification_items": list(self.outstanding_qualification_items),
            "objective": self.objective,
            "current_objection": self.current_objection,
            "buying_signals": list(self.buying_signals),
            "temperature": self.temperature,
            "summary": self.summary,
            "conversation_summary": self.conversation_summary,
            "summary_last_updated_turn": self.summary_last_updated_turn,
            "offered_slots": list(self.offered_slots),
        }