import unittest

from core_ai.unbacked_action_detector import UnbackedActionCategory, UnbackedActionDetector


class TestUnbackedActionDetectorCategories(unittest.TestCase):
    """
    Each category should match the real incident wording (and close
    variants) that motivated it, and nothing else.
    """

    def setUp(self):
        self.detector = UnbackedActionDetector()

    def test_matches_the_exact_live_production_failure_wording(self):
        """
        The exact message that fabricated a claim in live production
        (see docs/Decision_Log.md and today's investigation) -- this is
        the one case that must never regress.
        """
        message = (
            "Can you email me a checklist of everything I need to "
            "prepare before we start?"
        )
        self.assertEqual(
            self.detector.detect(message),
            UnbackedActionCategory.OUT_OF_CHAT_MESSAGE,
        )

    def test_matches_the_pdf_variant_of_the_live_failure(self):
        message = (
            "Can you email me a PDF checklist of everything I need to "
            "prepare before we start?"
        )
        self.assertEqual(
            self.detector.detect(message),
            UnbackedActionCategory.OUT_OF_CHAT_MESSAGE,
        )

    def test_matches_text_me_requests(self):
        self.assertEqual(
            self.detector.detect("can you text me a summary of this?"),
            UnbackedActionCategory.OUT_OF_CHAT_MESSAGE,
        )

    def test_matches_whatsapp_requests(self):
        self.assertEqual(
            self.detector.detect("just whatsapp me the details"),
            UnbackedActionCategory.OUT_OF_CHAT_MESSAGE,
        )

    def test_matches_alternate_booking_mechanism_requests(self):
        for message in [
            "can you email me the available times",
            "can you email me a link to book",
            "text me a time that works",
            "send me a link to pick a slot",
        ]:
            with self.subTest(message=message):
                self.assertEqual(
                    self.detector.detect(message),
                    UnbackedActionCategory.ALTERNATE_BOOKING_MECHANISM,
                )

    def test_matches_human_handoff_requests(self):
        for message in [
            "can I talk to a real person",
            "I'd like to speak to a human",
            "connect me with someone on your team",
        ]:
            with self.subTest(message=message):
                self.assertEqual(
                    self.detector.detect(message),
                    UnbackedActionCategory.HUMAN_HANDOFF,
                )


class TestUnbackedActionDetectorFalsePositives(unittest.TestCase):
    """
    Directional phrasing matters: the visitor asking Bray to send
    something must match, but the visitor giving their own contact
    info, or asking a normal question that happens to contain a
    similar word, must not. A false positive here means a completely
    normal message gets a canned decline instead of a real answer, so
    this list is exercised as carefully as the true positives above.
    """

    def setUp(self):
        self.detector = UnbackedActionDetector()

    def test_visitor_giving_their_own_email_does_not_match(self):
        self.assertIsNone(
            self.detector.detect("my email is john@example.com")
        )

    def test_asking_for_brays_email_does_not_match(self):
        self.assertIsNone(
            self.detector.detect("what's your email address?")
        )

    def test_missed_calls_pain_point_does_not_match(self):
        self.assertIsNone(
            self.detector.detect(
                "we get a lot of missed calls, can we book a call?"
            )
        )

    def test_are_you_a_bot_does_not_match_human_handoff(self):
        self.assertIsNone(
            self.detector.detect("are you a real person or an AI?")
        )

    def test_ordinary_pricing_question_does_not_match(self):
        self.assertIsNone(self.detector.detect("just tell me the price"))

    def test_buying_signal_does_not_match(self):
        self.assertIsNone(
            self.detector.detect("I'm interested, how do we get started?")
        )

    def test_numeric_slot_reply_does_not_match(self):
        self.assertIsNone(self.detector.detect("2"))

    def test_gibberish_does_not_match(self):
        self.assertIsNone(
            self.detector.detect(
                "asdkfj q23p9 %%% ??? blorgotron zzzxcv nonsense input"
            )
        )

    def test_integration_question_does_not_match(self):
        self.assertIsNone(
            self.detector.detect("do you integrate with Salesforce?")
        )

    def test_empty_and_none_message_do_not_match(self):
        self.assertIsNone(self.detector.detect(""))
        self.assertIsNone(self.detector.detect(None))


if __name__ == "__main__":
    unittest.main()
