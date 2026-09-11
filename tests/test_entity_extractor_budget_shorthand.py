"""
"15k" is a budget.

Found in live production, in the logs of a conversation that would not
close: a visitor said "Our budget is 15k and timeline is next quarter"
and the turn summary still read `Missing fields: ['budget']`.
BUDGET_PATTERN required either a literal "$" or a digit run directly
adjacent to a currency word, and "15k" is neither -- the same shape as
the "one billion dollars" gap closed in 5a9d992, in the notation people
actually type rather than speak.

It is not a cosmetic gap. budget is a required field in
qualification.yaml, so the lead stayed un-qualified, Bray kept asking
about pricing instead of offering times, and the close never came.
"""

import unittest

from core_ai.customer_state import CustomerState
from core_ai.entity_extractor import EntityExtractor


class TestShorthandBudgets(unittest.TestCase):
    def _budget(self, message: str) -> str:
        state = CustomerState()
        EntityExtractor().extract(message, state)
        return (state.budget or "").strip()

    def test_the_verbatim_message_from_the_live_conversation(self):
        self.assertTrue(
            self._budget("Our budget is 15k and timeline is next quarter.")
        )

    def test_the_shorthand_forms_people_type(self):
        for message in [
            "our budget is 15k",
            "our budget is 15K",
            "budget around $15k",
            "we can do 50k",
            "somewhere near 1.5m",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self._budget(message), f"nothing captured for {message!r}")

    def test_existing_forms_are_unaffected(self):
        for message in [
            "our budget is $15,000",
            "we have 20000 dollars",
            "$2,500 / month",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self._budget(message))

    def test_a_bare_number_with_no_marker_is_still_not_a_budget(self):
        """
        The extractor is context-blind, so widening this to any bare
        number would turn "option 2" into a budget.
        """
        state = CustomerState()
        EntityExtractor().extract("2", state)
        self.assertFalse((state.budget or "").strip())

    def test_ordinary_words_ending_in_k_are_not_budgets(self):
        for message in ["we have 3 clinics", "about 12 staff"]:
            with self.subTest(message=message):
                self.assertFalse(self._budget(message))


if __name__ == "__main__":
    unittest.main()
