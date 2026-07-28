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

        # Numbered list, in the exact order given -- not bullets --
        # matching what slot_matcher expects the visitor to reply with.
        self.assertIn("1. Tuesday 2:00 PM - 3:00 PM", output)
        self.assertIn("2. Wednesday 10:00 AM - 11:00 AM", output)
        self.assertIn("3. Thursday 1:00 PM - 2:00 PM", output)

        # Explicit instruction to present the times as a numbered list,
        # ask for a numeric reply, and treat it as the only question
        # this message asks -- otherwise slot_matcher's strict
        # digit/ordinal matching never gets a natural trigger in the
        # real conversation (the exact gap a live end-to-end run found).
        self.assertIn("numbered list", output)
        self.assertIn("reply with the number", output)
        self.assertIn("only question to ask in this message", output)

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
