import unittest
from types import SimpleNamespace

from core_ai.conversation_plan import ConversationPlan
from core_ai.prompt_builder import PromptBuilder


class TestPromptBuilderBookingSections(unittest.TestCase):
    """
    Proves plan.booking_confirmation / plan.booking_failed are purely
    additive to PromptBuilder's output: byte-identical when both are at
    their default (empty string / False), and correctly rendered when
    populated. Same discipline as test_prompt_builder_availability.py.
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

    def test_default_booking_fields_produce_byte_identical_output(self):
        plan_with_fields = ConversationPlan(
            strategy="drive_to_booking",
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
            booking_confirmation="",
            booking_failed=False,
        )

        # A plan-like object with neither attribute at all -- simulates
        # exactly what every plan looked like before these fields
        # existed. PromptBuilder reads them via getattr(..., "") or ""
        # / bool(getattr(..., False)), so both must produce identical
        # output.
        plan_without_fields = SimpleNamespace(
            strategy="drive_to_booking",
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
        )

        output_with_fields = self._build(plan_with_fields)
        output_without_fields = self._build(plan_without_fields)

        self.assertEqual(output_with_fields, output_without_fields)
        self.assertNotIn("BOOKING CONFIRMED", output_with_fields)
        self.assertNotIn("BOOKING SYSTEM ERROR", output_with_fields)

    def test_booking_confirmation_states_exact_time_but_not_as_a_system_line(self):
        plan = ConversationPlan(
            strategy="drive_to_booking",
            booking_confirmation="Wednesday 10:00 AM - 11:00 AM",
        )

        output = self._build(plan)

        self.assertIn("BOOKING CONFIRMED", output)
        # The exact fact must still be present, so the model has the
        # correct time available to state.
        self.assertIn("Wednesday 10:00 AM - 11:00 AM", output)
        # But the model must be told to phrase it naturally, not parrot
        # this instruction's own sentence structure back to the visitor
        # (the live-verification regression this guards against).
        self.assertIn("natural", output.lower())
        self.assertIn("not a system message", output.lower())
        self.assertIn("do not copy", output.lower())
        self.assertNotIn(
            "A real calendar event was just created for", output
        )
        self.assertNotIn("BOOKING SYSTEM ERROR", output)

    def test_booking_failed_is_narrated_with_calendly_fallback(self):
        plan = ConversationPlan(
            strategy="drive_to_booking",
            booking_failed=True,
        )

        output = self._build(plan)

        self.assertIn("BOOKING SYSTEM ERROR", output)
        self.assertIn("apologize", output.lower())
        # Kaivix's own persona.booking_link, resolved via the default
        # BusinessConfig this build() call falls back to.
        self.assertIn("calendly.com", output)
        self.assertNotIn("BOOKING CONFIRMED", output)

    def test_booking_confirmation_and_failed_can_both_appear_if_both_set(self):
        # Not a state ConversationEngine ever actually produces (see
        # ConversationPlan's docstring), but PromptBuilder itself makes
        # no assumption the two are mutually exclusive -- each section
        # is independently gated on its own field.
        plan = ConversationPlan(
            strategy="drive_to_booking",
            booking_confirmation="Tuesday 2:00 PM - 3:00 PM",
            booking_failed=True,
        )

        output = self._build(plan)

        self.assertIn("BOOKING CONFIRMED", output)
        self.assertIn("BOOKING SYSTEM ERROR", output)

    def test_no_plan_at_all_is_unaffected(self):
        output = self._build(None)
        self.assertNotIn("BOOKING CONFIRMED", output)
        self.assertNotIn("BOOKING SYSTEM ERROR", output)


class TestEngineRulesBookingHallucinationGuard(unittest.TestCase):
    """
    Guards the fix for the false-booking-confirmation gap: rule #8 alone
    pushes the model toward booking language with nothing constraining
    what it's allowed to claim about booking status. This proves the new
    rule is present in ENGINE_RULES (so it reaches the prompt on every
    build, regardless of which booking fields are set this turn) and
    that its presence doesn't disturb the existing byte-identical
    unset-fields behavior proven above.
    """

    def test_engine_rules_contains_the_booking_status_guard_rule(self):
        rules = PromptBuilder.ENGINE_RULES.format(max_sentences=4)

        self.assertIn("Never claim a booking succeeded, failed, or exists", rules)
        self.assertIn("Calendly", rules)
        # Deliberately does not repeat the exact "BOOKING CONFIRMED" /
        # "BOOKING SYSTEM ERROR" section headers here -- ENGINE_RULES is
        # always present in the prompt, so literal header text in the
        # rule would defeat the other tests' assertNotIn checks for
        # those headers when no booking outcome applies this turn.
        self.assertNotIn("BOOKING CONFIRMED", rules)
        self.assertNotIn("BOOKING SYSTEM ERROR", rules)

    def test_guard_rule_is_present_even_when_no_booking_fields_are_set(self):
        plan = SimpleNamespace(
            strategy="drive_to_booking",
            next_question="Ask if they'd like to book a free demo call and offer a time.",
            avoid_topics=[],
        )

        output = PromptBuilder().build(
            stage="closing",
            intent="buying_signal",
            goal="book_demo",
            knowledge="",
            plan=plan,
        )

        self.assertIn("Never claim a booking succeeded, failed, or exists", output)


if __name__ == "__main__":
    unittest.main()
