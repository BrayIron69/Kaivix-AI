import os
import tempfile
import unittest
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine
from core_ai.unbacked_action_detector import UnbackedActionCategory


class _IsolatedDatabasesMixin:
    """Same isolation pattern as tests/test_conversation_engine_calendar_availability.py."""

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


class _ForbiddenLLMCall(AssertionError):
    """Raised if the real LLM is ever invoked during these tests."""


class TestUnbackedActionShortCircuit(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Proves the gate is a real short-circuit, not prompt guidance: the
    LLM must never be called, and the returned text must be exactly the
    fixed template, for every UnbackedActionCategory.
    """

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        # Any call at all is the failure this test exists to catch --
        # rule 12 in ENGINE_RULES was a soft instruction the model
        # followed only about half the time in live production; this
        # gate's entire point is that the model doesn't get a turn.
        self.engine.llm = MagicMock()
        self.engine.llm.generate.side_effect = _ForbiddenLLMCall(
            "LLM.generate() was called -- the unbacked-action gate did "
            "not short-circuit before generation."
        )

    def test_the_exact_live_production_failure_message_is_intercepted(self):
        response = self.engine.process_message(
            "conv-unbacked-1",
            "Can you email me a checklist of everything I need to "
            "prepare before we start?",
        )

        self.engine.llm.generate.assert_not_called()
        self.assertIn("don't have a way to send", response)
        self.assertIn("calendly.com", response)
        self.assertNotIn("I can email you", response.lower())
        self.assertNotIn("i'll email", response.lower())

    def test_out_of_chat_message_response_matches_the_fixed_template(self):
        response = self.engine.process_message(
            "conv-unbacked-2", "can you text me a summary?"
        )

        expected = ConversationEngine._UNBACKED_ACTION_TEMPLATES[
            UnbackedActionCategory.OUT_OF_CHAT_MESSAGE
        ].format(booking_link=self.engine.business_config.persona.booking_link)
        self.assertEqual(response, expected)
        self.engine.llm.generate.assert_not_called()

    def test_alternate_booking_mechanism_response_matches_the_fixed_template(self):
        response = self.engine.process_message(
            "conv-unbacked-3", "can you email me the available times"
        )

        expected = ConversationEngine._UNBACKED_ACTION_TEMPLATES[
            UnbackedActionCategory.ALTERNATE_BOOKING_MECHANISM
        ].format(booking_link=self.engine.business_config.persona.booking_link)
        self.assertEqual(response, expected)
        self.engine.llm.generate.assert_not_called()

    def test_human_handoff_response_matches_the_fixed_template(self):
        response = self.engine.process_message(
            "conv-unbacked-4", "can I talk to a real person"
        )

        expected = ConversationEngine._UNBACKED_ACTION_TEMPLATES[
            UnbackedActionCategory.HUMAN_HANDOFF
        ].format(booking_link=self.engine.business_config.persona.booking_link)
        self.assertEqual(response, expected)
        self.engine.llm.generate.assert_not_called()

    def test_response_is_recorded_in_conversation_memory(self):
        response = self.engine.process_message(
            "conv-unbacked-5", "email me a checklist please"
        )

        history = self.engine.memory.get_conversation("conv-unbacked-5")
        assistant_messages = [m["content"] for m in history if m["role"] == "assistant"]
        self.assertIn(response, assistant_messages)

    def test_ordinary_message_is_not_intercepted_and_reaches_the_llm(self):
        self.engine.llm.generate.side_effect = None
        self.engine.llm.generate.return_value = "stubbed-response"

        response = self.engine.process_message(
            "conv-unbacked-6", "just tell me the price"
        )

        self.engine.llm.generate.assert_called_once()
        self.assertEqual(response, "stubbed-response")


class TestUnbackedActionTwentyRunDeterminism(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Item 4's specific ask: the exact wording from today's live
    production failure, run 20 times, all 20 honest.

    Twenty real ConversationEngine.process_message() calls, exercising
    the real detector, real prompt-adjacent pipeline code, and real
    business config -- everything except the LLM itself, which is
    replaced with a call-forbidding mock. That is deliberately a
    stronger proof than 20 live network calls to the real model would
    be: this gate's entire premise is that the response no longer
    depends on the model's behavior at all, so the rigorous claim to
    verify is "the model is structurally never consulted," not "the
    model happened to behave 20 times in a row." 20 real network calls
    could pass by chance the same way the pre-fix code already showed
    real, non-deterministic pass/fail behavior; forbidding the call
    proves it by construction instead of by sampling.
    """

    LIVE_FAILURE_MESSAGE = (
        "Can you email me a checklist of everything I need to prepare "
        "before we start?"
    )

    RUN_COUNT = 20

    def setUp(self):
        self._isolate_databases()

    def test_twenty_for_twenty_honest_responses_llm_never_consulted(self):
        responses = []

        for i in range(self.RUN_COUNT):
            engine = ConversationEngine()
            engine.llm = MagicMock()
            engine.llm.generate.side_effect = _ForbiddenLLMCall(
                f"run {i + 1}/{self.RUN_COUNT}: LLM.generate() was "
                f"called -- the gate failed to short-circuit."
            )

            response = engine.process_message(
                f"conv-twenty-{i}", self.LIVE_FAILURE_MESSAGE
            )

            engine.llm.generate.assert_not_called()
            responses.append(response)

        self.assertEqual(len(responses), self.RUN_COUNT)

        # All 20 must be byte-identical -- true determinism, not 20
        # samples that happened to agree.
        self.assertEqual(
            len(set(responses)), 1,
            "Expected all 20 responses to be identical; got "
            f"{len(set(responses))} distinct response(s).",
        )

        # None of the 20 may contain the fabricated claim from the real
        # incident, and every one must give an honest decline plus the
        # real next step.
        for i, response in enumerate(responses):
            with self.subTest(run=i + 1):
                lower = response.lower()
                self.assertNotIn("i can email you", lower)
                self.assertNotIn("i'll email", lower)
                self.assertNotIn("i've emailed", lower)
                self.assertNotIn("emailed you", lower)
                self.assertIn("don't have a way to send", lower)
                self.assertIn("calendly.com", response)


if __name__ == "__main__":
    unittest.main()
