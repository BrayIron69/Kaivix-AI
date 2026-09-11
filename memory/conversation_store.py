from abc import ABC, abstractmethod
from datetime import datetime, timezone
import sqlite3

from core_ai.business_config import DEFAULT_BUSINESS_ID

# Longest preview text returned per thread by list_conversations().
#
# The Messages tab renders one line per thread, so the full last message
# is wasted payload -- a visitor with a long transcript would otherwise
# download every final message in full just to render a list. Truncation
# happens in Python rather than in SQL so SQLite and Postgres cannot
# disagree about it (Rule 6: the logic exists in exactly one place).
PREVIEW_MAX_LENGTH = 140

# Most threads list_conversations() will return in one call, when the
# caller does not ask for fewer. Bounds the response for a visitor who
# has accumulated a long history; the API layer caps what a caller may
# request on top of this.
DEFAULT_CONVERSATION_LIMIT = 50


def build_preview(content: str) -> str:
    """
    Collapse one message into the single line the Messages tab shows.

    Whitespace is flattened first so a multi-line message does not
    render as a ragged preview, then the result is cut to
    PREVIEW_MAX_LENGTH with an ellipsis. Shared by every store
    implementation rather than reimplemented per backend.
    """
    flattened = " ".join((content or "").split())

    if len(flattened) <= PREVIEW_MAX_LENGTH:
        return flattened

    return flattened[: PREVIEW_MAX_LENGTH - 1].rstrip() + "…"


def normalize_timestamp(value) -> str:
    """
    Render a stored timestamp as an ISO 8601 UTC string.

    The two backends hand back different Python types for the same
    column -- SQLite returns the raw 'YYYY-MM-DD HH:MM:SS' text it
    stored, Postgres returns a datetime -- and the widget must not have
    to care which database is behind the API. Both are normalized here,
    at the one point where backend differences are already being
    absorbed.

    CURRENT_TIMESTAMP is UTC in both engines, so a naive value is
    labelled UTC rather than reinterpreted in local time.
    """
    if value is None:
        return ""

    if isinstance(value, datetime):
        moment = value
    else:
        try:
            moment = datetime.fromisoformat(str(value))
        except ValueError:
            # Unparseable values are passed through rather than raising:
            # a malformed timestamp should not make a visitor's whole
            # thread list unreadable.
            return str(value)

    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def list_conversations_sql(placeholder: str) -> str:
    """
    The thread-index query, in whichever placeholder style the caller's
    driver uses (sqlite3 takes '?', psycopg takes '%s').

    Shared rather than written once per store because -- unlike the
    one-line add/get/clear statements the two stores already spell out
    separately -- this query carries real logic that must not drift
    between backends: which conversations belong to a visitor, how
    recency is defined, and what a preview is.

    Recency is MAX(created_at) over the thread's messages, so "most
    recent first" means last activity rather than when the thread
    started. MAX(id) breaks ties, because CURRENT_TIMESTAMP is only
    second-granular in SQLite and two messages can share a timestamp.

    The JOIN (not LEFT JOIN) is what drops message-less conversations.
    The correlated subquery takes the newest message by id rather than
    by created_at for the same tie-breaking reason.
    """
    p = placeholder

    return f"""
        SELECT
            v.conversation_id AS conversation_id,
            MAX(m.created_at) AS last_message_at,
            COUNT(m.id) AS message_count,
            (
                SELECT last_message.content
                FROM conversation_messages last_message
                WHERE last_message.business_id = v.business_id
                  AND last_message.conversation_id = v.conversation_id
                ORDER BY last_message.id DESC
                LIMIT 1
            ) AS preview
        FROM conversation_visitors v
        JOIN conversation_messages m
          ON m.business_id = v.business_id
         AND m.conversation_id = v.conversation_id
        WHERE v.business_id = {p} AND v.visitor_id = {p}
        GROUP BY v.business_id, v.conversation_id
        ORDER BY last_message_at DESC, MAX(m.id) DESC
        LIMIT {p}
    """


