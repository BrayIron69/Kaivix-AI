"""
Company captured from a natural self-introduction.

Found by running a real fully-qualified conversation through live
production and reading the CRM row it produced: "I am Dana Verify from
Verify Dental Group..." stored name, email, budget and timeline but left
company EMPTY, because COMPANY_PATTERNS had no "<name> from <company>"
form at all. That left the lead permanently un-qualified, and since a
qualified lead is what triggers the close, Bray would never ask for the
meeting.
"""

import unittest

from core_ai.entity_extractor import EntityExtractor
from core_ai.customer_state import CustomerState


class TestCompanyFromSelfIntroduction(unittest.TestCase):
    def _company(self, message: str):
        state = CustomerState()
        EntityExtractor().extract(message, state)
        return (state.company or "").strip()

    def test_the_verbatim_message_from_the_live_check(self):
        company = self._company(
            "Hi, I am Dana Verify from Verify Dental Group, email "
            "dana-verify@example.com. Our budget is 20000 dollars."
        )
        self.assertEqual(company, "Verify Dental Group")

    def test_the_common_introduction_forms(self):
        for message, expected in [
            ("I'm Dana from Ridgeline Dental", "Ridgeline Dental"),
            ("this is Dana from Ridgeline Dental", "Ridgeline Dental"),
            ("I work for Ridgeline Dental", "Ridgeline Dental"),
            ("calling from Ridgeline Dental", "Ridgeline Dental"),
        ]:
            with self.subTest(message=message):
                self.assertEqual(self._company(message), expected)

    def test_a_location_is_not_mistaken_for_an_employer(self):
        """
        "I'm from Boston" is where someone lives, not who they work for.
        Requiring at least one word between the pronoun and "from" is
        what separates the two.
        """
        self.assertEqual(self._company("I'm from Boston"), "")
        self.assertEqual(self._company("I am from the UK"), "")

    def test_existing_patterns_are_unaffected(self):
        for message, expected in [
            ("my company is Acme Co", "Acme Co"),
            ("we run a dental clinic", "dental clinic"),
            ("I work at Ridgeline Dental", "Ridgeline Dental"),
        ]:
            with self.subTest(message=message):
                self.assertEqual(self._company(message), expected)


if __name__ == "__main__":
    unittest.main()
