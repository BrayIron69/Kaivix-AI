import os
import tempfile
import unittest

import crm.database as database
from crm.lead import Lead
from crm.sqlite_crm import SQLiteCRM


class TestCRMBusinessScoping(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)

        self._original_db_name = database.DATABASE_NAME
        database.DATABASE_NAME = self.db_path

        self.crm = SQLiteCRM()

    def tearDown(self):
        database.DATABASE_NAME = self._original_db_name
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_same_email_different_businesses_both_succeed(self):
        email = "shared@example.com"

        lead_a = self.crm.save_lead(
            {"name": "Alice A", "email": email, "company": "Acme A"},
            business_id="business-a",
        )
        lead_b = self.crm.save_lead(
            {"name": "Alice B", "email": email, "company": "Acme B"},
            business_id="business-b",
        )

        self.assertIsNotNone(lead_a)
        self.assertIsNotNone(lead_b)

        found_a = self.crm.get_lead_by_email(email, business_id="business-a")
        found_b = self.crm.get_lead_by_email(email, business_id="business-b")

        self.assertEqual(found_a.company, "Acme A")
        self.assertEqual(found_b.company, "Acme B")
        self.assertEqual(found_a.business_id, "business-a")
        self.assertEqual(found_b.business_id, "business-b")

    def test_no_cross_business_lookup(self):
        email = "shared2@example.com"
        self.crm.save_lead({"name": "A", "email": email}, business_id="business-a")

        self.assertIsNone(
            self.crm.get_lead_by_email(email, business_id="business-b")
        )

    def test_get_all_leads_scoped_by_business(self):
        self.crm.save_lead(
            {"name": "A", "email": "a@example.com"}, business_id="business-a"
        )
        self.crm.save_lead(
            {"name": "B", "email": "b@example.com"}, business_id="business-b"
        )

        leads_a = self.crm.get_all_leads(business_id="business-a")
        self.assertEqual(len(leads_a), 1)
        self.assertEqual(leads_a[0].email, "a@example.com")

    def test_update_lead_scoped_by_business(self):
        email = "shared3@example.com"
        self.crm.save_lead({"name": "A", "email": email}, business_id="business-a")
        self.crm.save_lead({"name": "B", "email": email}, business_id="business-b")

        self.crm.update_lead(email, business_id="business-a", notes="updated-a")

        lead_a = self.crm.get_lead_by_email(email, business_id="business-a")
        lead_b = self.crm.get_lead_by_email(email, business_id="business-b")

        self.assertEqual(lead_a.notes, "updated-a")
        self.assertEqual(lead_b.notes, "")

    def test_default_business_id_applied_when_unspecified(self):
        saved = self.crm.save_lead({"name": "Default", "email": "d@example.com"})
        self.assertEqual(saved.business_id, "kaivix")

    def test_delete_lead_scoped_by_business(self):
        """
        delete_lead matched on email alone while every other method was
        business-scoped, so deleting one tenant's lead wiped the same
        email out of every other tenant too.
        """
        email = "shared4@example.com"
        self.crm.save_lead({"name": "A", "email": email}, business_id="business-a")
        self.crm.save_lead({"name": "B", "email": email}, business_id="business-b")

        self.crm.delete_lead(email, business_id="business-a")

        self.assertIsNone(
            self.crm.get_lead_by_email(email, business_id="business-a")
        )
        surviving = self.crm.get_lead_by_email(email, business_id="business-b")
        self.assertIsNotNone(surviving)
        self.assertEqual(surviving.name, "B")

    def test_delete_lead_from_another_business_is_a_no_op(self):
        email = "shared5@example.com"
        self.crm.save_lead({"name": "A", "email": email}, business_id="business-a")

        self.assertFalse(
            self.crm.delete_lead(email, business_id="business-b")
        )
        self.assertIsNotNone(
            self.crm.get_lead_by_email(email, business_id="business-a")
        )

    def test_delete_lead_defaults_to_the_default_business_id(self):
        email = "default-delete@example.com"
        self.crm.save_lead({"name": "Default", "email": email})

        self.assertTrue(self.crm.delete_lead(email))
        self.assertIsNone(self.crm.get_lead_by_email(email))


class TestLeadFromRowPositionalFallback(unittest.TestCase):
    """
    crm/lead.py's Lead.from_row has three code paths: dict-style (used
    for real sqlite3.Row results), a current-schema tuple fallback, and
    an older legacy tuple fallback. business_id was appended as the
    LAST column specifically so it wouldn't shift any existing
    positional index -- these tests pin that down.
    """

    def test_current_schema_with_business_id_18_columns(self):
        row = (
            1, "Alice", "alice@example.com", "555-1234", "Acme", "Acme",
            "Software", "10k", "Q1", "scaling", "yes", 80, "Hot",
            "Qualified", "notes here", "2026-01-01", "2026-01-01T00:00:00",
            "business-a",
        )
        lead = Lead.from_row(row)

        self.assertEqual(lead.id, 1)
        self.assertEqual(lead.name, "Alice")
        self.assertEqual(lead.email, "alice@example.com")
        self.assertEqual(lead.phone, "555-1234")
        self.assertEqual(lead.score, 80)
        self.assertEqual(lead.created_at, "2026-01-01T00:00:00")
        self.assertEqual(lead.business_id, "business-a")

    def test_pre_business_id_schema_17_columns(self):
        row = (
            1, "Alice", "alice@example.com", "555-1234", "Acme", "Acme",
            "Software", "10k", "Q1", "scaling", "yes", 80, "Hot",
            "Qualified", "notes here", "2026-01-01", "2026-01-01T00:00:00",
        )
        lead = Lead.from_row(row)

        self.assertEqual(lead.id, 1)
        self.assertEqual(lead.created_at, "2026-01-01T00:00:00")
        self.assertEqual(lead.business_id, "")

    def test_older_13_column_schema(self):
        row = (
            1, "Alice", "alice@example.com", "Acme", "10k", "Q1",
            "scaling", 80, "Hot", "Qualified", "notes", "2026-01-01",
            "2026-01-01T00:00:00",
        )
        lead = Lead.from_row(row)

        self.assertEqual(lead.id, 1)
        self.assertEqual(lead.company, "Acme")
        self.assertEqual(lead.business, "Acme")
        self.assertEqual(lead.created_at, "2026-01-01T00:00:00")
        self.assertEqual(lead.business_id, "")


if __name__ == "__main__":
    unittest.main()
