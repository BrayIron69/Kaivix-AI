import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine
from core_ai.lead_profile import LeadProfile
from core_ai.working_memory import WorkingMemory

UTC = ZoneInfo("UTC")


class _IsolatedDatabasesMixin:
    """Same isolation pattern as
    tests/test_conversation_engine_business_config.py -- points crm/CRM
    and LongTermMemory at fresh temp files so constructing a real
    ConversationEngine never touches crm/leads.db or
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


class TestMaybeResolveBooking(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Unit tests for ConversationEngine._maybe_resolve_booking, called
    directly (not through a full process_message() turn) so each
    match/success/failure combination can be tested precisely and in
    isolation. NEVER calls the real Google Calendar API -- calendar_provider
    is always a MagicMock here.
    """

    _OFFERED_SLOTS = ["Tuesday 2:00 PM - 3:00 PM", "Wednesday 10:00 AM - 11:00 AM"]
    _WINDOWS = [
        (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
        (datetime(2026, 3, 11, 10, 0, tzinfo=UTC), datetime(2026, 3, 11, 11, 0, tzinfo=UTC)),
    ]

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.calendar_provider = MagicMock()
        self.working_memory = WorkingMemory()
        self.lead = LeadProfile(name="Alice", email="alice@example.com")

    def _seed_offered_slots(self, conversation_id="conv-1"):
        self.working_memory.set_offered_slots(self._OFFERED_SLOTS)
        self.engine._offered_slot_windows[conversation_id] = list(self._WINDOWS)

    def test_matched_and_success_sets_confirmation_and_clears_offered_slots(self):
        self._seed_offered_slots()
        self.engine.calendar_provider.create_event.return_value = {
            "success": True,
            "event_link": "https://calendar.google.com/event?eid=abc123",
            "error": None,
        }

        result = self.engine._maybe_resolve_booking(
            "conv-1", "2", self.lead, self.working_memory
        )

        self.assertEqual(result, {"confirmation": "Wednesday 10:00 AM - 11:00 AM", "failed": False})
        self.assertEqual(self.working_memory.offered_slots, [])
        self.assertNotIn("conv-1", self.engine._offered_slot_windows)

        _args, kwargs = self.engine.calendar_provider.create_event.call_args
        self.assertEqual(kwargs["start_time"], self._WINDOWS[1][0])
        self.assertEqual(kwargs["end_time"], self._WINDOWS[1][1])
        self.assertEqual(kwargs["attendee_email"], "alice@example.com")

    def test_matched_and_failure_sets_failed_and_clears_offered_slots(self):
        self._seed_offered_slots()
        self.engine.calendar_provider.create_event.return_value = {
            "success": False,
            "event_link": None,
            "error": "insufficient permissions",
        }
        self.engine.logger = MagicMock()

        result = self.engine._maybe_resolve_booking(
            "conv-1", "1", self.lead, self.working_memory
        )

        self.assertEqual(result, {"confirmation": "", "failed": True})
        self.assertEqual(self.working_memory.offered_slots, [])
        self.assertNotIn("conv-1", self.engine._offered_slot_windows)
        self.engine.logger.error.assert_called_once()

    def test_no_match_leaves_offered_slots_untouched_and_returns_none(self):
        self._seed_offered_slots()

        result = self.engine._maybe_resolve_booking(
            "conv-1", "what's the weather like", self.lead, self.working_memory
        )

        self.assertIsNone(result)
        self.assertEqual(self.working_memory.offered_slots, self._OFFERED_SLOTS)
        self.assertEqual(self.engine._offered_slot_windows["conv-1"], self._WINDOWS)
        self.engine.calendar_provider.create_event.assert_not_called()

    def test_no_offered_slots_returns_none_immediately(self):
        # working_memory.offered_slots was never seeded -- default [].
        result = self.engine._maybe_resolve_booking(
            "conv-1", "2", self.lead, self.working_memory
        )

        self.assertIsNone(result)
        self.engine.calendar_provider.create_event.assert_not_called()

    def test_calendar_exception_is_caught_and_logged_not_raised(self):
        self._seed_offered_slots()
        self.engine.calendar_provider.create_event.side_effect = RuntimeError(
            "Google Calendar API exploded"
        )
        self.engine.logger = MagicMock()

        result = self.engine._maybe_resolve_booking(
            "conv-1", "1", self.lead, self.working_memory
        )

        self.assertIsNone(result)
        self.engine.logger.error.assert_called_once()
        self.assertIn("conv-1", self.engine.logger.error.call_args[0][0])


class TestMaybeResolveBookingWithinFullTurn(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Full process_message() turns proving: a matched reply produces a
    booking_confirmation that reaches the assembled system prompt (and
    _maybe_attach_availability is skipped that same turn), and a broken
    calendar_provider never breaks the turn. NEVER calls the real Google
    Calendar API.
    """

    def setUp(self):
        self._isolate_databases()

    def test_matched_reply_produces_booking_confirmation_in_prompt(self):
        engine = ConversationEngine()
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.create_event.return_value = {
            "success": True,
            "event_link": "https://calendar.google.com/event?eid=abc123",
            "error": None,
        }

        conversation_id = "conv-booking-1"
        working_memory = engine.memory_manager.get_working_memory(conversation_id)
        working_memory.set_offered_slots(
            ["Tuesday 2:00 PM - 3:00 PM", "Wednesday 10:00 AM - 11:00 AM"]
        )
        engine._offered_slot_windows[conversation_id] = [
            (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
            (datetime(2026, 3, 11, 10, 0, tzinfo=UTC), datetime(2026, 3, 11, 11, 0, tzinfo=UTC)),
        ]

        captured = {}

        def fake_generate(messages):
            captured["system_prompt"] = messages[0]["content"]
            return "stubbed-response"

        engine.llm.generate = fake_generate

        response = engine.process_message(conversation_id, "2")

        self.assertEqual(response, "stubbed-response")
        self.assertIn("BOOKING CONFIRMED", captured["system_prompt"])
        self.assertIn("Wednesday 10:00 AM - 11:00 AM", captured["system_prompt"])
        self.assertNotIn("REAL AVAILABLE TIMES", captured["system_prompt"])
        self.assertEqual(working_memory.offered_slots, [])

    def test_matched_reply_with_failed_booking_produces_fallback_in_prompt(self):
        engine = ConversationEngine()
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.create_event.return_value = {
            "success": False,
            "event_link": None,
            "error": "calendar API rejected the request",
        }

        conversation_id = "conv-booking-2"
        working_memory = engine.memory_manager.get_working_memory(conversation_id)
        working_memory.set_offered_slots(["Tuesday 2:00 PM - 3:00 PM"])
        engine._offered_slot_windows[conversation_id] = [
            (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
        ]

        captured = {}

        def fake_generate(messages):
            captured["system_prompt"] = messages[0]["content"]
            return "stubbed-response"

        engine.llm.generate = fake_generate

        response = engine.process_message(conversation_id, "1")

        self.assertEqual(response, "stubbed-response")
        self.assertIn("BOOKING SYSTEM ERROR", captured["system_prompt"])
        self.assertEqual(working_memory.offered_slots, [])

    def test_process_message_completes_even_if_create_event_raises(self):
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "stubbed-response"
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.create_event.side_effect = RuntimeError(
            "calendar provider is completely broken"
        )

        conversation_id = "conv-booking-3"
        working_memory = engine.memory_manager.get_working_memory(conversation_id)
        working_memory.set_offered_slots(["Tuesday 2:00 PM - 3:00 PM"])
        engine._offered_slot_windows[conversation_id] = [
            (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
        ]

        response = engine.process_message(conversation_id, "1")
        self.assertEqual(response, "stubbed-response")


if __name__ == "__main__":
    unittest.main()
