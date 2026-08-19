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
