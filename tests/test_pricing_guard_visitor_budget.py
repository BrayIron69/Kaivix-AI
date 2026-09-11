"""
Bray can repeat a budget back to the person who just stated it.

The pricing guard flagged every dollar figure Bray was not cleared to
say -- including one the VISITOR had said seconds earlier. A visitor
typing "our budget is 20000 dollars" had Bray's entire reply replaced by
the deflection, twice in one real test conversation, purely for
acknowledging their own number.

Comparing spellings was not enough either, which a second live
conversation showed: the visitor typed "15k", Bray repeated it as
"$15,000", and an exact-match allowance missed it. The comparison is on
VALUE.

None of this widens what Bray may claim about Kaivix's own pricing: the
allowance is per-conversation and derived only from what the visitor
actually typed.
"""

import unittest

from core_ai.pricing_guard import (
    amounts_stated_by,
    contains_unapproved_price,
    find_unapproved_figures,
)


def _said(*messages):
    return [{"role": "user", "content": m} for m in messages]


class TestReadingWhatTheVisitorStated(unittest.TestCase):
    def test_the_forms_people_actually_type(self):
        for text, expected in [
            ("our budget is $15,000", 15000),
            ("our budget is $15k", 15000),
            ("our budget is 15k", 15000),
            ("our budget is 15K", 15000),
            ("our budget is 20000 dollars", 20000),
            ("we have 15000 set aside", 15000),
            ("we could go to 2m", 2_000_000),
        ]:
            with self.subTest(text=text):
                self.assertIn(expected, amounts_stated_by(_said(text)))

    def test_small_bare_numbers_are_not_budgets(self):
        """
        Picking slot "2" must never quietly authorise Bray to say "$2".
        A bare number needs four digits to count.
        """
        self.assertEqual(amounts_stated_by(_said("2")), set())
        self.assertEqual(amounts_stated_by(_said("option 3 please")), set())

    def test_only_the_visitors_own_turns_count(self):
        """
        Reading the assistant's turns too would let one invented figure
        launder itself into being allowed for the rest of the
        conversation.
        """
        history = [
            {"role": "assistant", "content": "It's usually around $9,500."},
            {"role": "user", "content": "our budget is 15k"},
        ]

        stated = amounts_stated_by(history)

        self.assertIn(15000, stated)
        self.assertNotIn(9500, stated)


class TestTheGuardAllowsTheirNumberBack(unittest.TestCase):
    def test_echoing_the_stated_budget_is_allowed_in_any_spelling(self):
        stated = amounts_stated_by(_said("our budget is 15k"))

        for response in [
            "Got it, $15,000 is a realistic range for that build.",
            "With $15,000 we can cover support and scheduling.",
        ]:
            with self.subTest(response=response):
                self.assertEqual(find_unapproved_figures(response, stated), [])

    def test_a_figure_the_visitor_never_said_is_still_blocked(self):
        stated = amounts_stated_by(_said("our budget is 15k"))

        self.assertEqual(
            find_unapproved_figures("Setup is usually $40,000.", stated),
            ["$40,000"],
        )

    def test_the_original_incident_phrasing(self):
        stated = amounts_stated_by(_said("Our budget is 20000 dollars."))
        self.assertEqual(
            find_unapproved_figures("$20,000 works well for that scope.", stated), []
        )

    def test_with_no_conversation_nothing_extra_is_allowed(self):
        """
        The knowledge-base scan has no conversation and must stay
        absolute, so the default has to allow nothing.
        """
        self.assertEqual(
            find_unapproved_figures("Setup starts at $15,000."), ["$15,000"]
        )
        self.assertTrue(contains_unapproved_price("Setup starts at $15,000."))

    def test_the_approved_staff_comparison_still_passes(self):
        self.assertEqual(find_unapproved_figures("between $1,500 and $3,000"), [])


if __name__ == "__main__":
    unittest.main()
