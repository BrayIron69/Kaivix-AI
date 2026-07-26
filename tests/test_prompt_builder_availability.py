import unittest
from types import SimpleNamespace

from core_ai.conversation_plan import ConversationPlan
from core_ai.prompt_builder import PromptBuilder


class TestPromptBuilderAvailabilitySection(unittest.TestCase):
    """
    Proves plan.available_slots is purely additive to PromptBuilder's
    output: byte-identical when empty (today's only real case, since no
    business has connected a calendar yet), and correctly rendered in a
    clearly labeled section when populated.
    """

    STAGE = "closing"
    INTENT = "buying_signal"
    GOAL = "book_demo"
    KNOWLEDGE = ""

    def _build(self, plan) -> str:
        return PromptBuilder().build(
            stage=self.STAGE,
            intent=self.INTENT,
            goal=self.GOAL,
            knowledge=self.KNOWLEDGE,
            plan=plan,
        )

    def test_empty_available_slots_produces_byte_identical_output(self):
        plan_with_field = ConversationPlan(
            strategy="drive_to_booking",
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
            available_slots=[],
        )

        # A plan-like object with no available_slots attribute at all --
        # simulates exactly what every plan looked like before this
        # field existed. PromptBuilder reads it via
        # getattr(plan, "available_slots", None) or [], so both must
        # produce identical output.
        plan_without_field = SimpleNamespace(
            strategy="drive_to_booking",
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
        )

        output_with_field = self._build(plan_with_field)
        output_without_field = self._build(plan_without_field)

        self.assertEqual(output_with_field, output_without_field)
        self.assertNotIn("REAL AVAILABLE TIMES", output_with_field)
        self.assertNotIn("available_slots", output_with_field)

    def test_populated_available_slots_are_rendered_in_labeled_section(self):
        plan = ConversationPlan(
            strategy="drive_to_booking",
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
            available_slots=[
                "Tuesday 2:00 PM - 3:00 PM",
                "Wednesday 10:00 AM - 11:00 AM",
                "Thursday 1:00 PM - 2:00 PM",
            ],
        )

        output = self._build(plan)

        self.assertIn("REAL AVAILABLE TIMES", output)
        self.assertIn("- Tuesday 2:00 PM - 3:00 PM", output)
        self.assertIn("- Wednesday 10:00 AM - 11:00 AM", output)
        self.assertIn("- Thursday 1:00 PM - 2:00 PM", output)

        # The section must come after the plan's strategy/next_question
        # lines, not scattered arbitrarily.
        strategy_index = output.index("Strategy: drive_to_booking")
        slots_index = output.index("REAL AVAILABLE TIMES")
        self.assertLess(strategy_index, slots_index)

    def test_no_plan_at_all_is_unaffected(self):
        # plan=None entirely (the default) must still skip every
        # plan-derived section, exactly as before this milestone.
        output = self._build(None)
        self.assertNotIn("REAL AVAILABLE TIMES", output)
        self.assertNotIn("CONVERSATION PLAN FOR THIS TURN", output)


if __name__ == "__main__":
    unittest.main()
