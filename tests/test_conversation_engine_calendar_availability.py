import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import crm.database as crm_database
import memory.conversation_store as conversation_store_module
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine
from core_ai.conversation_plan import ConversationPlan
from core_ai.working_memory import WorkingMemory
from scheduling.google_calendar_provider import GoogleCalendarProvider

UTC = ZoneInfo("UTC")


class _IsolatedDatabasesMixin:
    """Same isolation pattern as
    tests/test_conversation_engine_business_config.py -- points crm/CRM
    and LongTermMemory at fresh temp files so constructing a real
    ConversationEngine never touches crm/leads.db or
    memory/long_term_memory.db."""

    def _isolate_databases(self):
        # All THREE stores a real ConversationEngine writes to, not just
        # the first two. Isolating only CRM and long-term memory left
        # memory/conversation_memory.db pointed at the real file, so every
        # process_message() turn in this file wrote real rows into it --
        # invisible here because nothing in this file asserts on stored
        # conversation history. Matches the complete pattern
        # tests/test_multi_business_serving.py already uses.
        fd, crm_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(crm_db_path)

        fd, ltm_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(ltm_db_path)

        fd, conv_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(conv_db_path)

        original_crm_db_name = crm_database.DATABASE_NAME
        original_ltm_db_path = ltm_module.SQLiteLongTermMemoryStore.DB_PATH
        original_conv_db_path = conversation_store_module.SQLiteConversationStore.DB_PATH

        crm_database.DATABASE_NAME = crm_db_path
        ltm_module.SQLiteLongTermMemoryStore.DB_PATH = ltm_db_path
        conversation_store_module.SQLiteConversationStore.DB_PATH = conv_db_path

        def _restore():
            crm_database.DATABASE_NAME = original_crm_db_name
            ltm_module.SQLiteLongTermMemoryStore.DB_PATH = original_ltm_db_path
            conversation_store_module.SQLiteConversationStore.DB_PATH = original_conv_db_path
            for path in (crm_db_path, ltm_db_path, conv_db_path):
                if os.path.exists(path):
                    os.remove(path)

        self.addCleanup(_restore)


class TestMaybeAttachAvailability(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Unit tests for ConversationEngine._maybe_attach_availability, called
    directly (not through a full process_message() turn) so each
    strategy/is_connected combination can be tested precisely and in
    isolation.
    """

    _WINDOWS = [
        (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
        (datetime(2026, 3, 11, 10, 0, tzinfo=UTC), datetime(2026, 3, 11, 11, 0, tzinfo=UTC)),
    ]

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        # Replaced post-construction, the same pattern
        # test_conversation_engine_business_config.py uses for engine.llm
        # -- avoids ever touching the real scheduling/calendar_tokens.db.
        self.engine.calendar_provider = MagicMock()
        self.engine.calendar_provider.format_slot.side_effect = GoogleCalendarProvider.format_slot
        self.working_memory = WorkingMemory()

    def test_fires_when_strategy_is_drive_to_booking_and_connected(self):
        self.engine.calendar_provider.is_connected.return_value = True
        self.engine.calendar_provider.get_free_busy_windows.return_value = self._WINDOWS

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan, self.working_memory)

        self.assertEqual(
            result.available_slots,
            ["Tuesday 2:00 PM - 3:00 PM", "Wednesday 10:00 AM - 11:00 AM"],
        )
        self.engine.calendar_provider.get_free_busy_windows.assert_called_once_with(
            self.engine.business_id
        )

        # The original plan object must not be mutated.
        self.assertEqual(plan.available_slots, [])
        self.assertIsNot(result, plan)

        # The exact same display strings are remembered onto
        # working_memory, and the structured windows cached for later
        # booking resolution -- see _maybe_resolve_booking.
        self.assertEqual(
            self.working_memory.offered_slots,
            ["Tuesday 2:00 PM - 3:00 PM", "Wednesday 10:00 AM - 11:00 AM"],
        )
        self.assertEqual(self.engine._offered_slot_windows["conv-1"], self._WINDOWS)

    def test_skipped_when_strategy_is_not_drive_to_booking(self):
        self.engine.calendar_provider.is_connected.return_value = True

        plan = ConversationPlan(strategy="continue_discovery")
        result = self.engine._maybe_attach_availability("conv-1", plan, self.working_memory)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.calendar_provider.is_connected.assert_not_called()
        self.engine.calendar_provider.get_free_busy_windows.assert_not_called()
        self.assertEqual(self.working_memory.offered_slots, [])

    def test_skipped_when_strategy_matches_but_not_connected(self):
        self.engine.calendar_provider.is_connected.return_value = False

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan, self.working_memory)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.calendar_provider.is_connected.assert_called_once_with(
            self.engine.business_id
        )
        self.engine.calendar_provider.get_free_busy_windows.assert_not_called()
        self.assertEqual(self.working_memory.offered_slots, [])

    def test_not_connected_logs_a_warning(self):
        """
        The unlogged root cause of the false-booking-confirmation gap:
        is_connected() returning False used to leave zero trace anywhere.
        Must log at WARNING, not INFO -- by this point
        _calendar_booking_enabled() has already confirmed this business
        wants the feature on, so a missing connection here means a real
        visitor mid-booking-flow is getting no real slots, not merely
        "no calendar configured yet."
        """
        self.engine.calendar_provider.is_connected.return_value = False
        self.engine.logger = MagicMock()

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan, self.working_memory)

        self.assertIs(result, plan)
        self.engine.logger.warning.assert_called_once()
        logged_message = self.engine.logger.warning.call_args[0][0]
        self.assertIn(self.engine.business_id, logged_message)
        self.assertIn("conv-1", logged_message)
        self.engine.logger.error.assert_not_called()

    def test_calendar_exception_is_caught_and_logged_not_raised(self):
        self.engine.calendar_provider.is_connected.return_value = True
        self.engine.calendar_provider.get_free_busy_windows.side_effect = RuntimeError(
            "Google API exploded"
        )
        self.engine.logger = MagicMock()

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan, self.working_memory)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.logger.error.assert_called_once()
        self.assertIn("conv-1", self.engine.logger.error.call_args[0][0])
        self.assertEqual(self.working_memory.offered_slots, [])

    def test_is_connected_exception_is_also_caught(self):
        self.engine.calendar_provider.is_connected.side_effect = RuntimeError("boom")
        self.engine.logger = MagicMock()

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan, self.working_memory)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.logger.error.assert_called_once()


class TestMaybeAttachAvailabilityWithinFullTurn(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    A full process_message() turn never raises even when the calendar
    provider is broken -- proves the try/except in
    _maybe_attach_availability actually protects the real pipeline, not
    just the unit under direct test above.
    """

    def setUp(self):
        self._isolate_databases()

    def test_process_message_completes_even_if_calendar_provider_raises(self):
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "stubbed-response"
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.is_connected.side_effect = RuntimeError(
            "calendar provider is completely broken"
        )

        # Doesn't matter whether this particular message actually reaches
        # strategy="drive_to_booking" -- the point is process_message()
        # must never raise regardless, and if it does reach that branch,
        # the broken calendar_provider must not break the turn.
        response = engine.process_message("conv-availability-1", "Hello there")
        self.assertEqual(response, "stubbed-response")


if __name__ == "__main__":
    unittest.main()
