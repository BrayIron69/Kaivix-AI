"""
Bray must never send a visitor a price it invented.

knowledge/kaivix/pricing.md's Pricing Conversation Policy and
ENGINE_RULES rule #7 both forbid it, but both are instructions the model
can decline. A 150-run soak of the just_tell_me_the_price eval scenario
measured how often it does: 4 failures, ~2.7%, every one a genuinely
fabricated figure rather than a false positive.

The responses in REAL_LEAKED_RESPONSES below are verbatim from that
soak. None of those numbers exist anywhere the model can read -- the
real figures live in docs/Internal_Pricing_Reference.md, which
KnowledgeBase structurally cannot reach -- so the model invented them,
and invented them badly: "$5,000 and $15,000" for something that
actually costs under $2,500.

core_ai/pricing_guard.py is the deterministic backstop, in the same
spirit as Decision #030's action gate: the prompt rule stays as a first
line of defense, but the guarantee no longer depends on it.
"""

import unittest
from unittest.mock import MagicMock

from core_ai.conversation_engine import ConversationEngine
from core_ai.pricing_guard import (
    PRICE_DEFLECTION_RESPONSE,
    contains_unapproved_price,
    find_unapproved_figures,
)

# Verbatim from the 150-run soak that found this.
REAL_LEAKED_RESPONSES = [
    "Our pricing is structured as a one-time setup fee to build and train "
    "your custom AI employee, plus a modest monthly retainer. E.g., a "
    "support bot might start at a few thousand dollars setup and "
    "$500‑$800 per month.",
    "Our AI employee projects typically involve a one-time setup fee that "
    "varies with the scope, usually between $5,000 and $15,000, and a "
    "monthly retainer of $500‑$1,500 for hosting.",
    "Depending on the complexity, the setup typically ranges from $5 k to "
    "$10 k and the monthly retainer from $500 to $1.5 k.",
    "a modest monthly retainer (typically $500‑$1,500) that covers "
    "hosting, monitoring and ongoing improvements.",
]

# The one comparison pricing.md explicitly approves Bray to say aloud,
# in the exact and paraphrased forms the model actually produces.
APPROVED_RESPONSES = [
    "A part-time employee costs $1,500 to $3,000 per month minimum, and an "
    "AI employee costs a fraction of that.",
    "a part-timer runs $1.5-3 K a month, an AI employee is a fraction of that",
    "a part-timer runs $1.5‑3K a month",
]

# Legitimate pricing answers that follow the policy: shape, not numbers.
CLEAN_RESPONSES = [
    "Pricing depends on what you're automating. It's a one-time setup fee "
    "plus a small monthly retainer, and the exact number depends on scope.",
    "What are you looking to automate -- support, leads, voice, or custom?",
    "",
]


class TestFindUnapprovedFigures(unittest.TestCase):
    def test_every_real_leaked_response_is_detected(self):
        for response in REAL_LEAKED_RESPONSES:
            with self.subTest(response=response[:60]):
                self.assertTrue(
                    contains_unapproved_price(response),
                    "A price the model actually invented in production-shaped "
                    "output was not detected.",
                )
                self.assertTrue(find_unapproved_figures(response))

    def test_approved_staff_cost_comparison_is_not_flagged(self):
        for response in APPROVED_RESPONSES:
            with self.subTest(response=response[:60]):
                self.assertEqual(
                    find_unapproved_figures(response), [],
                    "The approved staff-cost comparison was treated as a leak; "
                    "blocking it would suppress messaging pricing.md "
                    "explicitly permits.",
                )

    def test_clean_responses_are_not_flagged(self):
        for response in CLEAN_RESPONSES:
            with self.subTest(response=response[:60]):
                self.assertFalse(contains_unapproved_price(response))

    def test_none_is_handled(self):
        self.assertEqual(find_unapproved_figures(None), [])

    def test_a_figure_next_to_the_approved_one_is_still_caught(self):
        """
        The approved comparison must not become a shield for an invented
        figure sitting beside it.
        """
        response = (
            "A part-time employee costs $1,500 to $3,000 per month, and our "
            "setup fee is $7,500."
        )

        self.assertEqual(find_unapproved_figures(response), ["$7,500"])


class TestEngineBlocksInventedPrices(unittest.TestCase):
    """
    The guard where it actually matters: on the response the engine is
    about to send and store.
    """

    def setUp(self):
        self.engine = ConversationEngine()
        self.engine.logger = MagicMock()

    def _guard(self, response: str) -> str:
        return self.engine._guard_against_invented_price("conv-1", response)

    def test_invented_price_is_replaced_with_the_deflection(self):
        for response in REAL_LEAKED_RESPONSES:
            with self.subTest(response=response[:60]):
                self.assertEqual(self._guard(response), PRICE_DEFLECTION_RESPONSE)

    def test_the_replacement_itself_contains_no_dollar_figure(self):
        """A deflection that leaked a number would defeat the point."""
        self.assertEqual(find_unapproved_figures(PRICE_DEFLECTION_RESPONSE), [])
        self.assertNotIn("$", PRICE_DEFLECTION_RESPONSE)

    def test_the_replacement_still_moves_the_conversation_forward(self):
        """
        Per pricing.md's policy: give the shape, offer a real next step.
        A guard that just stonewalls would cost a qualified lead.
        """
        lowered = PRICE_DEFLECTION_RESPONSE.lower()

        self.assertIn("setup fee", lowered)
        self.assertIn("retainer", lowered)
        self.assertIn("discovery call", lowered)
        self.assertIn("automate", lowered)

    def test_approved_and_clean_responses_pass_through_untouched(self):
        for response in APPROVED_RESPONSES + CLEAN_RESPONSES:
            with self.subTest(response=response[:60]):
                self.assertEqual(self._guard(response), response)

    def test_blocking_is_logged_as_an_error_with_the_figures(self):
        self._guard("our setup fee is $7,500 and the retainer is $400")

        self.engine.logger.error.assert_called_once()
        logged = self.engine.logger.error.call_args[0][0]
        self.assertIn("PricingGuard", logged)
        self.assertIn("$7,500", logged)
        self.assertIn("$400", logged)

    def test_a_clean_response_logs_nothing(self):
        self._guard("Pricing depends on scope -- what are you automating?")

        self.engine.logger.error.assert_not_called()


class TestInventedPriceNeverReachesHistory(unittest.TestCase):
    """
    The guard runs before the response is stored, so an invented price
    cannot survive in conversation history either -- where it would be
    replayed into later prompts and shown in the admin transcript.
    """

    def test_guard_runs_before_the_response_is_stored(self):
        engine = ConversationEngine()
        engine.logger = MagicMock()
        engine.memory = MagicMock()

        leaked = "our setup fee is $9,000"
        guarded = engine._guard_against_invented_price("conv-1", leaked)

        engine.memory.add_assistant_message("conv-1", guarded)

        stored = engine.memory.add_assistant_message.call_args[0][1]
        self.assertNotIn("$9,000", stored)
        self.assertEqual(stored, PRICE_DEFLECTION_RESPONSE)


if __name__ == "__main__":
    unittest.main()
