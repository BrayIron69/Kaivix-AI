import os
import sqlite3
import tempfile
import unittest
from datetime import datetime

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

    def test_expiry_round_trips(self):
        self.store.save_token(
            "business-a",
            {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "u",
                "scopes": [],
                "expiry": "2026-07-29T12:00:00",
            },
        )

        self.assertEqual(
            self.store.load_token("business-a")["expiry"],
            "2026-07-29T12:00:00",
        )

    def test_expiry_accepts_a_datetime(self):
        self.store.save_token(
            "business-a",
            {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "u",
                "scopes": [],
                "expiry": datetime(2026, 7, 29, 12, 0, 0),
            },
        )

        self.assertEqual(
            self.store.load_token("business-a")["expiry"],
            "2026-07-29T12:00:00",
        )

    def test_missing_expiry_is_stored_as_null(self):
        self.store.save_token(
            "business-a",
            {"token": "t", "refresh_token": "r", "token_uri": "u", "scopes": []},
        )

        self.assertIsNone(self.store.load_token("business-a")["expiry"])

    def test_reconnect_replaces_a_stale_expiry(self):
        self.store.save_token(
            "business-a",
            {
                "token": "old",
                "refresh_token": "r",
                "token_uri": "u",
                "scopes": [],
                "expiry": "2020-01-01T00:00:00",
            },
        )
        self.store.save_token(
            "business-a",
            {
                "token": "new",
                "refresh_token": "r",
                "token_uri": "u",
                "scopes": [],
                "expiry": "2030-01-01T00:00:00",
            },
        )

        self.assertEqual(
            self.store.load_token("business-a")["expiry"],
            "2030-01-01T00:00:00",
        )


class TestCalendarTokenStoreExpiryMigration(unittest.TestCase):
    """
    The deployed calendar_tokens.db predates the expiry column, so
    opening it must ALTER the existing table rather than rely on
    CREATE TABLE IF NOT EXISTS (which is a no-op on an existing table).
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def _create_pre_expiry_schema(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE calendar_tokens (
                business_id TEXT PRIMARY KEY,
                token TEXT,
                refresh_token TEXT,
                token_uri TEXT,
                scopes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO calendar_tokens
                (business_id, token, refresh_token, token_uri, scopes)
            VALUES ('kaivix', 'legacy-token', 'legacy-refresh', 'u', '[]')
            """
        )
        conn.commit()
        conn.close()

    def test_existing_db_gains_the_expiry_column(self):
        self._create_pre_expiry_schema()

        store = CalendarTokenStore(db_path=self.db_path)

        conn = store._get_connection()
        columns = {row[1] for row in conn.execute("PRAGMA table_info(calendar_tokens)")}
        conn.close()

        self.assertIn("expiry", columns)

    def test_pre_existing_row_survives_the_migration(self):
        self._create_pre_expiry_schema()

        store = CalendarTokenStore(db_path=self.db_path)
        loaded = store.load_token("kaivix")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["token"], "legacy-token")
        self.assertEqual(loaded["refresh_token"], "legacy-refresh")
        # Unknown, not "never expires" -- the provider falls back to the
        # library's own check for these rows.
        self.assertIsNone(loaded["expiry"])

    def test_migration_is_idempotent(self):
        self._create_pre_expiry_schema()

        CalendarTokenStore(db_path=self.db_path)
        store = CalendarTokenStore(db_path=self.db_path)

        store.save_token(
            "kaivix",
            {
                "token": "t",
                "refresh_token": "r",
                "token_uri": "u",
                "scopes": [],
                "expiry": "2030-01-01T00:00:00",
            },
        )

        self.assertEqual(
            store.load_token("kaivix")["expiry"], "2030-01-01T00:00:00"
        )


class TestCalendarTokenStoreVerifiers(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self.store = CalendarTokenStore(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_pending_verifier_save_and_pop_round_trip(self):
        self.store.save_pending_verifier("kaivix", "verifier-abc123")
        self.assertEqual(self.store.pop_pending_verifier("kaivix"), "verifier-abc123")

    def test_pop_pending_verifier_deletes_it(self):
        self.store.save_pending_verifier("kaivix", "verifier-abc123")
        self.store.pop_pending_verifier("kaivix")

        # A second pop must find nothing -- a verifier is never reused.
        self.assertIsNone(self.store.pop_pending_verifier("kaivix"))

    def test_pop_pending_verifier_returns_none_when_absent(self):
        self.assertIsNone(self.store.pop_pending_verifier("never-started"))

    def test_save_pending_verifier_replaces_on_repeated_handshake(self):
        self.store.save_pending_verifier("kaivix", "first-verifier")
        self.store.save_pending_verifier("kaivix", "second-verifier")

        self.assertEqual(self.store.pop_pending_verifier("kaivix"), "second-verifier")


if __name__ == "__main__":
    unittest.main()
