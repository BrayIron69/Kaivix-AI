import os
import tempfile
import unittest

from core_ai.lead_profile import LeadProfile
from memory.long_term_memory import LongTermMemory, SQLiteLongTermMemoryStore


class TestLongTermMemoryBusinessScoping(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self.store = SQLiteLongTermMemoryStore(db_path=self.db_path)
        self.memory = LongTermMemory(store=self.store)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_no_cross_business_leak_on_shared_email(self):
        email = "shared@example.com"

        lead = LeadProfile(name="Alice A", email=email, company="Acme A")
        self.memory.remember(lead, business_id="business-a")

        leaked = self.memory.recall(email, business_id="business-b")
        self.assertIsNone(leaked)

        profile = self.memory.recall(email, business_id="business-a")
        self.assertIsNotNone(profile)
        self.assertEqual(profile["email"], email)
        self.assertEqual(profile["name"], "Alice A")
        self.assertEqual(profile["company"], "Acme A")

    def test_business_id_column_is_populated(self):
        lead = LeadProfile(name="Bob", email="bob@example.com", company="Acme")
        self.memory.remember(lead, business_id="business-a")

        conn = self.store._get_connection()
        row = conn.execute(
            "SELECT business_id FROM long_term_memory WHERE key = ?",
            ("business-a::bob@example.com",),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["business_id"], "business-a")


if __name__ == "__main__":
    unittest.main()
