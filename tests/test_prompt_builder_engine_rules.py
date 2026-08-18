import unittest
from types import SimpleNamespace

from core_ai.prompt_builder import PromptBuilder


class TestEngineRulesGeneralActionHallucinationGuard(unittest.TestCase):
    """
    Guards the general anti-hallucination rule added alongside the
    booking-specific one in core_ai/prompt_builder.py's ENGINE_RULES.

    Rule #11 only covers booking status. It does not stop Bray from
    claiming some other action happened -- e.g. "I've sent you a
    checklist by email" when no email was ever sent, or "you're all set
    up" when nothing was set up. This proves the new, action-agnostic
    rule is present in ENGINE_RULES on every build, and that it does not
    quote either booking section's literal header text (which would
    defeat test_prompt_builder_booking.py's assertNotIn checks for those
    headers when no booking outcome applies this turn).
    """

    def test_engine_rules_contains_the_general_action_guard_rule(self):
        rules = PromptBuilder.ENGINE_RULES.format(max_sentences=4)

        self.assertIn(
            "Never claim to have performed, sent, set up, created, "
            "confirmed, or completed any action",
            rules,
        )
        self.assertIn("dedicated section of this prompt explicitly confirms", rules)
        self.assertNotIn("BOOKING CONFIRMED", rules)
        self.assertNotIn("BOOKING SYSTEM ERROR", rules)

    def test_guard_rule_is_present_even_when_no_dedicated_sections_are_set(self):
        plan = SimpleNamespace(
            strategy="qualify",
            next_question="Ask what they'd like automated.",
            avoid_topics=[],
        )

        output = PromptBuilder().build(
            stage="qualifying",
            intent="general_question",
            goal="qualify",
            knowledge="",
            plan=plan,
        )

        self.assertIn(
            "Never claim to have performed, sent, set up, created, "
            "confirmed, or completed any action",
            output,
        )


class TestEngineRulesResponseSpecificityAndStyle(unittest.TestCase):
    """
    Guards the response-specificity and em-dash style rules added
    alongside the general action-hallucination guard -- both meant to
    calibrate response quality for the current model rather than fix a
    correctness gap, so there's no live-conversation regression to
    reproduce here; this just proves the instructions reach the prompt.
    """

    def test_engine_rules_instructs_specific_answers_over_padding(self):
        rules = PromptBuilder.ENGINE_RULES.format(max_sentences=4)

        self.assertIn("specific facts, names, and numbers", rules)
        self.assertIn("vague reassurance language", rules)

    def test_engine_rules_instructs_avoiding_em_dashes(self):
        rules = PromptBuilder.ENGINE_RULES.format(max_sentences=4)

        self.assertIn("Do not use em dashes", rules)


if __name__ == "__main__":
    unittest.main()
