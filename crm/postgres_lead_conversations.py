from core_ai.business_config import DEFAULT_BUSINESS_ID
from database import postgres


class PostgresLeadConversationLinks:
    """
    Postgres-backed pointers from a lead to every conversation it has
    had.

    Same public surface as crm/lead_conversations.LeadConversationLinks,
    chosen between them by get_lead_conversation_links() in that module.
    Deliberately NOT part of BaseCRM, for the reason its SQLite twin
    already documents: this is a schema concern of this codebase's own
    storage, not something a HubSpot or Salesforce provider would model
    the same way.

    The only real differences are dialect: %s placeholders, ON CONFLICT
    DO NOTHING in place of INSERT OR IGNORE, and ctid in place of
    SQLite's rowid as the stable tiebreaker when two links share a
    first_seen timestamp.
    """

    def __init__(self):
        postgres.log_backend_choice("Lead-conversation links", using_postgres=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS lead_conversations (
                        business_id TEXT NOT NULL,
                        email TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (business_id, email, conversation_id)
                    )
                    """
                )
        conn.close()

    def link(
        self,
        email: str,
        conversation_id: str,
        business_id: str = DEFAULT_BUSINESS_ID,
    ) -> None:
        """
        Called on every sync, so a repeat link must be a no-op that
        leaves first_seen as the genuine first sighting rather than the
        most recent one -- ON CONFLICT DO NOTHING, matching the SQLite
        store's INSERT OR IGNORE.
        """
        if not email or not conversation_id:
            return

        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO lead_conversations
                        (business_id, email, conversation_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (business_id, email, conversation_id) DO NOTHING
                    """,
                    (business_id, email, conversation_id),
                )
        conn.close()

    def conversation_ids_for(
        self, email: str, business_id: str = DEFAULT_BUSINESS_ID
    ) -> list[str]:
        if not email:
            return []

        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT conversation_id
                FROM lead_conversations
                WHERE business_id = %s AND email = %s
                ORDER BY first_seen ASC, ctid ASC
                """,
                (business_id, email),
            )
            rows = cursor.fetchall()
        conn.close()

        return [row["conversation_id"] for row in rows]

    def delete_for(self, email: str, business_id: str = DEFAULT_BUSINESS_ID) -> None:
        """
        Drops the pointers only. Clearing the conversation CONTENT is
        ConversationMemory's job, and the admin delete does both.
        """
        if not email:
            return

        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM lead_conversations
                    WHERE business_id = %s AND email = %s
                    """,
                    (business_id, email),
                )
        conn.close()
