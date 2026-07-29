"""
Tests for IntentDetector's keyword matching (core_ai/intent_detector.py).

Regression driver: "too many missed calls" was classified as
MEETING_REQUEST because "call" substring-matched inside "calls", which
pushed ConversationEngine into the CLOSING stage and had Bray offer
booking slots before qualification was complete.
"""

import unittest

from core_ai.intent_detector import IntentDetector
from core_ai.intents import Intent


class TestMissedCallsRegression(unittest.TestCase):
    """The exact reported phrase, plus the shapes it shows up in."""

    def setUp(self):
        self.detector = IntentDetector()

    def test_too_many_missed_calls_is_not_a_meeting_request(self):
        self.assertNotEqual(
            self.detector.detect("too many missed calls"),
            Intent.MEETING_REQUEST,
        )

    def test_missed_calls_in_a_full_sentence_is_not_a_meeting_request(self):
        for message in [
            "We get too many missed calls",
            "Our biggest problem is too many missed calls after hours",
            "we're losing business because of too many missed calls",
            "too many missed calls and no one to answer them",
        ]:
            with self.subTest(message=message):
                self.assertNotEqual(
                    self.detector.detect(message),
                    Intent.MEETING_REQUEST,
                )

    def test_other_call_volume_phrasings_are_not_meeting_requests(self):
        for message in [
            "we miss a lot of calls",
            "our call center is overwhelmed",
            "the call volume is unmanageable",
            "we do a lot of cold calling",
            "nobody returns customer calls",
            "a missed call costs us a customer",
        ]:
            with self.subTest(message=message):
                self.assertNotEqual(
                    self.detector.detect(message),
                    Intent.MEETING_REQUEST,
                )

    def test_pain_point_phrasing_is_not_prematurely_classified_as_closing(self):
        """
        The downstream symptom: MEETING_REQUEST is in
        ConversationEngine._CLOSING_INTENTS, so a misread pain point
        jumped straight to booking. Any non-closing intent is fine here.
        """
        intent = self.detector.detect("too many missed calls")

        self.assertNotIn(
            intent.value,
            {"meeting_request", "buying_signal"},
        )


class TestLegitimateMeetingRequests(unittest.TestCase):
    """The fix must not cost us real booking requests."""

    def setUp(self):
        self.detector = IntentDetector()

    def test_singular_call_requests_still_match(self):
        for message in [
            "can we schedule a call?",
            "I'd like to book a call",
            "let's hop on a call",
            "could you give me a call tomorrow",
            "happy to jump on a call this week",
        ]:
            with self.subTest(message=message):
                self.assertEqual(
                    self.detector.detect(message),
                    Intent.MEETING_REQUEST,
                )

    def test_non_call_meeting_phrasings_still_match(self):
        for message in [
            "can we set up a meeting",
            "I want to book a demo",
            "send me your calendly",
            "can I get an appointment",
            "when can we talk",
            "I'd like a consultation",
            "interested in booking something next week",
            "are you free for scheduling a demo",
        ]:
            with self.subTest(message=message):
                self.assertEqual(
                    self.detector.detect(message),
                    Intent.MEETING_REQUEST,
                )

    def test_pain_point_and_real_request_together_still_books(self):
        """
        Scrubbing false positives must not swallow a genuine request that
        appears in the same message.
        """
        for message in [
            "we get too many missed calls -- can we book a call to discuss?",
            "our call center is drowning, can we schedule a demo",
        ]:
            with self.subTest(message=message):
                self.assertEqual(
                    self.detector.detect(message),
                    Intent.MEETING_REQUEST,
                )


class TestWholeWordMatching(unittest.TestCase):
    """Keywords must not match when buried inside a longer word."""

    def setUp(self):
        self.detector = IntentDetector()

    def test_keyword_inside_a_longer_word_does_not_match(self):
        for message, forbidden in [
            ("please recall what I said earlier", Intent.MEETING_REQUEST),
            ("the bookkeeping is a mess", Intent.MEETING_REQUEST),
            ("he is very talkative", Intent.MEETING_REQUEST),
            ("this is a bottleneck", Intent.MEETING_REQUEST),
        ]:
            with self.subTest(message=message):
                self.assertNotEqual(self.detector.detect(message), forbidden)


class TestOtherIntentsUnaffected(unittest.TestCase):
    """Every other category still classifies as it did before."""

    def setUp(self):
        self.detector = IntentDetector()

    def test_objection(self):
        self.assertEqual(
            self.detector.detect("that's too expensive for us"),
            Intent.OBJECTION,
        )

    def test_buying_signal(self):
        self.assertEqual(
            self.detector.detect("sounds good, let's do it"),
            Intent.BUYING_SIGNAL,
        )

    def test_pricing(self):
        for message in ["how much does it cost?", "what are your rates"]:
            with self.subTest(message=message):
                self.assertEqual(self.detector.detect(message), Intent.PRICING)

    def test_support(self):
        self.assertEqual(
            self.detector.detect("the widget is broken"),
            Intent.SUPPORT,
        )

    def test_goodbye(self):
        self.assertEqual(self.detector.detect("bye"), Intent.GOODBYE)

    def test_greeting(self):
        for message in ["hi", "hey there", "hello!"]:
            with self.subTest(message=message):
                self.assertEqual(self.detector.detect(message), Intent.GREETING)

    def test_multi_word_greeting_now_matches(self):
        """
        Previously dead: the greeting check compared single split words
        against a set containing two-word phrases, so "good morning"
        could never match.
        """
        self.assertEqual(
            self.detector.detect("good morning"),
            Intent.GREETING,
        )

    def test_information(self):
        self.assertEqual(
            self.detector.detect("tell me about your features"),
            Intent.INFORMATION,
        )

    def test_unknown(self):
        self.assertEqual(
            self.detector.detect("purple elephant umbrella"),
            Intent.UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main()
