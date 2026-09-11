"""
The two scheduling fabrications from a real test conversation:
inventing available times, and claiming a booking that never happened.

The plan is the sole authority on both -- plan.available_slots comes
only from real free/busy windows, plan.booking_confirmation only from a
create_event that actually succeeded -- so these tests drive the guard
with the plan in each state and assert on what survives.
"""

import unittest
from unittest.mock import MagicMock

from core_ai.booking_claim_guard import (
    claims_a_booking_happened,
    states_specific_availability,
)
from core_ai.conversation_plan import ConversationPlan
from core_ai.lead_profile import LeadProfile
from tests.test_ai_disclosure import _IsolatedDatabasesMixin


class TestDetectsInventedAvailability(unittest.TestCase):
    def test_the_shape_the_real_incident_produced(self):
        for response in [
            "Here are a few slots we have open:\n\n1. Friday 9:00 AM - 9:30 AM\n2. Friday 10:00 AM - 10:30 AM",
            "How about Tuesday at 2pm?",
            "I have Thursday 3:00 PM available if that works for you.",
            "We could do tomorrow at 11am.",
            "Does 4 PM on Monday work for you?",
        ]:
            with self.subTest(response=response):
                self.assertTrue(states_specific_availability(response))

    def test_round_the_clock_sales_talk_is_not_an_offer_of_times(self):
        """
        This product's entire pitch is 24/7 coverage. Matching a bare
        clock time would replace correct, on-topic answers with a
        booking fallback nobody asked for.
        """
        for response in [
            "Your AI employee answers at 3am while your team is asleep.",
            "It works 24/7 without salaries or sick days.",
            "Most clients are live within 2 weeks.",
            "A human takes 20 hours a week on this.",
            "The demo is 30 minutes.",
            "We build AI employees that handle support around the clock.",
        ]:
            with self.subTest(response=response):
                self.assertFalse(states_specific_availability(response))


class TestDetectsFabricatedBookingClaims(unittest.TestCase):
    def test_the_verbatim_claim_from_the_real_incident(self):
        self.assertTrue(claims_a_booking_happened("Fantastic, your demo is set!"))

    def test_other_ways_of_claiming_a_booking_exists(self):
        for response in [
            "You're all set for Tuesday.",
            "You're booked!",
            "I've scheduled that for you.",
            "I've got you down for 2pm.",
            "That's confirmed.",
            "Your meeting is on the calendar.",
            "Your appointment has been booked.",
        ]:
            with self.subTest(response=response):
                self.assertTrue(claims_a_booking_happened(response))

    def test_offering_to_book_is_honest_and_must_not_match(self):
        """
        Offering is the correct behaviour when nothing is booked yet.
        Flagging it would replace the right answer with a fallback.
        """
        for response in [
            "Would you like me to get that booked?",
            "Shall I set up a demo for you?",
            "You can book a time that works here: https://calendly.com/example",
            "Want me to check what's free next week?",
            "Which of those times works best for you?",
        ]:
            with self.subTest(response=response):
                self.assertFalse(claims_a_booking_happened(response))


class TestGuardUsesThePlanAsTheAuthority(_IsolatedDatabasesMixin, unittest.TestCase):
    def setUp(self):
        self._isolate_databases()
        from core_ai.conversation_engine import ConversationEngine

        self.engine = ConversationEngine()
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = False
        self.lead = LeadProfile(name="Nadia", email="nadia@ridgeline.com")

    def _guard(self, response, plan, channel="chat"):
        return self.engine._guard_against_fabricated_scheduling(
            "conv-1", response, plan, channel, self.lead
        )

    def test_invented_times_are_replaced_when_the_plan_has_no_real_slots(self):
        result = self._guard("How about Tuesday at 2pm?", ConversationPlan())

        self.assertNotIn("Tuesday at 2pm", result)
        self.assertIn("calendar", result.lower())

    def test_real_times_pass_through_untouched(self):
        """
        The live, working path verified in production must be completely
        unaffected -- this guard exists to catch invention, not to
        suppress the real feature.
        """
        response = "Here are a few slots:\n\n1. Friday 9:00 AM - 9:30 AM"
        plan = ConversationPlan(available_slots=["Friday 9:00 AM - 9:30 AM"])

        self.assertEqual(self._guard(response, plan), response)

    def test_fabricated_booking_claim_is_replaced(self):
        result = self._guard("Fantastic, your demo is set!", ConversationPlan())

        self.assertNotIn("your demo is set", result)

    def test_a_real_confirmed_booking_passes_through_untouched(self):
        response = "You're all set for Friday at 9am, see you then!"
        plan = ConversationPlan(booking_confirmation="Friday 9:00 AM - 9:30 AM")

        self.assertEqual(self._guard(response, plan), response)

    def test_booking_claim_wins_when_a_response_does_both(self):
        """
        A fabricated confirmation is the more damaging of the two: a
        visitor who believes a demo is on the calendar simply will not
        turn up to one that does not exist.
        """
        result = self._guard(
            "You're all set for Tuesday at 2pm!", ConversationPlan()
        )

        self.assertNotIn("all set", result)

    def test_ordinary_answers_are_never_touched(self):
        response = "We build AI employees that handle support around the clock."
        self.assertEqual(self._guard(response, ConversationPlan()), response)

    def test_voice_fallback_never_contains_a_url(self):
        result = self._guard("Your demo is set for 2pm!", ConversationPlan(), channel="voice")

        self.assertNotIn("http", result.lower())
        self.assertNotIn("calendly.com", result.lower())


if __name__ == "__main__":
    unittest.main()
