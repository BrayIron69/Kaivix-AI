from database import postgres
from memory.conversation_store import (
    DEFAULT_CONVERSATION_LIMIT,
    BaseConversationStore,
    list_conversations_sql,
    row_to_conversation,
)


class PostgresConversationStore(BaseConversationStore):
    """
    Postgres-backed conversation transcripts.

    Same reason as crm/postgres_crm.py: memory/conversation_memory.db
    lives on Render's wiped-on-deploy filesystem, so every transcript
    was destroyed on every push. That is not only lost history -- the
    admin dashboard renders a lead's transcript on its detail page, and
    delete_lead clears the conversations behind a lead, so leaving this
    on SQLite while moving leads to Postgres would produce leads that
    permanently show "no conversation on record".

    Tenant-scoped on (business_id, conversation_id), exactly as
    SQLiteConversationStore is, and for the same documented reason:
    conversation ids are generated client-side ('session_' +
    Math.random() in chat_widget.html), so they are not unique by
    construction and a collision across tenants must never surface one
    business's transcript on another's lead.
    """

    def __init__(self):
        postgres.log_backend_choice("Conversation memory", using_postgres=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_messages (
                        id SERIAL PRIMARY KEY,
                        business_id TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                # Every read is by this pair, and a transcript view that
                # scans the whole table gets slower with every
                # conversation the product ever has.
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS conversation_messages_scope_idx
                    ON conversation_messages (business_id, conversation_id, id)
                    """
                )
                # Which visitor owns which conversation -- see the same
                # table in memory/conversation_store.py for why this is
                # a separate table rather than a column on
                # conversation_messages.
                #
                # CREATE TABLE IF NOT EXISTS is the whole migration:
                # this table is new, so there is no existing data to
                # backfill. Threads that predate it simply have no
                # visitor row and never appear in a Messages tab, which
                # is correct -- nothing recorded who they belonged to.
                cursor.execute(
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
                cursor.execute(
                    """
                    CREATE INDEX IF NOT EXISTS conversation_visitors_lookup_idx
                    ON conversation_visitors (business_id, visitor_id)
                    """
                )
        conn.close()

    def add_message(self, business_id: str, conversation_id: str, role: str, content: str) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_messages
                        (business_id, conversation_id, role, content)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (business_id, conversation_id, role, content),
                )
        conn.close()

    def get_messages(self, business_id: str, conversation_id: str) -> list[dict]:
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, content
                FROM conversation_messages
                WHERE business_id = %s AND conversation_id = %s
                ORDER BY id ASC
                """,
                (business_id, conversation_id),
            )
            rows = cursor.fetchall()
        conn.close()

        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def clear(self, business_id: str, conversation_id: str) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM conversation_messages
                    WHERE business_id = %s AND conversation_id = %s
                    """,
                    (business_id, conversation_id),
                )
                # Same reason as the SQLite store: the admin delete path
                # calls this, and an orphaned visitor link would keep
                # listing a thread with no messages left in it.
                cursor.execute(
                    """
                    DELETE FROM conversation_visitors
                    WHERE business_id = %s AND conversation_id = %s
                    """,
                    (business_id, conversation_id),
                )
        conn.close()

    def link_visitor(
        self,
        business_id: str,
        conversation_id: str,
        visitor_id: str,
    ) -> None:
        # ON CONFLICT DO NOTHING is Postgres's INSERT OR IGNORE: the
        # first turn of a thread records its owner, every later turn is
        # a no-op, and a request naming a different visitor for an
        # existing thread cannot reassign it.
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO conversation_visitors
                        (business_id, conversation_id, visitor_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (business_id, conversation_id) DO NOTHING
                    """,
                    (business_id, conversation_id, visitor_id),
                )
        conn.close()

    def get_visitor_id(self, business_id: str, conversation_id: str) -> str | None:
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT visitor_id FROM conversation_visitors
                WHERE business_id = %s AND conversation_id = %s
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
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                list_conversations_sql("%s"),
                (business_id, visitor_id, limit),
            )
            rows = cursor.fetchall()
        conn.close()

        return [row_to_conversation(row) for row in rows]
