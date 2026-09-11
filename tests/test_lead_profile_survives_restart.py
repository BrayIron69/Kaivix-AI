"""
A conversation that outlives the process it started in.

Measured in production, not imagined: a deploy landed mid-conversation,
and because ConversationEngine._lead_profiles is an in-memory cache, the
next turn got a blank LeadProfile. Transcripts ARE durable (Postgres),
so the model kept talking as though it remembered the visitor -- it said
"Thanks, Pat" and read the address out of the history -- while every
deterministic Python path saw an empty lead. The booking that followed
went onto a real calendar with NO attendee and the title
"Kaivix Demo Call - ", after Bray had promised an invite was on its way.

The dangerous part is the divergence: the model's apparent memory and
the system's actual state disagreed, and only the model's half was
visible to the visitor.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.conversation_store as conversation_store_module
import memory.long_term_memory as ltm_module
from core_ai.conversation_plan import ConversationPlan
from core_ai.lead_profile import LeadProfile
from core_ai.prompt_builder import PromptBuilder
from crm.lead_conversations import LeadConversationLinks


class _IsolatedDatabasesMixin:
    def _isolate_databases(self):
        paths = []
        for _ in range(3):
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            os.remove(path)
            paths.append(path)
        crm_db, ltm_db, conv_db = paths

        originals = (
            crm_database.DATABASE_NAME,
            ltm_module.SQLiteLongTermMemoryStore.DB_PATH,
            conversation_store_module.SQLiteConversationStore.DB_PATH,
        )
        crm_database.DATABASE_NAME = crm_db
        ltm_module.SQLiteLongTermMemoryStore.DB_PATH = ltm_db
        conversation_store_module.SQLiteConversationStore.DB_PATH = conv_db

        def _restore():
            (
                crm_database.DATABASE_NAME,
                ltm_module.SQLiteLongTermMemoryStore.DB_PATH,
                conversation_store_module.SQLiteConversationStore.DB_PATH,
            ) = originals
            for p in paths:
                if os.path.exists(p):
                    os.remove(p)

        self.addCleanup(_restore)


class TestReverseLookup(_IsolatedDatabasesMixin, unittest.TestCase):
    """The piece that re-establishes WHO a conversation belongs to."""

    def setUp(self):
        self._isolate_databases()
        self.links = LeadConversationLinks()

    def test_finds_the_lead_behind_a_conversation(self):
        self.links.link("nadia@example.com", "conv-1", business_id="kaivix")

        self.assertEqual(
            self.links.email_for_conversation("conv-1", business_id="kaivix"),
            "nadia@example.com",
        )

    def test_returns_none_for_an_unlinked_conversation(self):
        """
        The normal state before a visitor gives an email. There is no
        identity to recover, and inventing one would be worse than
        starting fresh.
        """
        self.assertIsNone(self.links.email_for_conversation("conv-unknown", "kaivix"))

    def test_never_crosses_businesses(self):
        self.links.link("nadia@example.com", "conv-1", business_id="kaivix")

        self.assertIsNone(
            self.links.email_for_conversation("conv-1", business_id="other-business")
        )


class TestEngineRecoversIdentityAfterRestart(_IsolatedDatabasesMixin, unittest.TestCase):
    def setUp(self):
        self._isolate_databases()

    def _engine(self, llm_response="Sure."):
        from core_ai.conversation_engine import ConversationEngine

        engine = ConversationEngine()
        engine.llm = MagicMock()
        engine.llm.generate.return_value = llm_response
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.is_connected.return_value = False
        engine.email_provider = MagicMock()
        engine.email_provider.is_connected.return_value = False
        return engine

    def test_a_brand_new_engine_recovers_the_visitor_it_never_met(self):
        """
        The exact production scenario: turn one on one process, the rest
        on another. The SECOND engine is a genuinely fresh object with
        an empty _lead_profiles, standing in for the post-deploy process.
        """
        first = self._engine()
        first.process_message(
            "conv-restart",
            "Hi, I am Pat Persistence from Persistence Dental Group, "
            "my email is pat@example.com. Our timeline is next quarter.",
        )

        captured = first._lead_profiles["conv-restart"]
        self.assertEqual(captured.email, "pat@example.com")

        # --- process restarts here ---
        second = self._engine()
        self.assertEqual(second._lead_profiles, {})

        recovered = second._update_lead_profile("conv-restart", "1")

        self.assertEqual(recovered.email, "pat@example.com")
        self.assertEqual(recovered.name, "Pat Persistence")
        self.assertEqual(recovered.timeline, "next quarter")

    def test_an_unknown_conversation_still_starts_clean(self):
        engine = self._engine()
        lead = engine._get_lead("conv-never-seen")

        self.assertEqual(lead.email, "")
        self.assertEqual(lead.name, "")

    def test_a_lookup_failure_never_drops_the_turn(self):
        engine = self._engine()
        engine.lead_conversation_links = MagicMock()
        engine.lead_conversation_links.email_for_conversation.side_effect = RuntimeError(
            "store unavailable"
        )

        lead = engine._get_lead("conv-x")

        self.assertEqual(lead.email, "")


class TestTheInvitePromiseMatchesReality(unittest.TestCase):
    """
    Google notifies attendees and nothing else, so an event created with
    none means nobody was told. Bray promised an invite anyway.
    """

    def _prompt(self, plan):
        return PromptBuilder().build(
            stage="closing", intent="buying_signal", goal="book_meeting",
            knowledge="", plan=plan,
        )

    def test_promises_the_invite_only_when_there_was_an_attendee(self):
        prompt = self._prompt(
            ConversationPlan(
                booking_confirmation="Monday 9:00 AM - 9:30 AM",
                booking_invite_sent_to="pat@example.com",
            )
        )

        self.assertIn("genuinely been sent to pat@example.com", prompt)

    def test_forbids_the_invite_claim_when_nobody_was_invited(self):
        prompt = self._prompt(
            ConversationPlan(
                booking_confirmation="Monday 9:00 AM - 9:30 AM",
                booking_invite_sent_to="",
            )
        )

        self.assertIn("No calendar invitation was sent", prompt)
        self.assertIn("Do NOT say an invite is coming", prompt)


class TestEventTitleIsNeverMalformed(_IsolatedDatabasesMixin, unittest.TestCase):
    def setUp(self):
        self._isolate_databases()

    def _resolve_with(self, lead):
        from core_ai.conversation_engine import ConversationEngine
        from core_ai.working_memory import WorkingMemory

        engine = ConversationEngine()
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.create_event.return_value = {
            "success": True, "event_link": "x", "error": None
        }

        from datetime import datetime, timedelta

        start = datetime(2026, 9, 14, 9, 0)
        engine._offered_slot_windows["conv-1"] = [(start, start + timedelta(minutes=30))]

        wm = WorkingMemory()
        wm.set_offered_slots(["Monday 9:00 AM - 9:30 AM"])

        engine._maybe_resolve_booking("conv-1", "1", lead, wm)
        return engine.calendar_provider.create_event.call_args.kwargs["summary"]

    def test_named_lead_gets_a_named_title(self):
        summary = self._resolve_with(LeadProfile(name="Pat", email="pat@example.com"))
        self.assertEqual(summary, "Kaivix Demo Call - Pat")

    def test_empty_lead_does_not_produce_a_trailing_dash(self):
        """A real calendar really did receive "Kaivix Demo Call - "."""
        summary = self._resolve_with(LeadProfile())
        self.assertEqual(summary, "Kaivix Demo Call")


if __name__ == "__main__":
    unittest.main()
