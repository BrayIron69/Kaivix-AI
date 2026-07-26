import json
import sqlite3
from datetime import datetime, timezone


class CalendarTokenStore:
    """
    Tenant-scoped SQLite storage for calendar OAuth tokens.

    Mirrors memory/long_term_memory.py's SQLiteLongTermMemoryStore
    pattern: this class owns nothing but "save a token dict for a
    business_id" / "load it back" / "delete it" -- GoogleCalendarProvider
    owns all OAuth/refresh logic and is the only caller.

    business_id is the PRIMARY KEY: one calendar connection per business.
    Reconnecting (save_token again for the same business_id) replaces the
    previous row rather than accumulating history -- there is exactly one
    "current" calendar connection per business at a time.

    client_id/client_secret are deliberately NOT stored here. There is
    one shared Google Cloud OAuth app for all businesses today (not
    per-business OAuth apps), so those come from
    GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET env vars at the provider level,
    not from a per-row value.
    """

    DB_PATH = "scheduling/calendar_tokens.db"

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self.DB_PATH
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calendar_tokens (
                business_id TEXT PRIMARY KEY,
                token TEXT,
                refresh_token TEXT,
                token_uri TEXT,
                scopes TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_token(self, business_id: str, credentials_dict: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        scopes_json = json.dumps(credentials_dict.get("scopes") or [])

        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO calendar_tokens (
                business_id, token, refresh_token, token_uri, scopes, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(business_id) DO UPDATE SET
                token = excluded.token,
                refresh_token = excluded.refresh_token,
                token_uri = excluded.token_uri,
                scopes = excluded.scopes,
                updated_at = excluded.updated_at
            """,
            (
                business_id,
                credentials_dict.get("token"),
                credentials_dict.get("refresh_token"),
                credentials_dict.get("token_uri"),
                scopes_json,
                now,
            ),
        )
        conn.commit()
        conn.close()

    def load_token(self, business_id: str) -> dict | None:
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM calendar_tokens WHERE business_id = ?",
            (business_id,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return {
            "business_id": row["business_id"],
            "token": row["token"],
            "refresh_token": row["refresh_token"],
            "token_uri": row["token_uri"],
            "scopes": json.loads(row["scopes"] or "[]"),
            "updated_at": row["updated_at"],
        }

    def delete_token(self, business_id: str) -> None:
        conn = self._get_connection()
        conn.execute(
            "DELETE FROM calendar_tokens WHERE business_id = ?",
            (business_id,),
        )
        conn.commit()
        conn.close()
