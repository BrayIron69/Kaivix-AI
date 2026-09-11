import json
from datetime import datetime, timezone

from database import postgres
from memory.long_term_memory import (
    BaseLongTermMemoryStore,
    SQLiteLongTermMemoryStore,
)


class PostgresLongTermMemoryStore(BaseLongTermMemoryStore):
    """
    Postgres-backed cross-session visitor profiles.

    memory/long_term_memory.db is on the same wiped-on-deploy filesystem
    as the leads and the transcripts, so the one thing this store exists
    to do -- recognise a returning visitor and recall what they told us
    last time -- silently stopped working on every deploy.

    Field lists and JSON encoding are imported from
    SQLiteLongTermMemoryStore rather than restated, so the two stores
    cannot disagree about what a profile contains. Only the SQL differs,
    which is the one thing that genuinely has to.
    """

    _SCALAR_FIELDS = SQLiteLongTermMemoryStore._SCALAR_FIELDS
    _LIST_FIELDS = SQLiteLongTermMemoryStore._LIST_FIELDS

    def __init__(self):
        postgres.log_backend_choice("Long-term memory", using_postgres=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS long_term_memory (
                        key TEXT PRIMARY KEY,
                        business_id TEXT DEFAULT '',
                        name TEXT DEFAULT '',
                        company TEXT DEFAULT '',
                        email TEXT DEFAULT '',
                        industry TEXT DEFAULT '',
                        budget TEXT DEFAULT '',
                        timeline TEXT DEFAULT '',
                        important_notes TEXT DEFAULT '',
                        products_of_interest TEXT DEFAULT '[]',
                        pain_points TEXT DEFAULT '[]',
                        objections TEXT DEFAULT '[]',
                        buying_signals TEXT DEFAULT '[]',
                        preferences TEXT DEFAULT '[]',
                        previous_conversations TEXT DEFAULT '[]',
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
        conn.close()

    def get(self, key: str) -> dict | None:
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM long_term_memory WHERE key = %s", (key,))
            row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_profile(row)

    def save(self, key: str, profile: dict) -> None:
        """
        Upsert in ONE statement, unlike the SQLite store's read-then-
        insert-or-update. Postgres has ON CONFLICT and the table has a
        primary key to hang it on, so there is no reason to keep a
        check-then-act pair that two concurrent turns for the same
        visitor could interleave inside.
        """
        now = datetime.now(timezone.utc).isoformat()

        values = {field: profile.get(field, "") for field in self._SCALAR_FIELDS}
        for list_field in self._LIST_FIELDS:
            values[list_field] = json.dumps(profile.get(list_field) or [])

        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO long_term_memory (
                        key, business_id, name, company, email, industry,
                        budget, timeline, important_notes,
                        products_of_interest, pain_points, objections,
                        buying_signals, preferences, previous_conversations,
                        created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                        business_id = EXCLUDED.business_id,
                        name = EXCLUDED.name,
                        company = EXCLUDED.company,
                        email = EXCLUDED.email,
                        industry = EXCLUDED.industry,
                        budget = EXCLUDED.budget,
                        timeline = EXCLUDED.timeline,
                        important_notes = EXCLUDED.important_notes,
                        products_of_interest = EXCLUDED.products_of_interest,
                        pain_points = EXCLUDED.pain_points,
                        objections = EXCLUDED.objections,
                        buying_signals = EXCLUDED.buying_signals,
                        preferences = EXCLUDED.preferences,
                        previous_conversations = EXCLUDED.previous_conversations,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        key,
                        profile.get("business_id", "") or "",
                        values["name"],
                        values["company"],
                        values["email"],
                        values["industry"],
                        values["budget"],
                        values["timeline"],
                        values["important_notes"],
                        values["products_of_interest"],
                        values["pain_points"],
                        values["objections"],
                        values["buying_signals"],
                        values["preferences"],
                        values["previous_conversations"],
                        now,
                        now,
                    ),
                )
        conn.close()

    def _row_to_profile(self, row) -> dict:
        """
        Rows arrive as dicts here (see database/postgres.get_connection),
        where the SQLite store receives sqlite3.Row. Both are read by
        column name, so the only real work is decoding the JSON list
        columns -- and a value that isn't valid JSON becomes an empty
        list rather than taking down the turn, matching the SQLite
        store's tolerance.
        """
        profile = {"key": row.get("key")}

        for field in self._SCALAR_FIELDS:
            profile[field] = row.get(field) or ""

        for field in self._LIST_FIELDS:
            raw = row.get(field) or "[]"
            try:
                decoded = json.loads(raw)
            except (TypeError, ValueError):
                decoded = []
            profile[field] = decoded if isinstance(decoded, list) else []

        profile["business_id"] = row.get("business_id") or ""
        profile["created_at"] = row.get("created_at") or ""
        profile["updated_at"] = row.get("updated_at") or ""

        return profile
