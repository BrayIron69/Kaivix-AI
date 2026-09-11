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

    # A tool PlanningEngine has deterministically decided should run
    # this turn, as {"name": str, "args": dict}, or None. PlanningEngine
    # only ever RECORDS the request -- it performs no I/O, same as it
    # never sets available_slots or booking_confirmation above.
    # ConversationEngine._maybe_run_requested_tool executes it one step
    # later and writes tool_result below.
    #
    # Deliberately not an LLM function call: the model deciding when to
    # send real mail to a real prospect is the exact failure Decision
    # #030's unbacked-action gate exists to prevent.
    tool_request: dict = None

    # The ToolResult of tool_request, as a dict, or None when no tool
    # ran. PromptBuilder renders a confirmation ONLY when this says
    # success -- so Bray stating that an email went out is downstream of
    # an email actually going out, never downstream of the conversation
    # feeling like it should have.
    tool_result: dict = None

    def to_dict(self) -> dict:
        return asdict(self)