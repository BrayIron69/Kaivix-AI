"""
Budget extraction must handle a spelled-out magnitude word (thousand,
million, billion), not just a literal `$` figure or a digit run next to
a currency word.

Regression coverage for a bug seen in a real live voice call: a visitor
answered the budget question with "How about one. Billion dollars?"
(the period is a real transcription artifact from Vapi's speech-to-text,
not something the visitor typed), and then, asked again, "I told you 1
billion dollars." BUDGET_PATTERN matched neither -- it requires either a
literal `$` or a digit run directly adjacent to a currency word, and
"billion" is neither a currency word nor a digit -- so budget stayed in
QualificationEngine's missing-fields list for the rest of the call and
the assistant kept asking for it.

See EntityExtractor.BUDGET_MAGNITUDE_PATTERN and its docstring for the
fix and why the currency word is optional there.
"""

import unittest

from core_ai.entity_extractor import EntityExtractor

# Verbatim from the real call that exposed this (see
# core_ai/conversation_engine.py's _guard_against_garbled_email_confirmation
# docstring for the same call's other bug).
REAL_INCIDENT_FIRST_ATTEMPT = "How about one. Billion dollars?"
REAL_INCIDENT_SECOND_ATTEMPT = "I told you 1 billion dollars."


class TestBudgetExtractionHandlesSpelledOutMagnitudeWords(unittest.TestCase):
    def setUp(self):
        self.extractor = EntityExtractor()

    def _budget_for(self, message: str):
        return self.extractor.extract(message).budget

    def test_the_exact_first_attempt_from_the_real_incident(self):
        """
        The stray period ("one. Billion") is what a plain \\s+ join
        between the number word and the magnitude word would refuse to
        bridge -- this is the case that actually failed to extract.
        """
        budget = self._budget_for(REAL_INCIDENT_FIRST_ATTEMPT)

        self.assertNotEqual(budget, "", "budget was never extracted at all")
        self.assertIn("billion", budget.lower())

    def test_the_exact_second_attempt_from_the_real_incident(self):
        """
        Contains a real digit ("1"), but BUDGET_PATTERN still refuses it
        -- "billion" sits between the digit and "dollars", breaking the
        digit-adjacent-to-currency-word requirement.
        """
        budget = self._budget_for(REAL_INCIDENT_SECOND_ATTEMPT)

        self.assertEqual(budget, "1 billion dollars")

    def test_stray_transcription_punctuation_is_not_stored_verbatim(self):
        """
        The extracted value should read as a real budget answer, not
        carry the mid-phrase period into LeadProfile/the CRM.
        """
        budget = self._budget_for(REAL_INCIDENT_FIRST_ATTEMPT)

        self.assertNotIn(".", budget)


class TestBudgetMagnitudeWordsWithDigitsOrSpelledOutNumbers(unittest.TestCase):
    """Coverage beyond the exact incident: digits and spelled-out
    numbers, on either side of a magnitude word, with and without a
    trailing currency word."""

    def setUp(self):
        self.extractor = EntityExtractor()

    def _budget_for(self, message: str):
        return self.extractor.extract(message).budget

    def test_spelled_out_number_and_magnitude_with_dollars(self):
        self.assertEqual(
            self._budget_for("Our budget is one billion dollars."),
            "one billion dollars",
        )

    def test_digit_and_magnitude_with_dollars(self):
        self.assertEqual(
            self._budget_for("We can do 1 billion dollars."),
            "1 billion dollars",
        )

    def test_bare_digit_and_magnitude_with_no_currency_word(self):
        """
        A real spoken answer that never says "dollars" out loud is
        common -- the currency word is deliberately optional here,
        unlike BUDGET_PATTERN's digit-only branch.
        """
        self.assertEqual(self._budget_for("Maybe 50 thousand."), "50 thousand")

    def test_compound_spelled_out_number_before_magnitude(self):
        self.assertEqual(
            self._budget_for("a hundred thousand dollars sounds right"),
            "a hundred thousand dollars",
        )

    def test_realistic_voice_answer_with_filler_words_around_it(self):
        """
        A real spoken answer is rarely just the number -- there's
        usually a filler word or a trailing clause around it. The
        extractor only needs to find the budget phrase somewhere in the
        message, not have the whole message be exactly that phrase.
        """
        self.assertEqual(
            self._budget_for("around ten thousand dollars a month I think"),
            "ten thousand dollars",
        )

    def test_another_realistic_voice_answer(self):
        self.assertEqual(
            self._budget_for("maybe five thousand or so"),
            "five thousand",
        )

    def test_compound_hundred_thousand_with_currency(self):
        self.assertEqual(
            self._budget_for("we're thinking five hundred thousand dollars"),
            "five hundred thousand dollars",
        )


class TestBudgetMagnitudeFixDoesNotAffectExistingBehavior(unittest.TestCase):
    """The pre-existing digit/dollar-sign extraction (BUDGET_PATTERN)
    must be completely unaffected by this addition -- these are the
    same assertions that would have passed before this change."""

    def setUp(self):
        self.extractor = EntityExtractor()

    def _budget_for(self, message: str):
        return self.extractor.extract(message).budget

    def test_dollar_sign_with_comma_separated_thousands(self):
        self.assertEqual(self._budget_for("Our budget is $5,000."), "$5,000")

    def test_digit_with_usd_suffix(self):
        self.assertEqual(self._budget_for("5000 usd works for us"), "5000 usd")

    def test_dollar_figure_per_month(self):
        self.assertEqual(
            self._budget_for("$500 / month is what we have"), "$500 / month"
        )

    def test_no_budget_mentioned_extracts_nothing(self):
        self.assertEqual(self._budget_for("We're based in Boston."), "")


if __name__ == "__main__":
    unittest.main()
