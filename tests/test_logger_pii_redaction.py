"""
Logger.log_lead must not write customer PII to logs/app.log in the clear.

It used to log name, email, business, budget, timeline and pain point
verbatim. logs/app.log is plaintext, not access-controlled, copied around with
the repo directory, and never rotated.

The rule these tests enforce: direct identifiers (name, email) are masked;
non-identifying qualification data (company, budget, timeline, pain point) is
kept so the log stays useful. The strongest test here is
TestNoRawPIIReachesTheLog, which asserts against the actual emitted line
rather than against the helpers.
"""

import logging
import unittest

from utils.logger import Logger, _initials, _mask_email, _truncate, lead_reference

FULL_LEAD = {
    "name": "Nadia Okonkwo",
    "email": "nadia.okonkwo@ridgeline-dental.com",
    "company": "Ridgeline Dental",
    "business": "Ridgeline Dental",
    "budget": "$2000/month",
    "timeline": "Ready now",
    "pain_point": "Answering customer inquiries",
    "business_id": "kaivix",
}


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class _LogCaptureMixin:
    """
    Capture what log_lead actually emits, without writing to logs/app.log.

    Logger attaches a FileHandler to a named logger the first time it is
    constructed, and reuses it afterwards; these tests add their own handler
    and drop it again rather than touching that setup.
    """

    def _capture(self):
        logger = Logger()
        handler = _CapturingHandler()
        logger.logger.addHandler(handler)
        self.addCleanup(logger.logger.removeHandler, handler)
        return logger, handler


class TestNoRawPIIReachesTheLog(_LogCaptureMixin, unittest.TestCase):
    def setUp(self):
        logger, self.handler = self._capture()
        logger.log_lead(FULL_LEAD)
        self.line = self.handler.lines[-1]

    def test_full_email_is_absent(self):
        self.assertNotIn("nadia.okonkwo@ridgeline-dental.com", self.line)

    def test_email_local_part_is_absent(self):
        self.assertNotIn("nadia.okonkwo", self.line)

    def test_full_name_is_absent(self):
        self.assertNotIn("Nadia Okonkwo", self.line)
        self.assertNotIn("Okonkwo", self.line)

    def test_masked_email_keeps_the_domain(self):
        self.assertIn("n***@ridgeline-dental.com", self.line)

    def test_name_is_reduced_to_initials(self):
        self.assertIn("Name=N.O.", self.line)

    def test_a_lead_reference_is_present(self):
        expected = lead_reference("kaivix", "nadia.okonkwo@ridgeline-dental.com")
        self.assertIn(f"ref={expected}", self.line)

    def test_the_event_is_still_identifiable_as_a_lead_capture(self):
        self.assertIn("Lead Captured", self.line)


class TestUsefulnessIsPreserved(_LogCaptureMixin, unittest.TestCase):
    """
    The point is to stop writing PII, not to gut the log. A line that says
    nothing is a failure of this change too.
    """

    def setUp(self):
        logger, self.handler = self._capture()
        logger.log_lead(FULL_LEAD)
        self.line = self.handler.lines[-1]

    def test_qualification_data_is_kept(self):
        self.assertIn("Budget=$2000/month", self.line)
        self.assertIn("Timeline=Ready now", self.line)
        self.assertIn("Pain Point=Answering customer inquiries", self.line)

    def test_company_is_kept(self):
        self.assertIn("Company=Ridgeline Dental", self.line)

    def test_company_falls_back_to_the_business_field(self):
        logger, handler = self._capture()
        lead = dict(FULL_LEAD)
        lead["company"] = ""
        logger.log_lead(lead)

        self.assertIn("Company=Ridgeline Dental", handler.lines[-1])


