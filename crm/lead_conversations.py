"""
Every conversation a lead has ever had, not just the most recent one.

Why this exists
---------------
leads.conversation_id records a single conversation and is overwritten
on each sync, so a returning visitor's earlier conversations stayed in
memory/conversation_memory.db with nothing pointing at them. Two
consequences, one cosmetic and one not:

  - The admin dashboard could only ever show the latest transcript.
  - Deleting a lead cleared only the conversation the lead still named.
    Every earlier transcript -- the visitor's own words -- survived the
    delete, unreachable and unreviewable. For a delete offered as "this
    removes the lead and its conversation", that is the wrong outcome.

Keyed by (business_id, email) to match how a lead is identified
everywhere else (LeadService.get_by_email / delete_lead,
UNIQUE(business_id, email) on leads), rather than by leads.id, so a link
survives the lead row being rewritten.

Lives in crm/ and shares leads.db because this is a fact about the lead
record. The conversation CONTENT stays in memory/conversation_memory.db,
owned by ConversationMemory -- this table holds only the pointer.
"""

from core_ai.business_config import DEFAULT_BUSINESS_ID
from crm.database import get_connection


class LeadConversationLinks:
    """
    Pointers from a lead to every conversation it has had.

    Deliberately not part of BaseCRM: that contract is implemented by
    every CRM provider, and this is a SQLite-schema concern rather than
    something a HubSpot/Salesforce provider would model the same way.
    Keeping it separate means adding it does not oblige every provider
    to grow a method.
    """

    def link(
        self,
        email: str,
        conversation_id: str,
        business_id: str = DEFAULT_BUSINESS_ID,
    ) -> None:
        """
        Record that `conversation_id` belongs to this lead.

        Called on every sync, so INSERT OR IGNORE against the composite
        primary key makes a repeat link a no-op and keeps first_seen as
        the genuine first sighting rather than the most recent one.
        """
        if not email or not conversation_id:
            return

        conn = get_connection()
        conn.execute(
            """
            INSERT OR IGNORE INTO lead_conversations
                (business_id, email, conversation_id)
            VALUES (?, ?, ?)
            """,
            (business_id, email, conversation_id),
        )
        conn.commit()
        conn.close()

    def conversation_ids_for(
        self, email: str, business_id: str = DEFAULT_BUSINESS_ID
    ) -> list[str]:
        """
        This lead's conversations, oldest first. Empty when the lead has
        none linked -- including every lead captured before this table
        existed, whose single conversation is still reachable through
        leads.conversation_id (see the admin view's fallback).
        """
        if not email:
            return []

        conn = get_connection()
        rows = conn.execute(
            """
            SELECT conversation_id
            FROM lead_conversations
            WHERE business_id = ? AND email = ?
            ORDER BY first_seen ASC, rowid ASC
            """,
            (business_id, email),
        ).fetchall()
        conn.close()

        return [row["conversation_id"] for row in rows]

    def email_for_conversation(
        self, conversation_id: str, business_id: str = DEFAULT_BUSINESS_ID
    ) -> str | None:
        """
        Which lead this conversation belongs to -- the reverse of
        conversation_ids_for, and the piece that lets a restarted
        process work out WHO it is talking to.

        ConversationEngine holds lead profiles in memory keyed by
        conversation_id, so a restart leaves it with a blank profile and
        no email, and LongTermMemory.hydrate (which keys on email)
        returns immediately without recovering anything. This lookup is
        what re-establishes the identity so the existing hydration can
        run. See ConversationEngine._get_lead.

        Returns None for a conversation with no linked lead, which is
        the normal state before a visitor has given an email: there is
        no durable identity to recover yet, and inventing one would be
        worse than starting fresh.
        """
        if not conversation_id:
            return None

        conn = get_connection()
        row = conn.execute(
            """
            SELECT email
            FROM lead_conversations
            WHERE business_id = ? AND conversation_id = ?
            ORDER BY first_seen DESC
            LIMIT 1
            """,
            (business_id, conversation_id),
        ).fetchone()
        conn.close()

        return row["email"] if row else None

    def delete_for(
        self, email: str, business_id: str = DEFAULT_BUSINESS_ID
    ) -> None:
        """
        Drop every link for this lead. Only the pointers -- clearing the
        conversation CONTENT is ConversationMemory's job, and the admin
        delete does both.
        """
        if not email:
            return

        conn = get_connection()
        conn.execute(
            """
            DELETE FROM lead_conversations
            WHERE business_id = ? AND email = ?
            """,
            (business_id, email),
        )
        conn.commit()
        conn.close()


def get_lead_conversation_links():
    """
    The link store this deployment should use.

    Postgres when DATABASE_URL is set, SQLite otherwise. Chosen here
    rather than by a providers.yaml field because this is deployment
    infrastructure, not a per-business choice: crm_provider says where a
    given business's LEADS go (and could reasonably be hubspot for one
    business and postgres for another), while this table is part of this
    codebase's own storage and follows the deployment.

    An explicit factory rather than dispatch inside the class, so the
    two implementations stay separately readable and a caller can still
    construct either one directly in a test.
    """
    from database import postgres

    if postgres.is_configured():
        from crm.postgres_lead_conversations import PostgresLeadConversationLinks

        return PostgresLeadConversationLinks()

    return LeadConversationLinks()
