"""
A visitor who steps away mid-booking can still pick a time.

The times offered to a visitor lived only in memory: WorkingMemory
.offered_slots for the display text and ConversationEngine
._offered_slot_windows for the real datetimes. A restart between "here
are three times" and "2" left nothing to resolve the reply against, so
the booking silently never happened. On Render's free plan the service
spins down after ~15 minutes idle, which makes a coffee break enough.

Recomputing availability instead would be wrong rather than merely
slower: "2" refers to the list the visitor was SHOWN, and a fresh lookup
minutes later can return a different set, so matching against it books a
time nobody agreed to.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.conversation_store as conversation_store_module
import memory.long_term_memory as ltm_module
from core_ai.lead_profile import LeadProfile
from core_ai.working_memory import WorkingMemory
from scheduling.offered_slot_store import (
    SQLiteOfferedSlotStore,
    deserialize_window,
    serialize_slots,
)

START = datetime(2026, 9, 14, 9, 0)
WINDOWS = [
    (START, START + timedelta(minutes=30)),
    (START + timedelta(minutes=30), START + timedelta(minutes=60)),
]
DISPLAYS = ["Monday 9:00 AM - 9:30 AM", "Monday 9:30 AM - 10:00 AM"]


def _temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    return path


class TestTheStoreItself(unittest.TestCase):
    def setUp(self):
        self.path = _temp_db()
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))
        self.store = SQLiteOfferedSlotStore(db_path=self.path)

    def test_round_trips_text_and_times_together(self):
        self.store.save("kaivix", "conv-1", serialize_slots(WINDOWS, DISPLAYS))

        loaded = self.store.load("kaivix", "conv-1")

        self.assertEqual([s["display"] for s in loaded], DISPLAYS)
        self.assertEqual(deserialize_window(loaded[0]), WINDOWS[0])
        self.assertEqual(deserialize_window(loaded[1]), WINDOWS[1])

    def test_order_is_preserved_because_the_visitor_replies_with_a_number(self):
        self.store.save("kaivix", "conv-1", serialize_slots(WINDOWS, DISPLAYS))

        loaded = self.store.load("kaivix", "conv-1")

        self.assertEqual(loaded[1]["display"], "Monday 9:30 AM - 10:00 AM")

    def test_saving_again_replaces_rather_than_appends(self):
        self.store.save("kaivix", "conv-1", serialize_slots(WINDOWS, DISPLAYS))
        self.store.save("kaivix", "conv-1", serialize_slots(WINDOWS[:1], DISPLAYS[:1]))

        self.assertEqual(len(self.store.load("kaivix", "conv-1")), 1)

    def test_empty_for_an_unknown_conversation(self):
        self.assertEqual(self.store.load("kaivix", "nope"), [])

    def test_never_crosses_businesses(self):
        self.store.save("kaivix", "conv-1", serialize_slots(WINDOWS, DISPLAYS))
        self.assertEqual(self.store.load("other", "conv-1"), [])

    def test_clear_removes_them(self):
        self.store.save("kaivix", "conv-1", serialize_slots(WINDOWS, DISPLAYS))
        self.store.clear("kaivix", "conv-1")
        self.assertEqual(self.store.load("kaivix", "conv-1"), [])

    def test_an_unreadable_time_is_reported_rather_than_guessed(self):
        self.assertIsNone(deserialize_window({"start": "not-a-date", "end": "x"}))
        self.assertIsNone(deserialize_window({}))


class _IsolatedDatabasesMixin:
    def _isolate_databases(self):
        paths = [_temp_db() for _ in range(3)]
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


class TestBookingSurvivesARestart(_IsolatedDatabasesMixin, unittest.TestCase):
    def setUp(self):
        self._isolate_databases()
        self.slot_db = _temp_db()
        self.addCleanup(lambda: os.path.exists(self.slot_db) and os.remove(self.slot_db))
        self.lead = LeadProfile(name="Rae", email="rae@example.com")

    def _engine(self):
        from core_ai.conversation_engine import ConversationEngine

        engine = ConversationEngine()
        engine.offered_slot_store = SQLiteOfferedSlotStore(db_path=self.slot_db)
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.is_connected.return_value = True
        engine.calendar_provider.get_free_busy_windows.return_value = WINDOWS
        engine.calendar_provider.format_slot.side_effect = lambda s, e: (
            DISPLAYS[0] if s == WINDOWS[0][0] else DISPLAYS[1]
        )
        engine.calendar_provider.create_event.return_value = {
            "success": True, "event_link": "http://x", "error": None
        }
        return engine

    def test_a_pick_still_books_on_a_process_that_never_offered_the_slots(self):
        """
        The whole point. Offer on one engine, pick on a brand-new one
        whose in-memory caches are empty, exactly as after a deploy or
        an idle spin-down.
        """
        from core_ai.conversation_plan import ConversationPlan

        offering = self._engine()
        wm = WorkingMemory()
        offering._maybe_attach_availability(
            "conv-restart", ConversationPlan(strategy="drive_to_booking"), wm
        )

        # --- restart ---
        booking = self._engine()
        self.assertEqual(booking._offered_slot_windows, {})

        fresh_wm = WorkingMemory()
        result = booking._maybe_resolve_booking("conv-restart", "2", self.lead, fresh_wm)

        self.assertIsNotNone(result)
        self.assertFalse(result["failed"])
        self.assertEqual(result["confirmation"], "Monday 9:30 AM - 10:00 AM")

        # And it booked the time the visitor was actually shown.
        kwargs = booking.calendar_provider.create_event.call_args.kwargs
        self.assertEqual(kwargs["start_time"], WINDOWS[1][0])
        self.assertEqual(kwargs["end_time"], WINDOWS[1][1])

    def test_the_offered_times_are_dropped_once_booked(self):
        from core_ai.conversation_plan import ConversationPlan

        engine = self._engine()
        wm = WorkingMemory()
        engine._maybe_attach_availability(
            "conv-1", ConversationPlan(strategy="drive_to_booking"), wm
        )
        engine._maybe_resolve_booking("conv-1", "1", self.lead, wm)

        self.assertEqual(engine.offered_slot_store.load("kaivix", "conv-1"), [])
        self.assertEqual(wm.offered_slots, [])

    def test_nothing_offered_means_nothing_to_resolve(self):
        engine = self._engine()
        result = engine._maybe_resolve_booking("conv-none", "1", self.lead, WorkingMemory())
        self.assertIsNone(result)

    def test_a_storage_failure_does_not_break_same_process_booking(self):
        """
        Persisting is best-effort and logged, never raised. If it fails
        on the offering turn, the in-memory pair must still carry the
        booking through within that process.
        """
        from core_ai.conversation_plan import ConversationPlan

        engine = self._engine()
        engine.offered_slot_store = MagicMock()
        engine.offered_slot_store.save.side_effect = RuntimeError("disk gone")
        engine.offered_slot_store.load.return_value = []

        wm = WorkingMemory()
        engine._maybe_attach_availability(
            "conv-1", ConversationPlan(strategy="drive_to_booking"), wm
        )
        result = engine._maybe_resolve_booking("conv-1", "1", self.lead, wm)

        self.assertIsNotNone(result)
        self.assertFalse(result["failed"])


if __name__ == "__main__":
    unittest.main()
