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

    Also holds oauth_pending_verifiers, a short-lived handshake table:
    get_authorization_url() and handle_oauth_callback() run in two
    separate HTTP requests (and so build two independent Flow objects),
    but Google's PKCE flow requires the same code_verifier used to
    generate the authorization request's code_challenge to be replayed
    during the token exchange. This table is that bridge -- keyed by
    `state` (which GoogleCalendarProvider already sets to business_id),
    not by business_id itself, since it's a per-handshake value, not a
    per-business one. Deliberately a persisted table, not an in-memory
    dict: an in-memory store would silently break under multiple server
    workers/instances (the planned Cloud Run deployment may use more
    than one).
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
                expiry TEXT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oauth_pending_verifiers (
                state TEXT PRIMARY KEY,
                code_verifier TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # `expiry` was added after the first deployment, so an existing
        # calendar_tokens.db (including the live one) predates it and
        # CREATE TABLE IF NOT EXISTS above won't add it. Same additive
        # ALTER-if-missing migration crm/database.py uses. Rows written
        # before this keep expiry NULL, which GoogleCalendarProvider
        # treats as "unknown, fall back to the library's own check"
        # rather than as "never expires".
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(calendar_tokens)")
        }
        if "expiry" not in existing_columns:
            conn.execute("ALTER TABLE calendar_tokens ADD COLUMN expiry TEXT")

        conn.commit()
        conn.close()

    @staticmethod
    def _serialize_expiry(expiry) -> str | None:
        """
        Normalize an expiry to ISO-8601 text for storage. Accepts a
        datetime or an already-formatted string so callers can pass
        either; anything falsy becomes NULL.
        """
        if not expiry:
            return None

        if isinstance(expiry, datetime):
            return expiry.isoformat()

        return str(expiry)

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
                business_id, token, refresh_token, token_uri, scopes,
                expiry, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(business_id) DO UPDATE SET
                token = excluded.token,
                refresh_token = excluded.refresh_token,
                token_uri = excluded.token_uri,
                scopes = excluded.scopes,
                expiry = excluded.expiry,
                updated_at = excluded.updated_at
            """,
            (
                business_id,
                credentials_dict.get("token"),
                credentials_dict.get("refresh_token"),
                credentials_dict.get("token_uri"),
                scopes_json,
                self._serialize_expiry(credentials_dict.get("expiry")),
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
            "expiry": row["expiry"],
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

    # ------------------------------------------------------------------
    # OAuth handshake (PKCE code_verifier bridge)
    # ------------------------------------------------------------------

    def save_pending_verifier(self, state: str, code_verifier: str) -> None:
        """
        Save the code_verifier generated for this OAuth handshake
        (keyed by `state`), so the later, separate /callback request can
        retrieve it via pop_pending_verifier(). Replaces any existing row
        for the same `state` -- only the most recent handshake for a
        given state can complete.
        """
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO oauth_pending_verifiers (state, code_verifier)
            VALUES (?, ?)
            ON CONFLICT(state) DO UPDATE SET
                code_verifier = excluded.code_verifier,
                created_at = CURRENT_TIMESTAMP
            """,
            (state, code_verifier),
        )
        conn.commit()
        conn.close()

    def pop_pending_verifier(self, state: str) -> str | None:
        """
        Retrieve AND delete the pending code_verifier for `state`, in one
        call, so a given handshake's verifier is never reused. Returns
        None if no pending verifier is on record (expired, already used,
        or the handshake never started).
        """
        conn = self._get_connection()
        row = conn.execute(
            "SELECT code_verifier FROM oauth_pending_verifiers WHERE state = ?",
            (state,),
        ).fetchone()

        if row is not None:
            conn.execute(
                "DELETE FROM oauth_pending_verifiers WHERE state = ?",
                (state,),
            )
            conn.commit()

        conn.close()
        return row["code_verifier"] if row is not None else None