class TestReferenceIsStableAndScoped(unittest.TestCase):
    def test_same_lead_gives_the_same_reference(self):
        self.assertEqual(
            lead_reference("kaivix", "a@b.com"),
            lead_reference("kaivix", "a@b.com"),
        )

    def test_reference_is_case_and_whitespace_insensitive(self):
        self.assertEqual(
            lead_reference("kaivix", "  A@B.com  "),
            lead_reference("kaivix", "a@b.com"),
        )

    def test_same_email_in_two_businesses_gives_different_references(self):
        """
        The CRM allows one address in two businesses as two records
        (UNIQUE(business_id, email)); the reference must not collapse them.
        """
        self.assertNotEqual(
            lead_reference("kaivix", "a@b.com"),
            lead_reference("other-business", "a@b.com"),
        )

    def test_reference_does_not_contain_the_email(self):
        self.assertNotIn("a@b.com", lead_reference("kaivix", "a@b.com"))

    def test_reference_is_produced_even_with_no_email(self):
        self.assertTrue(lead_reference("kaivix", None))
        self.assertTrue(lead_reference("kaivix", ""))


class TestMaskEmail(unittest.TestCase):
    def test_typical_address(self):
        self.assertEqual(_mask_email("nadia@example.com"), "n***@example.com")

    def test_single_character_local_part(self):
        self.assertEqual(_mask_email("n@example.com"), "n***@example.com")

    def test_subdomain_is_kept_whole(self):
        self.assertEqual(_mask_email("a@mail.corp.example.com"), "a***@mail.corp.example.com")

    def test_multiple_at_signs_split_on_the_last(self):
        self.assertEqual(_mask_email('"odd@local"@example.com'), '"***@example.com')

    def test_blank_stays_blank(self):
        self.assertEqual(_mask_email(""), "")
        self.assertEqual(_mask_email(None), "")
        self.assertEqual(_mask_email("   "), "")

    def test_malformed_address_is_withheld_entirely(self):
        """No "@" at all, or an empty half -- withhold rather than guess which
        part is safe to show."""
        self.assertEqual(_mask_email("not-an-email"), "***")
        self.assertEqual(_mask_email("@example.com"), "***")
        self.assertEqual(_mask_email("nadia@"), "***")

    def test_no_original_local_part_survives_masking(self):
        self.assertNotIn("adia", _mask_email("nadia@example.com"))


class TestInitials(unittest.TestCase):
    def test_two_part_name(self):
        self.assertEqual(_initials("Nadia Okonkwo"), "N.O.")

    def test_single_name(self):
        self.assertEqual(_initials("nadia"), "N.")

    def test_three_part_name(self):
        self.assertEqual(_initials("Ada Grace Lovelace"), "A.G.L.")

    def test_extra_whitespace_is_ignored(self):
        self.assertEqual(_initials("  Nadia   Okonkwo  "), "N.O.")

    def test_blank_stays_blank(self):
        self.assertEqual(_initials(""), "")
        self.assertEqual(_initials(None), "")
        self.assertEqual(_initials("   "), "")


class TestTruncate(unittest.TestCase):
    def test_short_text_is_untouched(self):
        self.assertEqual(_truncate("Answering customer inquiries"), "Answering customer inquiries")

    def test_long_text_is_bounded_and_says_how_much_was_dropped(self):
        result = _truncate("x" * 200)
        self.assertLess(len(result), 200)
        self.assertIn("+140 chars", result)

    def test_none_becomes_blank(self):
        self.assertEqual(_truncate(None), "")

    def test_non_string_is_accepted(self):
        self.assertEqual(_truncate(5000), "5000")


class TestMissingFieldsDoNotCrash(_LogCaptureMixin, unittest.TestCase):
    """
    log_lead takes a plain dict. An incomplete one must log something rather
    than raise -- a logging call must never be the thing that breaks a
    request.
    """

    def test_empty_lead_logs_without_raising(self):
        logger, handler = self._capture()
        logger.log_lead({})

        line = handler.lines[-1]
        self.assertIn("Lead Captured", line)
        self.assertIn("Name= ", line)
        self.assertIn("Email= ", line)

    def test_none_values_log_without_raising(self):
        logger, handler = self._capture()
        logger.log_lead(
            {
                "name": None,
                "email": None,
                "company": None,
                "business": None,
                "budget": None,
                "timeline": None,
                "pain_point": None,
                "business_id": None,
            }
        )
        self.assertIn("Lead Captured", handler.lines[-1])


if __name__ == "__main__":
    unittest.main()
