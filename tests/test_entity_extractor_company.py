"""
Company extraction must not swallow a whole sentence.

Regression coverage for a bug seen in a real live conversation: a
visitor answering "we run a dental clinic and need help with missed
calls" had that entire phrase stored as their company name, which then
appeared in the CRM and on the admin dashboard.

This is the same over-capture already fixed for NAME_PATTERNS (see
tests/test_entity_extractor_name.py), in the other place it occurs:
COMPANY_PATTERNS capture everything up to sentence punctuation
([^.,!?]+), so any trailing clause came along with the company.

The boundary is deliberately NOT capitalization here -- unlike a name,
"dental clinic" is a perfectly good lowercase answer -- it is the start
of the next clause. See EntityExtractor._COMPANY_STOP_PATTERN.
"""

import unittest

from core_ai.entity_extractor import EntityExtractor

# Verbatim from the live conversation that exposed this.
REAL_INCIDENT_MESSAGE = "we run a dental clinic and need help with missed calls"
REAL_INCIDENT_BAD_VALUE = "dental clinic and need help with missed calls"


class TestCompanyExtractionStopsAtClauseBoundaries(unittest.TestCase):
    def setUp(self):
        self.extractor = EntityExtractor()

    def _company_for(self, message: str):
        return self.extractor.extract(message).company

    def test_the_exact_message_from_the_real_incident(self):
        company = self._company_for(REAL_INCIDENT_MESSAGE)

        self.assertNotEqual(
            company, REAL_INCIDENT_BAD_VALUE,
            "The full sentence was stored as the company name again -- this "
            "is the exact value that reached the CRM and admin dashboard.",
        )
        self.assertEqual(company, "dental clinic")

    def test_business_mirrors_company_after_the_cut(self):
        """
        company and business are kept in sync by the extractor; the
        truncated value has to land in both, not just one.
        """
        state = self.extractor.extract(REAL_INCIDENT_MESSAGE)

        self.assertEqual(state.company, "dental clinic")
        self.assertEqual(state.business, "dental clinic")

    def test_plausible_full_sentence_answers_are_cut_at_the_clause(self):
        cases = [
            (REAL_INCIDENT_MESSAGE, "dental clinic"),
            ("I own a small law firm and we're growing fast", "small law firm"),
            ("we run a gym but we're struggling with bookings", "gym"),
            ("I run a bakery so I need something simple", "bakery"),
            ("we own a clinic that handles 200 patients a week", "clinic"),
            ("my company is Acme Corp and we have 20 staff", "Acme Corp"),
            ("we run a clinic because our front desk is overwhelmed", "clinic"),
            ("we run a salon and I want to automate booking", "salon"),
            ("I own a garage which is open seven days a week", "garage"),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(self._company_for(message), expected)

    def test_no_extracted_company_is_ever_sentence_shaped(self):
        """
        The property that actually matters, stated directly: whatever is
        extracted must not look like prose.
        """
        messages = [
            REAL_INCIDENT_MESSAGE,
            "I own a small law firm and we're growing fast",
            "we run a gym but we're struggling with bookings",
            "we run a clinic in downtown Boston serving 200 patients weekly",
            "I run a bakery so I need something simple and cheap to run",
        ]
        widest_cap = max(EntityExtractor._COMPANY_MAX_WORDS.values())

        for message in messages:
            with self.subTest(message=message):
                company = self._company_for(message)
                self.assertLessEqual(
                    len(company.split()),
                    widest_cap,
                    f"Sentence-shaped company extracted: {company!r}",
                )
                for verb_phrase in (" and need", " and want", " but we", " so i"):
                    self.assertNotIn(verb_phrase, company.lower())


class TestRealCompanyNamesStillExtract(unittest.TestCase):
    """
    The fix must not over-correct. A bare "and" inside a real company
    name must not cut it -- that is why coordinators only cut when a new
    clause plainly follows.
    """

    def setUp(self):
        self.extractor = EntityExtractor()

    def _company_for(self, message: str):
        return self.extractor.extract(message).company

    def test_company_names_containing_and_are_preserved(self):
        cases = [
            ("we run Smith and Sons Plumbing", "Smith and Sons Plumbing"),
            ("my company is Barnes and Noble", "Barnes and Noble"),
            ("I own Baker and Associates", "Baker and Associates"),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(self._company_for(message), expected)

    def test_a_stated_name_is_not_cut_on_descriptive_words(self):
        """
        The descriptive-continuation boundary applies to business-TYPE
        captures only. A visitor stating a proper name that happens to
        contain one of those words must keep it.
        """
        cases = [
            ("my company is Made in Chelsea", "Made in Chelsea"),
            (
                "my company is The Law Offices of Smith and Associates LLP",
                "The Law Offices of Smith and Associates LLP",
            ),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(self._company_for(message), expected)

    def test_ordinary_answers_still_extract(self):
        cases = [
            ("my company is Acme Co", "Acme Co"),
            ("I own a bakery", "bakery"),
            ("we run a dental clinic", "dental clinic"),
            ("I work at Google", "Google"),
            ("my business is Kaivix Labs", "Kaivix Labs"),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(self._company_for(message), expected)

    def test_run_ons_with_no_conjunction_stop_at_the_description(self):
        """
        Closes a gap this file previously documented as open: a run-on
        with no conjunction ("a clinic in downtown Boston serving 200
        patients weekly") is 8 words and slipped under the single shared
        word cap of 8.

        Business-type captures now also stop at a descriptive
        continuation, which is better than the rejection a tighter cap
        alone would have produced -- the useful part ("clinic") is kept
        rather than the whole value discarded.
        """
        cases = [
            ("we run a clinic in downtown Boston serving 200 patients weekly", "clinic"),
            (
                "we run a clinic in downtown Boston serving over 200 patients every week",
                "clinic",
            ),
            ("I own a bakery based in Leeds", "bakery"),
            ("we run a gym near the station", "gym"),
            ("we own a garage located on the high street", "garage"),
        ]
        for message, expected in cases:
            with self.subTest(message=message):
                self.assertEqual(self._company_for(message), expected)


if __name__ == "__main__":
    unittest.main()
