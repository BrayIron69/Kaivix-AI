import unittest

from core_ai.entity_extractor import EntityExtractor


class TestNameExtractionDoesNotSwallowVerbPhrases(unittest.TestCase):
    """
    Regression coverage for a bug found by real end-to-end email
    verification, not by any prior test (there was no EntityExtractor
    test file at all before this one).

    NAME_PATTERNS' "i'm ..." / "i am ..." entries capture up to three
    following words, which is right for "I'm Alice Smith" but was also
    matching ordinary sentence openers: "Hi, I'm interested in learning
    about your AI automation services" produced
    lead.name == "Interested In Learning". That fabricated name then
    reached a real visitor, addressed in a real email as
    "Hi Interested In Learning,".

    The fix keeps matching case-insensitive (so the lead-in phrase still
    matches however it was typed) but requires the *captured* text to
    actually start uppercase in the original message -- a real typed name
    is capitalized, an ordinary verb phrase is not.
    """

    def setUp(self):
        self.extractor = EntityExtractor()

    def _name_for(self, message: str):
        return self.extractor.extract(message).name

    def test_the_exact_message_that_caused_the_real_incident(self):
        message = "Hi, I'm interested in learning about your AI automation services."
        self.assertFalse(
            self._name_for(message),
            "The verb phrase after \"I'm\" was extracted as a name -- this is "
            "the exact fabrication that reached a real inbox.",
        )

    def test_common_lowercase_openers_are_not_read_as_names(self):
        openers = [
            "I'm looking for a way to automate support",
            "I am hoping to book a demo",
            "i'm just browsing for now",
            "I'm trying to understand your pricing",
            "I am currently evaluating a few vendors",
            "I'm not sure this is a fit yet",
            "this is really helpful, thanks",
        ]
        for message in openers:
            with self.subTest(message=message):
                self.assertFalse(
                    self._name_for(message),
                    f"Extracted a name from a verb phrase: {message!r}",
                )

    def test_real_names_are_still_extracted(self):
        cases = [
            ("Hi, I'm Alice and my email is alice@example.com.", "Alice"),
            ("I'm Bee Person, email bp@example.com", "Bee Person"),
            ("Hi, I'm Kaivixname and my email is x@example.com.", "Kaivixname"),
            ("I am Dana from WidgetCo", "Dana"),
            ("My name is Tom", "Tom"),
            ("This is Nadia calling about the demo", "Nadia"),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(self._name_for(message), expected)

    def test_lowercase_lead_in_phrase_still_matches_a_capitalized_name(self):
        """
        Only the captured name must be capitalized -- the "i'm" lead-in
        itself may be typed any way, which is why re.IGNORECASE stays.
        """
        self.assertEqual(self._name_for("hey, i'm Alice"), "Alice")
        self.assertEqual(self._name_for("my name is Tom"), "Tom")


if __name__ == "__main__":
    unittest.main()
