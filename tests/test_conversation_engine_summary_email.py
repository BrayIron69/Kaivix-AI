import os
import tempfile
import unittest
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.conversation_engine import ConversationEngine
from core_ai.unbacked_action_detector import UnbackedActionCategory


class _IsolatedDatabasesMixin:
    """Same isolation pattern as tests/test_conversation_engine_unbacked_actions.py."""

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


REQUEST_MESSAGE = "Can you email me a summary of this conversation?"


class TestConversationSummaryEmailRealDataIn(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    'Real conversation data in, real email content out': seeds a real
    LeadProfile and a real WorkingMemory with genuinely collected
    fields, then proves the exact same data reaches EmailProvider.send_email
    verbatim -- nothing invented, nothing dropped silently.
    """

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.llm = MagicMock()
        self.engine.llm.generate.side_effect = _ForbiddenLLMCall(
            "LLM.generate() was called -- the summary-email path did "
            "not short-circuit before generation."
        )
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = True
        self.engine.email_provider.send_email.return_value = {"success": True, "error": None}

    def test_real_lead_and_working_memory_fields_reach_the_real_send_call(self):
        conversation_id = "conv-summary-1"

        lead = self.engine._update_lead_profile(conversation_id, "hi, I'm Alice from Acme Co")
        lead.update(
            name="Alice",
            email="alice@acme.example.com",
            company="Acme Co",
            budget="$5k/month",
            timeline="next quarter",
            pain_points=["too many missed calls"],
            goals=["automate lead qualification"],
        )
        self.engine._lead_profiles[conversation_id] = lead

        working_memory = self.engine.memory_manager.get_working_memory(conversation_id)
        working_memory.set_conversation_summary(
            "Alice from Acme Co is exploring an AI sales agent to handle "
            "missed calls and qualify leads automatically."
        )

        response = self.engine.process_message(conversation_id, REQUEST_MESSAGE)

        self.engine.llm.generate.assert_not_called()
        self.engine.email_provider.send_email.assert_called_once()

        _args, kwargs = self.engine.email_provider.send_email.call_args
        self.assertEqual(kwargs["to"], "alice@acme.example.com")
        self.assertIn(
            "Alice from Acme Co is exploring an AI sales agent",
            kwargs["body_text"],
        )
        self.assertIn("Acme Co", kwargs["body_text"])
        self.assertIn("too many missed calls", kwargs["body_text"])
        self.assertIn("automate lead qualification", kwargs["body_text"])
        self.assertIn("$5k/month", kwargs["body_text"])
        self.assertIn("next quarter", kwargs["body_text"])

        self.assertIn("alice@acme.example.com", response)
        self.assertNotIn("i sent", response.lower())  # no fabricated-tense leak; see below

    def test_success_response_states_the_real_address_and_nothing_else(self):
        conversation_id = "conv-summary-2"
        lead = self.engine._update_lead_profile(conversation_id, "my email is bob@example.com")
        lead.update(email="bob@example.com")
        self.engine._lead_profiles[conversation_id] = lead

        response = self.engine.process_message(conversation_id, REQUEST_MESSAGE)

        self.assertIn("bob@example.com", response)
        self.assertIn("sent", response.lower())


class TestConversationSummaryEmailHonestDeclines(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Every path that isn't a real, successful send must say so honestly
    -- never claim an email went out when it didn't.
    """

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.llm = MagicMock()
        self.engine.llm.generate.side_effect = _ForbiddenLLMCall(
            "LLM.generate() was called -- the summary-email path did "
            "not short-circuit before generation."
        )

    def test_not_connected_declines_honestly_and_never_calls_send(self):
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = False

        response = self.engine.process_message("conv-summary-3", REQUEST_MESSAGE)

        self.engine.email_provider.send_email.assert_not_called()
        self.assertIn("don't have a way to send", response)
        self.assertNotIn("i've sent", response.lower())
        self.assertNotIn("i have sent", response.lower())

    def test_connected_but_no_lead_email_asks_instead_of_inventing_one(self):
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = True

        response = self.engine.process_message("conv-summary-4", REQUEST_MESSAGE)

        self.engine.email_provider.send_email.assert_not_called()
        self.assertIn("email", response.lower())
        self.assertNotIn("i've sent", response.lower())
        self.assertNotIn("i have sent", response.lower())
        self.assertNotIn("@", response)  # no address to leak -- none was ever collected

    def test_real_send_failure_apologizes_and_never_claims_success(self):
        conversation_id = "conv-summary-5"
        lead = self.engine._update_lead_profile(conversation_id, "my email is carol@example.com")
        lead.update(email="carol@example.com")
        self.engine._lead_profiles[conversation_id] = lead

        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = True
        self.engine.email_provider.send_email.return_value = {
            "success": False,
            "error": "Gmail API quota exceeded",
        }
        self.engine.logger = MagicMock()

        response = self.engine.process_message(conversation_id, REQUEST_MESSAGE)

        self.engine.email_provider.send_email.assert_called_once()
        self.assertNotIn("i've sent", response.lower())
        self.assertNotIn("i have sent", response.lower())
        self.assertIn("calendly.com", response)
        self.engine.logger.error.assert_called_once()
        logged_message = self.engine.logger.error.call_args[0][0]
        self.assertIn(conversation_id, logged_message)
        self.assertIn("Gmail API quota exceeded", logged_message)


class TestOnlyConversationSummaryEmailEverSends(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Item 4's explicit requirement: no category outside
    CONVERSATION_SUMMARY_EMAIL may ever trigger a real send, and no
    change here may widen OUT_OF_CHAT_MESSAGE / ALTERNATE_BOOKING_MECHANISM
    / HUMAN_HANDOFF to look backed. send_email is replaced with a
    call-forbidding mock so this is proven by construction, not by
    inspecting a handful of transcripts.
    """

    _MESSAGES_THAT_MUST_NEVER_SEND = {
        UnbackedActionCategory.OUT_OF_CHAT_MESSAGE: (
            "Can you email me a checklist of everything I need to "
            "prepare before we start?"
        ),
        UnbackedActionCategory.ALTERNATE_BOOKING_MECHANISM: (
            "can you email me the available times"
        ),
        UnbackedActionCategory.HUMAN_HANDOFF: "can I talk to a real person",
    }

    def setUp(self):
        self._isolate_databases()

    def test_no_other_category_ever_calls_send_email(self):
        for category, message in self._MESSAGES_THAT_MUST_NEVER_SEND.items():
            with self.subTest(category=category):
                engine = ConversationEngine()
                engine.llm = MagicMock()
                engine.llm.generate.side_effect = _ForbiddenLLMCall(
                    "LLM.generate() was called."
                )
                engine.email_provider = MagicMock()
                engine.email_provider.is_connected.return_value = True
                engine.email_provider.send_email.side_effect = AssertionError(
                    f"send_email() was called for category={category!r} -- "
                    f"only CONVERSATION_SUMMARY_EMAIL may ever send a real email."
                )

                response = engine.process_message(f"conv-guard-{category}", message)

                engine.email_provider.send_email.assert_not_called()
                self.assertNotIn("i've sent", response.lower())
                self.assertNotIn("i have sent", response.lower())

    def test_generic_send_me_a_summary_without_conversation_anchor_still_declines(self):
        # "send me a summary" alone (e.g. of pricing, of services) is
        # exactly the case CONVERSATION_SUMMARY_EMAIL_PHRASES was built
        # to exclude -- see core_ai/unbacked_action_detector.py. No
        # category should match this at all, so it must reach the LLM
        # like any ordinary question, not the deterministic gate.
        engine = ConversationEngine()
        engine.llm = MagicMock()
        engine.llm.generate.return_value = "stubbed-response"
        engine.email_provider = MagicMock()
        engine.email_provider.send_email.side_effect = AssertionError(
            "send_email() must never be called for an unanchored summary request."
        )

        response = engine.process_message(
            "conv-guard-generic", "can you send me a summary of your pricing?"
        )

        engine.email_provider.send_email.assert_not_called()
        engine.llm.generate.assert_called_once()
        self.assertEqual(response, "stubbed-response")


class TestConversationSummaryEmailTwentyRunDeterminism(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Same rigor as TestUnbackedActionTwentyRunDeterminism in
    tests/test_conversation_engine_unbacked_actions.py: 20 real
    process_message() calls with the LLM forbidden, proving the
    honest-decline path (no connection, the realistic state for every
    business until the founder reconnects post-scope-change) is
    deterministic by construction, not by sampling.
    """

    RUN_COUNT = 20

    def setUp(self):
        self._isolate_databases()

    def test_twenty_for_twenty_honest_declines_when_not_connected(self):
        responses = []

        for i in range(self.RUN_COUNT):
            engine = ConversationEngine()
            engine.llm = MagicMock()
            engine.llm.generate.side_effect = _ForbiddenLLMCall(
                f"run {i + 1}/{self.RUN_COUNT}: LLM.generate() was called."
            )
            engine.email_provider = MagicMock()
            engine.email_provider.is_connected.return_value = False

            response = engine.process_message(f"conv-summary-twenty-{i}", REQUEST_MESSAGE)

            engine.llm.generate.assert_not_called()
            engine.email_provider.send_email.assert_not_called()
            responses.append(response)

        self.assertEqual(len(responses), self.RUN_COUNT)
        self.assertEqual(
            len(set(responses)), 1,
            f"Expected all {self.RUN_COUNT} responses to be identical; got "
            f"{len(set(responses))} distinct response(s).",
        )
        for response in responses:
            self.assertNotIn("i've sent", response.lower())
            self.assertNotIn("i have sent", response.lower())
            self.assertIn("don't have a way to send", response)


if __name__ == "__main__":
    unittest.main()
