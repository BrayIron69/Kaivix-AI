import unittest
from types import SimpleNamespace

from core_ai.action_claim_gate import find_unbacked_action_claim


def _plan(booking_confirmation="", booking_failed=False):
    return SimpleNamespace(booking_confirmation=booking_confirmation, booking_failed=booking_failed)


class TestFindUnbackedActionClaim(unittest.TestCase):
    """
    Deterministic gate: no LLM involved. Proves find_unbacked_action_claim
    catches the three action categories this codebase has no mechanism
    for (email, alternate booking mechanism, human handoff), leaves
    ordinary responses alone, and correctly exempts a *real* booking
    confirmation/failure -- the one case where booking-status language
    is actually backed by something (a real GoogleCalendarProvider call,
    see ConversationEngine._maybe_resolve_booking).
    """

    def test_clean_response_is_not_flagged(self):
        response = "We build custom AI agents for support and lead qualification. What are you looking to automate?"
        self.assertIsNone(find_unbacked_action_claim(response, _plan()))

    def test_email_claim_is_caught(self):
        cases = [
            "I've sent you an email with the checklist!",
            "I have sent that over to your inbox.",
            "Just sent you an email with the details.",
            "Go ahead and check your inbox for the checklist.",
            "It should be in your inbox shortly.",
        ]
        for response in cases:
            with self.subTest(response=response):
                self.assertEqual(find_unbacked_action_claim(response, _plan()), "email")

    def test_alternate_booking_mechanism_claim_is_caught_when_not_backed(self):
        cases = [
            "You're all booked for Tuesday at 2pm!",
            "Booking confirmed, see you then.",
            "I've added you to our calendar for next week.",
        ]
        for response in cases:
            with self.subTest(response=response):
                self.assertEqual(
                    find_unbacked_action_claim(response, _plan()),
                    "alternate_booking_mechanism",
                )

    def test_alternate_booking_mechanism_claim_is_exempt_when_backed_by_real_confirmation(self):
        response = "Booking confirmed for Wednesday 10:00 AM - 11:00 AM -- you'll get a calendar invite shortly."
        plan = _plan(booking_confirmation="Wednesday 10:00 AM - 11:00 AM")
        self.assertIsNone(find_unbacked_action_claim(response, plan))

    def test_alternate_booking_mechanism_claim_is_exempt_when_backed_by_real_failure(self):
        response = "Booking confirmed didn't go through on our end, here's a fallback link instead."
        plan = _plan(booking_failed=True)
        self.assertIsNone(find_unbacked_action_claim(response, plan))

    def test_human_handoff_claim_is_caught(self):
        cases = [
            "I've forwarded this to our team.",
            "I have escalated this to a specialist.",
            "Someone will reach out to you shortly.",
            "Our team will contact you soon.",
            "I'll have someone contact you about this.",
        ]
        for response in cases:
            with self.subTest(response=response):
                self.assertEqual(find_unbacked_action_claim(response, _plan()), "human_handoff")

    def test_human_handoff_claim_is_caught_even_with_a_real_booking_this_turn(self):
        # Booking being backed only exempts booking-status language --
        # it says nothing about whether a human was actually notified.
        response = "Booking confirmed for Tuesday! I've also notified our team so they're ready for you."
        plan = _plan(booking_confirmation="Tuesday 2:00 PM - 3:00 PM")
        self.assertEqual(find_unbacked_action_claim(response, plan), "human_handoff")

    def test_empty_response_is_not_flagged(self):
        self.assertIsNone(find_unbacked_action_claim("", _plan()))

    def test_no_plan_argument_defaults_to_treating_booking_as_unbacked(self):
        self.assertEqual(
            find_unbacked_action_claim("Booking confirmed, see you then!"),
            "alternate_booking_mechanism",
        )


if __name__ == "__main__":
    unittest.main()
