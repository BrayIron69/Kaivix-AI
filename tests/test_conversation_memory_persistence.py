import os
import tempfile
import unittest

from core_ai.conversation_engine import ConversationEngine
from memory.conversation_memory import ConversationMemory
from memory.conversation_store import SQLiteConversationStore


class TestConversationMemoryPersistence(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_conversation_survives_new_instance_against_same_store(self):
        # First "process": write messages via one ConversationMemory
        # instance backed by a store pointed at a real db file.
        store = SQLiteConversationStore(db_path=self.db_path)
        memory = ConversationMemory(store=store)
        memory.add_user_message("conv-1", "Hi, tell me about your pricing.")
        memory.add_assistant_message("conv-1", "Happy to walk you through it.")

        # Simulate a process restart: a brand new ConversationMemory
        # instance, with a brand new store instance, pointed at the
        # same db file -- nothing shared in Python process memory.
        restarted_store = SQLiteConversationStore(db_path=self.db_path)
        restarted_memory = ConversationMemory(store=restarted_store)

        history = restarted_memory.get_conversation("conv-1")
        self.assertEqual(
            history,
            [
                {"role": "user", "content": "Hi, tell me about your pricing."},
                {"role": "assistant", "content": "Happy to walk you through it."},
            ],
        )

    def test_business_id_isolation_on_shared_conversation_id(self):
        store = SQLiteConversationStore(db_path=self.db_path)
        memory_a = ConversationMemory(business_id="business-a", store=store)
        memory_b = ConversationMemory(business_id="business-b", store=store)

        memory_a.add_user_message("conv-shared", "Message from business A")
        memory_b.add_user_message("conv-shared", "Message from business B")

        history_a = memory_a.get_conversation("conv-shared")
        history_b = memory_b.get_conversation("conv-shared")

        self.assertEqual(len(history_a), 1)
        self.assertEqual(history_a[0]["content"], "Message from business A")

        self.assertEqual(len(history_b), 1)
        self.assertEqual(history_b[0]["content"], "Message from business B")

    def test_clear_removes_persisted_messages_not_just_in_memory_copy(self):
        store = SQLiteConversationStore(db_path=self.db_path)
        memory = ConversationMemory(store=store)
        memory.add_user_message("conv-1", "Hello")
        memory.clear("conv-1")

        # Re-check through a brand new instance/store pointed at the
        # same db file, so a stale in-memory copy can't mask a bug.
        reloaded_store = SQLiteConversationStore(db_path=self.db_path)
        reloaded_memory = ConversationMemory(store=reloaded_store)
        self.assertEqual(reloaded_memory.get_conversation("conv-1"), [])

    def test_conversation_engine_constructs_without_error(self):
        # Smoke test: ConversationEngine's single ConversationMemory
        # construction site (business_id=self.business_id) still wires
        # up cleanly with no other changes required.
        engine = ConversationEngine()
        self.assertEqual(engine.memory.business_id, engine.business_id)


if __name__ == "__main__":
    unittest.main()
