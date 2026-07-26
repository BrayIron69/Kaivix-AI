from abc import ABC, abstractmethod
import sqlite3

from core_ai.business_config import DEFAULT_BUSINESS_ID


class BaseConversationStore(ABC):
    """
    Storage-backend contract for ConversationMemory.

    Mirrors the existing crm/base_crm.py + crm/sqlite_crm.py and
    memory/long_term_memory.py's BaseLongTermMemoryStore split: the
    ConversationMemory component owns all business logic and is
    backend-agnostic; a BaseConversationStore implementation owns
    nothing but "append a message" / "return a conversation's messages"
    / "delete a conversation's messages", scoped by (business_id,
    conversation_id). Swapping SQLite for another backend later means
    writing a new subclass of this class — ConversationMemory itself
    does not change.
    """

    @abstractmethod
    def add_message(
        self,
        business_id: str,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        """Append one message to a conversation."""
        raise NotImplementedError

    @abstractmethod
    def get_messages(self, business_id: str, conversation_id: str) -> list[dict]:
        """Return all messages for a conversation, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def clear(self, business_id: str, conversation_id: str) -> None:
        """Delete all messages for a conversation."""
        raise NotImplementedError


class SQLiteConversationStore(BaseConversationStore):
    """
    Default SQLite-backed implementation of BaseConversationStore.

    Uses its own database file, separate from crm/leads.db and
    memory/long_term_memory.db — this table holds raw per-turn
    conversation messages (the same data ConversationMemory used to
    keep only in a process-local defaultdict), not the durable
    cross-session profile fields LongTermMemory owns.

    Built tenant-scoped from the start (business_id is part of the
    schema and every query), unlike the CRM/LongTermMemory tables which
    needed a later retrofit — there is no pre-existing data to migrate
    here.
    """

    DB_PATH = "memory/conversation_memory.db"

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
            f"""
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_id TEXT NOT NULL DEFAULT '{DEFAULT_BUSINESS_ID}',
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_messages_business_conversation
            ON conversation_messages (business_id, conversation_id)
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_message(
        self,
        business_id: str,
        conversation_id: str,
        role: str,
        content: str,
    ) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            INSERT INTO conversation_messages (business_id, conversation_id, role, content)
            VALUES (?, ?, ?, ?)
            """,
            (business_id, conversation_id, role, content),
        )
        conn.commit()
        conn.close()

    def get_messages(self, business_id: str, conversation_id: str) -> list[dict]:
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT role, content FROM conversation_messages
            WHERE business_id = ? AND conversation_id = ?
            ORDER BY id ASC
            """,
            (business_id, conversation_id),
        )
        rows = cursor.fetchall()
        conn.close()

        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def clear(self, business_id: str, conversation_id: str) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            DELETE FROM conversation_messages
            WHERE business_id = ? AND conversation_id = ?
            """,
            (business_id, conversation_id),
        )
        conn.commit()
        conn.close()
