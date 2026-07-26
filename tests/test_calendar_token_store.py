import os
import tempfile
import unittest

from scheduling.calendar_token_store import CalendarTokenStore


class TestCalendarTokenStore(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self.store = CalendarTokenStore(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_save_and_load_round_trip(self):
        self.store.save_token(
            "business-a",
            {
                "token": "access-token-a",
                "refresh_token": "refresh-token-a",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": ["https://www.googleapis.com/auth/calendar.readonly"],
            },
        )

        loaded = self.store.load_token("business-a")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["business_id"], "business-a")
        self.assertEqual(loaded["token"], "access-token-a")
        self.assertEqual(loaded["refresh_token"], "refresh-token-a")
        self.assertEqual(loaded["token_uri"], "https://oauth2.googleapis.com/token")
        self.assertEqual(
            loaded["scopes"], ["https://www.googleapis.com/auth/calendar.readonly"]
        )

    def test_load_missing_business_returns_none(self):
        self.assertIsNone(self.store.load_token("nonexistent-business"))

    def test_save_replaces_on_reconnect(self):
        self.store.save_token(
            "business-a",
            {"token": "old-token", "refresh_token": "r1", "token_uri": "u", "scopes": []},
        )
        self.store.save_token(
            "business-a",
            {"token": "new-token", "refresh_token": "r2", "token_uri": "u", "scopes": []},
        )

        loaded = self.store.load_token("business-a")
        self.assertEqual(loaded["token"], "new-token")
        self.assertEqual(loaded["refresh_token"], "r2")

        conn = self.store._get_connection()
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM calendar_tokens WHERE business_id = ?",
            ("business-a",),
        ).fetchone()["n"]
        conn.close()
        self.assertEqual(count, 1)

    def test_delete_removes_token(self):
        self.store.save_token(
            "business-a",
            {"token": "t", "refresh_token": "r", "token_uri": "u", "scopes": []},
        )
        self.store.delete_token("business-a")
        self.assertIsNone(self.store.load_token("business-a"))

    def test_business_id_isolation(self):
        self.store.save_token(
            "business-a",
            {"token": "token-a", "refresh_token": "r-a", "token_uri": "u", "scopes": []},
        )
        self.store.save_token(
            "business-b",
            {"token": "token-b", "refresh_token": "r-b", "token_uri": "u", "scopes": []},
        )

        loaded_a = self.store.load_token("business-a")
        loaded_b = self.store.load_token("business-b")
        self.assertEqual(loaded_a["token"], "token-a")
        self.assertEqual(loaded_b["token"], "token-b")

        # Deleting/replacing one business's token must not affect the
        # other's.
        self.store.delete_token("business-a")
        self.assertIsNone(self.store.load_token("business-a"))
        self.assertIsNotNone(self.store.load_token("business-b"))
        self.assertEqual(self.store.load_token("business-b")["token"], "token-b")


if __name__ == "__main__":
    unittest.main()