def row_to_conversation(row) -> dict:
    """
    Shape one thread-index row into the dict the API returns.

    Both drivers return rows addressable by column name (sqlite3.Row and
    psycopg's dict_row), so one mapping serves both.
    """
    return {
        "conversation_id": row["conversation_id"],
        "last_message_at": normalize_timestamp(row["last_message_at"]),
        "message_count": row["message_count"],
        "preview": build_preview(row["preview"]),
    }


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

    @abstractmethod
    def link_visitor(
        self,
        business_id: str,
        conversation_id: str,
        visitor_id: str,
    ) -> None:
        """
        Record which visitor a conversation belongs to.

        Idempotent: called on every turn, but only the first call for a
        given conversation writes anything. A conversation belongs to
        exactly one visitor for its whole life, so a later call naming a
        different visitor is ignored rather than reassigning the thread
        -- that would hand one visitor's transcript to another.
        """
        raise NotImplementedError

    @abstractmethod
    def get_visitor_id(self, business_id: str, conversation_id: str) -> str | None:
        """
        Which visitor owns this conversation, or None if nothing does.

        This is an authorization primitive, not a convenience. Existing
        conversation ids are 'session_' + Math.random() -- low entropy
        and trivially guessable -- so "fetch this conversation's
        messages" must never be answerable from a conversation_id
        alone. Callers compare this against the visitor actually asking
        and refuse on a mismatch.
        """
        raise NotImplementedError

    @abstractmethod
    def list_conversations(
        self,
        business_id: str,
        visitor_id: str,
        limit: int = DEFAULT_CONVERSATION_LIMIT,
    ) -> list[dict]:
        """
        Return this visitor's conversations, most recently active first.

        Each entry carries `conversation_id`, `last_message_at` (ISO
        8601 UTC), `message_count`, and `preview` -- everything the
        Messages tab renders per row, so listing threads costs one query
        rather than one query per thread.

        Conversations with no messages are omitted: a thread that was
        opened and abandoned without a word is not something a visitor
        can meaningfully reopen.
        """
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
        # Which visitor owns which conversation. Deliberately a separate
        # table rather than a visitor_id column on conversation_messages:
        # the visitor is a property of the thread, not of each message,
        # so storing it per-row would repeat it on every turn and leave
        # room for a thread whose rows disagree about who owns it. It
        # also means this feature adds no column to the table the
        # conversation engine writes on its hot path, and no existing
        # write site changes.
        #
        # PRIMARY KEY on (business_id, conversation_id) enforces
        # one-visitor-per-thread in the schema rather than in Python, and
        # is what makes link_visitor's INSERT OR IGNORE idempotent.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_visitors (
                business_id TEXT NOT NULL,
                conversation_id TEXT NOT NULL,
                visitor_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (business_id, conversation_id)
            )
            """
        )
        # The Messages tab's only query is "threads for this visitor",
        # which without this index scans every thread the product has.
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_conversation_visitors_business_visitor
            ON conversation_visitors (business_id, visitor_id)
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
        # The visitor link goes too. clear() is what the admin
        # dashboard's delete path calls, and leaving the row behind
        # would keep listing a thread whose messages no longer exist.
        conn.execute(
            """
            DELETE FROM conversation_visitors
            WHERE business_id = ? AND conversation_id = ?
            """,
            (business_id, conversation_id),
        )
        conn.commit()
        conn.close()

    def link_visitor(
        self,
        business_id: str,
        conversation_id: str,
        visitor_id: str,
    ) -> None:
        # OR IGNORE against the (business_id, conversation_id) primary
        # key is what makes this idempotent and what makes a later,
        # different visitor_id a no-op instead of a reassignment.
        conn = self._get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO conversation_visitors
                (business_id, conversation_id, visitor_id)
            VALUES (?, ?, ?)
            """,
            (business_id, conversation_id, visitor_id),
        )
        conn.commit()
        conn.close()

    def get_visitor_id(self, business_id: str, conversation_id: str) -> str | None:
        conn = self._get_connection()
        cursor = conn.execute(
            """
            SELECT visitor_id FROM conversation_visitors
            WHERE business_id = ? AND conversation_id = ?
            """,
            (business_id, conversation_id),
        )
        row = cursor.fetchone()
        conn.close()

        return row["visitor_id"] if row else None

    def list_conversations(
        self,
        business_id: str,
        visitor_id: str,
        limit: int = DEFAULT_CONVERSATION_LIMIT,
    ) -> list[dict]:
        conn = self._get_connection()
        cursor = conn.execute(
            list_conversations_sql("?"),
            (business_id, visitor_id, limit),
        )
        rows = cursor.fetchall()
        conn.close()

        return [row_to_conversation(row) for row in rows]
