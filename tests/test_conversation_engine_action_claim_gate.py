import os
import tempfile
import unittest
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine


class _IsolatedDatabasesMixin:
    """Same isolation pattern as tests/test_conversation_engine_booking.py
    -- points crm/CRM and LongTermMemory at fresh temp files so
    constructing a real ConversationEngine never touches crm/leads.db or
    memory/long_term_memory.db."""

    def _isolate_databases(self):
        fd, crm_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(crm_db_path)

        fd, ltm_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(ltm_db_path)

        original_crm_db_name = crm_database.DATABASE_NAME
        original_ltm_db_path = ltm_module.SQLiteLongTermMemoryStore.DB_PATH

        crm_database.DATABASE_NAME = crm_db_path
        ltm_module.SQLiteLongTermMemoryStore.DB_PATH = ltm_db_path

        def _restore():
            crm_database.DATABASE_NAME = original_crm_db_name
            ltm_module.SQLiteLongTermMemoryStore.DB_PATH = original_ltm_db_path
            for path in (crm_db_path, ltm_db_path):
                if os.path.exists(path):
                    os.remove(path)

        self.addCleanup(_restore)


class TestActionClaimGateWithinFullTurn(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Proves the deterministic gate (core_ai/action_claim_gate.py) is
    actually wired into process_message(), not just unit-tested in
    isolation: an LLM response containing an unbacked action claim never
    reaches the caller, regardless of what ENGINE_RULES asked the model
    to do. Stubs engine.llm.generate the same way
    test_conversation_engine_booking.py does -- no real LLM call.
    """

    def setUp(self):
        self._isolate_databases()

    def test_fabricated_email_claim_is_replaced_before_returning(self):
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "No problem! I've sent you an email with the checklist."
        engine.logger = MagicMock()

        response = engine.process_message("conv-gate-email", "can you email me a checklist?")

        self.assertNotIn("sent you an email", response.lower())
        self.assertIn("calendly.com", response)
        gate_warnings = [
            call for call in engine.logger.warning.call_args_list
            if "[ActionClaimGate]" in call.args[0]
        ]
        self.assertEqual(len(gate_warnings), 1)
        self.assertIn("email", gate_warnings[0].args[0])

    def test_fabricated_human_handoff_claim_is_replaced_before_returning(self):
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "I've forwarded this to our team, they'll reach out shortly."
        engine.logger = MagicMock()

        response = engine.process_message("conv-gate-handoff", "can someone call me back?")

        self.assertNotIn("forwarded", response.lower())
        gate_warnings = [
            call for call in engine.logger.warning.call_args_list
            if "[ActionClaimGate]" in call.args[0]
        ]
        self.assertEqual(len(gate_warnings), 1)
        self.assertIn("human_handoff", gate_warnings[0].args[0])

    def test_ordinary_response_passes_through_unchanged(self):
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "We build custom AI agents for support and lead qualification."
        engine.logger = MagicMock()

        response = engine.process_message("conv-gate-clean", "what do you do?")

        self.assertEqual(response, "We build custom AI agents for support and lead qualification.")
        engine.logger.warning.assert_not_called()

    def test_real_booking_confirmation_text_is_not_gated(self):
        # Sanity check against a false positive: a genuine booking
        # confirmation (the kind PromptBuilder's BOOKING CONFIRMED
        # section asks the model to produce) must reach the visitor
        # unmodified, since it IS backed by a real calendar event.
        engine = ConversationEngine()
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.create_event.return_value = {
            "success": True,
            "event_link": "https://calendar.google.com/event?eid=abc123",
            "error": None,
        }
        engine.llm.generate = (
            lambda messages: "You're all booked for Wednesday 10:00 AM - 11:00 AM! "
            "You'll get a calendar invite in your email shortly."
        )
        engine.logger = MagicMock()

        conversation_id = "conv-gate-real-booking"
        working_memory = engine.memory_manager.get_working_memory(conversation_id)
        working_memory.set_offered_slots(["Wednesday 10:00 AM - 11:00 AM"])
        from datetime import datetime
        from zoneinfo import ZoneInfo

        UTC = ZoneInfo("UTC")
        engine._offered_slot_windows[conversation_id] = [
            (datetime(2026, 3, 11, 10, 0, tzinfo=UTC), datetime(2026, 3, 11, 11, 0, tzinfo=UTC)),
        ]

        response = engine.process_message(conversation_id, "1")

        self.assertIn("You're all booked", response)
        engine.logger.warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
