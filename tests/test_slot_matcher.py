import unittest

from scheduling.slot_matcher import match_offered_slot

SLOTS = [
    "Tuesday 2:00 PM - 3:00 PM",
    "Wednesday 10:00 AM - 11:00 AM",
    "Thursday 1:00 PM - 2:00 PM",
]


class TestMatchOfferedSlot(unittest.TestCase):
    def test_exact_digit_match(self):
        self.assertEqual(match_offered_slot("2", SLOTS), 1)
        self.assertEqual(match_offered_slot("1", SLOTS), 0)
        self.assertEqual(match_offered_slot("3", SLOTS), 2)

    def test_digit_embedded_in_sentence(self):
        self.assertEqual(match_offered_slot("I'll take option 2 please", SLOTS), 1)
        self.assertEqual(match_offered_slot("Let's do #3", SLOTS), 2)

    def test_ordinal_word_match_case_insensitive(self):
        self.assertEqual(match_offered_slot("the first one works", SLOTS), 0)
        self.assertEqual(match_offered_slot("SECOND", SLOTS), 1)
        self.assertEqual(match_offered_slot("Third please", SLOTS), 2)

    def test_out_of_range_digit_returns_none(self):
        self.assertIsNone(match_offered_slot("4", SLOTS))
        self.assertIsNone(match_offered_slot("0", SLOTS))

    def test_ordinal_beyond_offered_count_returns_none(self):
        two_slots = SLOTS[:2]
        self.assertIsNone(match_offered_slot("third", two_slots))

    def test_no_offered_slots_returns_none(self):
        self.assertIsNone(match_offered_slot("1", []))
        self.assertIsNone(match_offered_slot("first", []))

    def test_ambiguous_or_unrelated_text_returns_none(self):
        self.assertIsNone(match_offered_slot("I like Tuesdays in general", SLOTS))
        self.assertIsNone(match_offered_slot("what's your pricing?", SLOTS))
        self.assertIsNone(match_offered_slot("", SLOTS))
        self.assertIsNone(match_offered_slot("maybe later", SLOTS))

    def test_multi_digit_number_does_not_falsely_match(self):
        # "10" must not be misread as digit "1".
        self.assertIsNone(match_offered_slot("10", SLOTS))
        self.assertIsNone(match_offered_slot("call me at 10am", SLOTS))

    def test_does_not_fuzzy_match_slot_text_itself(self):
        # Mentioning the slot's own weekday/time text is NOT a valid
        # match path -- only digits/ordinals are.
        self.assertIsNone(match_offered_slot("Tuesday works for me", SLOTS))
        self.assertIsNone(match_offered_slot("2:00 PM is good", SLOTS))


if __name__ == "__main__":
    unittest.main()
