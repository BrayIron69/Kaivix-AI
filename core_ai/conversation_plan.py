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

    def to_dict(self) -> dict:
        return asdict(self)