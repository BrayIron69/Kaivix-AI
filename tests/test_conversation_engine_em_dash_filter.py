import os
import tempfile
import unittest

import crm.database as crm_database
import memory.conversation_store as conversation_store_module
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine


class _IsolatedDatabasesMixin:
    """Same isolation pattern as tests/test_conversation_engine_unbacked_actions.py."""

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


class TestConversationEngineStripsEmDashesFromRealTurn(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Proves the filter is actually wired into process_message(), not just
    unit-tested in isolation: an LLM response containing an em dash
    never reaches the caller or conversation memory, regardless of what
    ENGINE_RULES rule #14 asked the model to do.
    """

    def setUp(self):
        self._isolate_databases()

    def test_em_dash_in_llm_response_is_stripped_before_returning(self):
        engine = ConversationEngine()
        engine.llm.generate = (
            lambda messages: "We build custom AI agents — trained on your business."
        )

        response = engine.process_message("conv-emdash-1", "what do you do?")

        self.assertNotIn("—", response)
        self.assertEqual(response, "We build custom AI agents. Trained on your business.")

    def test_em_dash_is_also_stripped_in_stored_conversation_history(self):
        engine = ConversationEngine()
        engine.llm.generate = (
            lambda messages: "Bray — our AI sales agent — is available 24/7."
        )

        conversation_id = "conv-emdash-2"
        response = engine.process_message(conversation_id, "who am I talking to?")

        history = engine.memory.get_conversation(conversation_id)
        assistant_messages = [m["content"] for m in history if m["role"] == "assistant"]

        # get_conversation() reads from the real, process-persistent
        # ConversationMemory store (not isolated per test, unlike CRM/
        # LTM above -- see _IsolatedDatabasesMixin), so membership is
        # the right check here, not an exact count: a prior run against
        # the same conversation_id could otherwise leave extra rows
        # behind and fail this test for a reason that has nothing to do
        # with em dashes. Same pattern
        # tests/test_conversation_engine_unbacked_actions.py uses.
        self.assertIn(response, assistant_messages)
        for message in assistant_messages:
            self.assertNotIn("—", message)

    def test_response_with_no_em_dash_passes_through_unchanged(self):
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "We build custom AI agents for support."

        response = engine.process_message("conv-emdash-3", "what do you do?")

        self.assertEqual(response, "We build custom AI agents for support.")


if __name__ == "__main__":
    unittest.main()
