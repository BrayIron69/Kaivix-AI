from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class ConversationPlan:
    """
    Structured output of the PlanningEngine.

    Represents the AI's short-term conversational plan for the
    current turn: what it is trying to achieve, how, why, what to
    ask next, and what to avoid.

    This is a data contract only. It is populated with placeholder
    defaults for now — PlanningEngine does not yet perform real
    planning logic (see core_ai/planning_engine.py).
    """

    goal: str = ""
    strategy: str = ""
    reasoning: str = ""
    next_question: str = ""
    avoid_topics: List[str] = field(default_factory=list)
    recommended_action: str = ""

    # Populated only by ConversationEngine._maybe_attach_availability,
    # after PlanningEngine has already returned its plan -- PlanningEngine
    # itself never sets this (it performs no I/O). Human-readable open
    # time windows (e.g. "Tuesday 2:00 PM - 3:00 PM") from
    # GoogleCalendarProvider.get_free_busy_slots, ready for PromptBuilder
    # to insert directly into prompt text. Empty for every plan that
    # isn't strategy="drive_to_booking" for a business with a connected
    # calendar -- i.e. empty for every plan today.
    available_slots: List[str] = field(default_factory=list)

    # Populated only by ConversationEngine._maybe_resolve_booking, after
    # PlanningEngine has already returned its plan -- same pattern as
    # available_slots above; PlanningEngine never sets either. Set to the
    # exact matched slot's display text (e.g. "Tuesday 2:00 PM - 3:00 PM")
    # when a visitor's reply was just resolved into a real calendar
    # booking this turn, so PromptBuilder can have Bray confirm that
    # EXACT text back verbatim rather than risk the LLM paraphrasing (and
    # potentially misstating) the confirmed time. Empty otherwise.
    booking_confirmation: str = ""

    # Companion to booking_confirmation: true when a visitor's reply
    # matched an offered slot but the actual calendar booking attempt
    # failed (GoogleCalendarProvider.create_event returned
    # success=False), so PromptBuilder can have Bray apologize and offer
    # the existing Calendly link as a fallback instead of silently
    # dropping the booking. False otherwise -- and never true at the
    # same time as a non-empty booking_confirmation.
    booking_failed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)