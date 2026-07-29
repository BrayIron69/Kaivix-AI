"""
BusinessConfig.tools.enabled_tools gating for calendar booking
(ConversationEngine._calendar_booking_enabled).

enabled_tools was loaded by BusinessConfigRepository and then never
read: booking was gated purely on whether a Google Calendar happened to
be OAuth-connected, so the config list had no effect on behavior and a
business could not switch the feature off short of disconnecting its
calendar. These tests pin the gate on both booking entry points.

Never touches the real Google Calendar API -- calendar_provider is
always a MagicMock.
"""

import os
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine
from core_ai.conversation_plan import ConversationPlan
from core_ai.lead_profile import LeadProfile
from core_ai.working_memory import WorkingMemory

UTC = ZoneInfo("UTC")


class _IsolatedDatabasesMixin:
    """Same isolation pattern as tests/test_conversation_engine_booking.py."""

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


class _BookingEngineMixin(_IsolatedDatabasesMixin):
    _OFFERED_SLOTS = ["Tuesday 2:00 PM - 3:00 PM", "Wednesday 10:00 AM - 11:00 AM"]
    _WINDOWS = [
        (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
        (datetime(2026, 3, 11, 10, 0, tzinfo=UTC), datetime(2026, 3, 11, 11, 0, tzinfo=UTC)),
    ]

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.calendar_provider = MagicMock()
        self.engine.calendar_provider.is_connected.return_value = True
        self.engine.calendar_provider.get_free_busy_windows.return_value = list(
            self._WINDOWS
        )
        self.engine.calendar_provider.format_slot.side_effect = self._OFFERED_SLOTS
        self.engine.calendar_provider.create_event.return_value = {
            "success": True,
            "event_link": "https://calendar.google.com/event?eid=abc123",
            "error": None,
        }

        self.working_memory = WorkingMemory()
        self.lead = LeadProfile(name="Alice", email="alice@example.com")
        self.plan = ConversationPlan(strategy="drive_to_booking")

    def _set_enabled_tools(self, tools):
        self.engine.business_config = SimpleNamespace(
            tools=SimpleNamespace(enabled_tools=tools)
        )

    def _seed_offered_slots(self, conversation_id="conv-1"):
        self.working_memory.set_offered_slots(self._OFFERED_SLOTS)
        self.engine._offered_slot_windows[conversation_id] = list(self._WINDOWS)


class TestCalendarBookingEnabledFlag(_BookingEngineMixin, unittest.TestCase):
    def test_kaivix_real_config_has_calendar_booking_enabled(self):
        """
        Kaivix's own tools.yaml must list calendar_booking, or wiring the
        gate would silently switch off working production behavior.
        """
        self.assertIn(
            "calendar_booking",
            self.engine.business_config.tools.enabled_tools,
        )
        self.assertTrue(self.engine._calendar_booking_enabled())

    def test_empty_enabled_tools_disables_booking(self):
        self._set_enabled_tools([])
        self.assertFalse(self.engine._calendar_booking_enabled())

    def test_unrelated_tools_do_not_enable_booking(self):
        self._set_enabled_tools(["crm_sync", "email_followup"])
        self.assertFalse(self.engine._calendar_booking_enabled())

    def test_missing_tools_section_fails_closed(self):
        self.engine.business_config = SimpleNamespace()
        self.assertFalse(self.engine._calendar_booking_enabled())

    def test_null_enabled_tools_fails_closed(self):
        self._set_enabled_tools(None)
        self.assertFalse(self.engine._calendar_booking_enabled())


class TestAvailabilityGatedByEnabledTools(_BookingEngineMixin, unittest.TestCase):
    def test_disabled_tool_attaches_no_availability(self):
        self._set_enabled_tools([])

        result = self.engine._maybe_attach_availability(
            "conv-1", self.plan, self.working_memory
        )

        self.assertEqual(result.available_slots, [])
        self.assertEqual(self.working_memory.offered_slots, [])

    def test_disabled_tool_never_calls_the_calendar(self):
        """
        The config gate runs before is_connected, so a business with
        booking off does no calendar I/O at all.
        """
        self._set_enabled_tools([])

        self.engine._maybe_attach_availability(
            "conv-1", self.plan, self.working_memory
        )

        self.engine.calendar_provider.is_connected.assert_not_called()
        self.engine.calendar_provider.get_free_busy_windows.assert_not_called()

    def test_enabled_tool_still_attaches_availability(self):
        self._set_enabled_tools(["calendar_booking"])

        result = self.engine._maybe_attach_availability(
            "conv-1", self.plan, self.working_memory
        )

        self.assertEqual(result.available_slots, self._OFFERED_SLOTS)
        self.assertEqual(self.working_memory.offered_slots, self._OFFERED_SLOTS)
        self.engine.calendar_provider.get_free_busy_windows.assert_called_once()


class TestBookingResolutionGatedByEnabledTools(_BookingEngineMixin, unittest.TestCase):
    def test_disabled_tool_creates_no_event_even_with_slots_already_offered(self):
        """
        The dangerous case: slots were offered while the tool was on, and
        it was switched off before the visitor replied. A disabled tool
        must not produce a real calendar event.
        """
        self._seed_offered_slots()
        self._set_enabled_tools([])

        result = self.engine._maybe_resolve_booking(
            "conv-1", "2", self.lead, self.working_memory
        )

        self.assertIsNone(result)
        self.engine.calendar_provider.create_event.assert_not_called()

    def test_disabled_tool_leaves_offered_slots_untouched(self):
        self._seed_offered_slots()
        self._set_enabled_tools([])

        self.engine._maybe_resolve_booking(
            "conv-1", "2", self.lead, self.working_memory
        )

        self.assertEqual(self.working_memory.offered_slots, self._OFFERED_SLOTS)

    def test_enabled_tool_still_books(self):
        self._seed_offered_slots()
        self._set_enabled_tools(["calendar_booking"])

        result = self.engine._maybe_resolve_booking(
            "conv-1", "2", self.lead, self.working_memory
        )

        self.assertEqual(
            result,
            {"confirmation": "Wednesday 10:00 AM - 11:00 AM", "failed": False},
        )
        self.engine.calendar_provider.create_event.assert_called_once()


if __name__ == "__main__":
    unittest.main()
