import json
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime


class BaseOfferedSlotStore(ABC):
    """
    The times most recently offered to one visitor, durably.

    ConversationEngine held these in a process-local dict
    (_offered_slot_windows) alongside WorkingMemory.offered_slots, both
    in memory. A restart between "here are three times" and "2" left
    nothing to resolve the reply against, so the booking silently never
    happened -- and on Render's free plan the service spins down after
    ~15 minutes idle, so a visitor who steps away before choosing hits
    this routinely.

    Recomputing availability instead of storing it would be WRONG, not
    merely slower: the visitor's "2" refers to the list they were shown,
    and a fresh free/busy lookup minutes later can return a different
    set (time has passed, a slot may have been taken). Matching "2"
    against a recomputed list books a time nobody agreed to. That is
    exactly the ambiguity scheduling/slot_matcher.py refuses to guess
    at, and the same reasoning applies here.

    Both halves are stored together. The display string is what the
    visitor actually saw and what gets confirmed back to them; the
    start/end datetimes are what the booking is made from. Keeping them
    in one record makes it impossible for the text and the time to drift
    apart, which is the failure _maybe_resolve_booking's
    "matched a display string but have no window" branch exists to
    catch.
    """

    @abstractmethod
    def save(self, business_id: str, conversation_id: str, slots: list[dict]) -> None:
        """Replace the offered slots for this conversation."""

    @abstractmethod
    def load(self, business_id: str, conversation_id: str) -> list[dict]:
        """The offered slots, in the order presented. Empty when none."""

    @abstractmethod
    def clear(self, business_id: str, conversation_id: str) -> None:
        """Drop them, once booked or abandoned."""


def serialize_slots(windows, display_texts) -> list[dict]:
    """
    Pair structured (start, end) windows with the text the visitor saw,
    ready to store. Datetimes go to ISO-8601, which round-trips the
    timezone the business's calendar returned.
    """
    slots = []
    for (start, end), display in zip(windows, display_texts):
        slots.append(
            {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "display": display,
            }
        )
    return slots


def deserialize_window(slot: dict):
    """
    (start, end) datetimes for one stored slot, or None if either side
    is unparseable -- in which case the caller must fail safely rather
    than guess a time, the same way a missing cached window already does.
    """
    try:
        return (
            datetime.fromisoformat(slot["start"]),
            datetime.fromisoformat(slot["end"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


class SQLiteOfferedSlotStore(BaseOfferedSlotStore):
    """
    Local-development backing. On Render this file is wiped on every
    deploy like every other SQLite file here, which is precisely why
    PostgresOfferedSlotStore exists and is chosen whenever DATABASE_URL
    is set.
    """

    DB_PATH = "scheduling/offered_slots.db"

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self.DB_PATH
        self._ensure_schema()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS offered_slots (
                business_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                slots TEXT NOT NULL,
                offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (business_id, conversation_id)
            )
            """
        )
        conn.commit()
        conn.close()

    def save(self, business_id: str, conversation_id: str, slots: list[dict]) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO offered_slots (business_id, conversation_id, slots)
            VALUES (?, ?, ?)
            ON CONFLICT(business_id, conversation_id) DO UPDATE SET
                slots = excluded.slots,
                offered_at = CURRENT_TIMESTAMP
            """,
            (business_id, conversation_id, json.dumps(slots)),
        )
        conn.commit()
        conn.close()

    def load(self, business_id: str, conversation_id: str) -> list[dict]:
        conn = self._get_connection()
        row = conn.execute(
            """
            SELECT slots FROM offered_slots
            WHERE business_id = ? AND conversation_id = ?
            """,
            (business_id, conversation_id),
        ).fetchone()
        conn.close()

        if row is None:
            return []

        try:
            decoded = json.loads(row["slots"])
        except (TypeError, ValueError):
            return []

        return decoded if isinstance(decoded, list) else []

    def clear(self, business_id: str, conversation_id: str) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            DELETE FROM offered_slots
            WHERE business_id = ? AND conversation_id = ?
            """,
            (business_id, conversation_id),
        )
        conn.commit()
        conn.close()


def get_offered_slot_store() -> BaseOfferedSlotStore:
    """
    Postgres when DATABASE_URL is set, SQLite otherwise -- the same
    deployment-follows-the-environment rule ConversationMemory and the
    lead-conversation links already use.
    """
    from database import postgres

    if postgres.is_configured():
        from scheduling.postgres_offered_slot_store import PostgresOfferedSlotStore

        return PostgresOfferedSlotStore()

    return SQLiteOfferedSlotStore()
