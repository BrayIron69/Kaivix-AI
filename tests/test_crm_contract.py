"""
ONE scenario suite, run against EVERY CRM implementation.

This exists because of a bug found in this codebase earlier the same
day. EmailProvider deliberately MIRRORED GoogleCalendarProvider rather
than sharing code, with a docstring promising the two would stay in
step. They did not: the calendar provider received a critical
persistence fix, the email provider did not, and email stayed silently
broken in production. Nothing caught it, because nothing was checking
that the twins still agreed.

PostgresCRM mirrors SQLiteCRM the same way and for the same legitimate
reason (the SQL genuinely differs). So the promise is a test, not a
comment. Everything below runs against both.

The Postgres cases SKIP unless DATABASE_URL is set, so the suite stays
runnable with no database. They are not decorative: they are how the
real Render instance gets verified, and skipping loudly is honest about
what did and did not run.
"""

import os
import tempfile
import unittest

import crm.database as crm_database
from crm.sqlite_crm import SQLiteCRM
from database import postgres

BUSINESS_A = "contract-biz-a"
BUSINESS_B = "contract-biz-b"


class _CRMContractCases:
    """
    The behaviour every BaseCRM implementation must have. Subclasses
    provide `self.crm` and a clean slate; nothing here knows which
    backend it is talking to.
    """

    def test_save_then_read_back(self):
        self.crm.save_lead({"name": "Nadia", "email": "n@example.com"}, BUSINESS_A)

        lead = self.crm.get_lead_by_email("n@example.com", BUSINESS_A)

        self.assertIsNotNone(lead)
        self.assertEqual(lead.email, "n@example.com")
        self.assertEqual(lead.name, "Nadia")

    def test_unknown_email_is_none(self):
        self.assertIsNone(self.crm.get_lead_by_email("nobody@example.com", BUSINESS_A))

    def test_saving_the_same_email_twice_upserts_rather_than_duplicating(self):
        self.crm.save_lead({"name": "Nadia", "email": "n@example.com"}, BUSINESS_A)
        self.crm.save_lead(
            {"name": "Nadia", "email": "n@example.com", "company": "Ridgeline"},
            BUSINESS_A,
        )

        all_leads = self.crm.get_all_leads(BUSINESS_A)
        self.assertEqual(len(all_leads), 1)
        self.assertEqual(all_leads[0].company, "Ridgeline")

    def test_a_later_save_never_blanks_a_field_it_omits(self):
        """
        The merge rule every implementation shares: empty values do not
        overwrite real ones. A visitor who gives a budget and then says
        something unrelated must not lose the budget.
        """
        self.crm.save_lead(
            {"name": "Nadia", "email": "n@example.com", "budget": "$20,000"},
            BUSINESS_A,
        )
        self.crm.save_lead({"name": "Nadia", "email": "n@example.com"}, BUSINESS_A)

        self.assertEqual(
            self.crm.get_lead_by_email("n@example.com", BUSINESS_A).budget, "$20,000"
        )

    def test_the_same_email_in_two_businesses_stays_two_records(self):
        self.crm.save_lead({"name": "A", "email": "shared@example.com"}, BUSINESS_A)
        self.crm.save_lead({"name": "B", "email": "shared@example.com"}, BUSINESS_B)

        self.assertEqual(
            self.crm.get_lead_by_email("shared@example.com", BUSINESS_A).name, "A"
        )
        self.assertEqual(
            self.crm.get_lead_by_email("shared@example.com", BUSINESS_B).name, "B"
        )

    def test_one_business_never_reads_anothers_leads(self):
        self.crm.save_lead({"name": "A", "email": "a@example.com"}, BUSINESS_A)

        self.assertEqual(self.crm.get_all_leads(BUSINESS_B), [])
        self.assertIsNone(self.crm.get_lead_by_email("a@example.com", BUSINESS_B))

    def test_update_applies_and_reports_whether_it_matched(self):
        self.crm.save_lead({"name": "Nadia", "email": "n@example.com"}, BUSINESS_A)

        self.assertTrue(
            self.crm.update_lead("n@example.com", BUSINESS_A, timeline="next quarter")
        )
        self.assertEqual(
            self.crm.get_lead_by_email("n@example.com", BUSINESS_A).timeline,
            "next quarter",
        )
        self.assertFalse(
            self.crm.update_lead("ghost@example.com", BUSINESS_A, timeline="never")
        )

    def test_update_ignores_fields_outside_the_allowlist(self):
        self.crm.save_lead({"name": "Nadia", "email": "n@example.com"}, BUSINESS_A)

        self.assertFalse(
            self.crm.update_lead("n@example.com", BUSINESS_A, id=999, nonsense="x")
        )

    def test_delete_removes_only_that_businesss_lead(self):
        self.crm.save_lead({"name": "A", "email": "shared@example.com"}, BUSINESS_A)
        self.crm.save_lead({"name": "B", "email": "shared@example.com"}, BUSINESS_B)

        self.assertTrue(self.crm.delete_lead("shared@example.com", BUSINESS_A))

        self.assertIsNone(self.crm.get_lead_by_email("shared@example.com", BUSINESS_A))
        self.assertIsNotNone(self.crm.get_lead_by_email("shared@example.com", BUSINESS_B))

    def test_deleting_something_absent_reports_false(self):
        self.assertFalse(self.crm.delete_lead("ghost@example.com", BUSINESS_A))

    def test_email_is_required(self):
        with self.assertRaises(ValueError):
            self.crm.save_lead({"name": "No Email"}, BUSINESS_A)

    def test_company_is_mirrored_to_business(self):
        self.crm.save_lead(
            {"name": "Nadia", "email": "n@example.com", "company": "Ridgeline"},
            BUSINESS_A,
        )

        lead = self.crm.get_lead_by_email("n@example.com", BUSINESS_A)
        self.assertEqual(lead.business, "Ridgeline")


class TestSQLiteCRMContract(_CRMContractCases, unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(path)

        original = crm_database.DATABASE_NAME
        crm_database.DATABASE_NAME = path

        def _restore():
            crm_database.DATABASE_NAME = original
            if os.path.exists(path):
                os.remove(path)

        self.addCleanup(_restore)
        self.crm = SQLiteCRM()


@unittest.skipUnless(
    postgres.is_configured(),
    "DATABASE_URL is not set -- Postgres contract cases skipped. They are how "
    "the real instance gets verified, so a green run without them proves only "
    "half of this contract.",
)
class TestPostgresCRMContract(_CRMContractCases, unittest.TestCase):
    def setUp(self):
        from crm.postgres_crm import PostgresCRM

        self.crm = PostgresCRM()
        self._wipe()
        self.addCleanup(self._wipe)

    def _wipe(self):
        """
        Remove only this test's own business ids. Deliberately never
        TRUNCATEs: this may be pointed at the real Render instance, and
        a test suite that can wipe production leads is a worse problem
        than the one it was written to prevent.
        """
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM leads WHERE business_id IN (%s, %s)",
                    (BUSINESS_A, BUSINESS_B),
                )
        conn.close()


if __name__ == "__main__":
    unittest.main()
