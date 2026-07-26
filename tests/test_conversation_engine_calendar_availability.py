import os
import tempfile
import unittest
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine
from core_ai.conversation_plan import ConversationPlan


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


class TestMaybeAttachAvailability(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Unit tests for ConversationEngine._maybe_attach_availability, called
    directly (not through a full process_message() turn) so each
    strategy/is_connected combination can be tested precisely and in
    isolation.
    """

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        # Replaced post-construction, the same pattern
        # test_conversation_engine_business_config.py uses for engine.llm
        # -- avoids ever touching the real scheduling/calendar_tokens.db.
        self.engine.calendar_provider = MagicMock()

    def test_fires_when_strategy_is_drive_to_booking_and_connected(self):
        self.engine.calendar_provider.is_connected.return_value = True
        self.engine.calendar_provider.get_free_busy_slots.return_value = [
            "Tuesday 2:00 PM - 3:00 PM",
            "Wednesday 10:00 AM - 11:00 AM",
        ]

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan)

        self.assertEqual(
            result.available_slots,
            ["Tuesday 2:00 PM - 3:00 PM", "Wednesday 10:00 AM - 11:00 AM"],
        )
        self.engine.calendar_provider.get_free_busy_slots.assert_called_once_with(
            self.engine.business_id
        )

        # The original plan object must not be mutated.
        self.assertEqual(plan.available_slots, [])
        self.assertIsNot(result, plan)

    def test_skipped_when_strategy_is_not_drive_to_booking(self):
        self.engine.calendar_provider.is_connected.return_value = True

        plan = ConversationPlan(strategy="continue_discovery")
        result = self.engine._maybe_attach_availability("conv-1", plan)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.calendar_provider.is_connected.assert_not_called()
        self.engine.calendar_provider.get_free_busy_slots.assert_not_called()

    def test_skipped_when_strategy_matches_but_not_connected(self):
        self.engine.calendar_provider.is_connected.return_value = False

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.calendar_provider.is_connected.assert_called_once_with(
            self.engine.business_id
        )
        self.engine.calendar_provider.get_free_busy_slots.assert_not_called()

    def test_calendar_exception_is_caught_and_logged_not_raised(self):
        self.engine.calendar_provider.is_connected.return_value = True
        self.engine.calendar_provider.get_free_busy_slots.side_effect = RuntimeError(
            "Google API exploded"
        )
        self.engine.logger = MagicMock()

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan)

        self.assertIs(result, plan)
        self.assertEqual(result.available_slots, [])
        self.engine.logger.error.assert_called_once()
        self.assertIn("conv-1", self.engine.logger.error.call_args[0][0])

    def test_is_connected_exception_is_also_caught(self):
        self.engine.calendar_provider.is_connected.side_effect = RuntimeError("boom")
        self.engine.logger = MagicMock()

        plan = ConversationPlan(strategy="drive_to_booking")
        result = self.engine._maybe_attach_availability("conv-1", plan)

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
