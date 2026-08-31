"""
A spoken email confirmation must quote the exact stored value, not a
free-generated approximation of it.

Regression coverage for a real live voice call. A visitor gave their
email correctly once ("It is oskar.m@yarbo.com"), and EntityExtractor
stored it correctly -- confirmed separately in
tests/test_entity_extractor_budget.py's neighbor concern is budget, but
the email side of this same call is covered directly here. The visitor
then spelled it out letter by letter to confirm it ("O-S-C-A-R dot M at
A-R-B-O dot com"), which contains no literal "@" so EntityExtractor
never touched the correctly stored value -- but the model's own spoken
confirmation back to the visitor free-generated a garbled variant
instead of quoting the real one: "Thanks for confirming oskar.m@.
yorbo.com." Two separate bugs, two separate fixes -- this file covers
the second one (the first, storage, was never actually broken; see
core_ai/conversation_engine.py's
_guard_against_garbled_email_confirmation docstring for the full
trace).
"""

import unittest
from unittest.mock import MagicMock

from core_ai.conversation_engine import ConversationEngine
from core_ai.lead_profile import LeadProfile
from tests.test_voice_channel_no_spoken_url import _IsolatedDatabasesMixin

# Verbatim from the real call that exposed this.
REAL_STORED_EMAIL = "oskar.m@yarbo.com"
REAL_SPELLED_OUT_CONFIRMATION_ATTEMPT = "O-S-C-A-R dot M at A-R-B-O dot com."
REAL_GARBLED_MODEL_RESPONSE = (
    "Thanks for confirming oskar.m@. yorbo.com. Just to align our "
    "proposal, could you let me know the budget range you're "
    "considering for an AI employee to manage Yarbo's sales and support?"
)


class TestGuardAgainstGarbledEmailConfirmation(_IsolatedDatabasesMixin, unittest.TestCase):
    """Direct coverage of the deterministic backstop itself."""

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()

    def test_the_exact_real_garbled_response_is_replaced(self):
        lead = LeadProfile(name="Hasnad", email=REAL_STORED_EMAIL)

        result = self.engine._guard_against_garbled_email_confirmation(
            "conv-1", REAL_GARBLED_MODEL_RESPONSE, lead
        )

        self.assertEqual(result, f"Just to confirm, I have your email as {REAL_STORED_EMAIL}.")
        self.assertIn(REAL_STORED_EMAIL, result)
        self.assertNotIn("yorbo", result)

    def test_a_response_already_containing_the_correct_email_is_untouched(self):
        lead = LeadProfile(name="Alice", email="alice@example.com")
        text = "Great, I have your email as alice@example.com on file."

        result = self.engine._guard_against_garbled_email_confirmation("conv-2", text, lead)

        self.assertEqual(result, text)

    def test_a_response_that_never_mentions_email_is_untouched(self):
        """No "@" in the response at all -- the guard must not fire on
        every turn just because an email is on file."""
        lead = LeadProfile(name="Alice", email="alice@example.com")
        text = "What's your budget for this?"

        result = self.engine._guard_against_garbled_email_confirmation("conv-3", text, lead)

        self.assertEqual(result, text)

    def test_no_op_when_lead_email_is_not_yet_known(self):
        """Nothing to confirm against -- the guard must not invent an
        email just because the response happens to contain "@"."""
        lead = LeadProfile(name="Alice", email="")
        text = "What's the best email address to reach you at?"

        result = self.engine._guard_against_garbled_email_confirmation("conv-4", text, lead)

        self.assertEqual(result, text)

    def test_a_completely_different_email_is_still_caught(self):
        """Not just a mangled variant of the real one -- any email that
        doesn't exactly match counts as unconfirmed."""
        lead = LeadProfile(name="Alice", email="alice@example.com")
        text = "Got it, I'll send that to bob@example.com."

        result = self.engine._guard_against_garbled_email_confirmation("conv-5", text, lead)

        self.assertIn("alice@example.com", result)
        self.assertNotIn("bob@example.com", result)

    def test_it_logs_an_error_when_it_fires(self):
        lead = LeadProfile(name="Alice", email="alice@example.com")
        self.engine.logger = MagicMock()

        self.engine._guard_against_garbled_email_confirmation(
            "conv-6", "I have it as alice@wrong-domain.com", lead
        )

        self.engine.logger.error.assert_called_once()

    def test_it_logs_nothing_on_a_clean_response(self):
        lead = LeadProfile(name="Alice", email="alice@example.com")
        self.engine.logger = MagicMock()

        self.engine._guard_against_garbled_email_confirmation(
            "conv-7", "Confirmed: alice@example.com", lead
        )

        self.engine.logger.error.assert_not_called()


class TestGarbledEmailConfirmationCaughtOnARealTurn(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    The scenario that matters most, driven through a REAL
    process_message() turn: a visitor who already gave their email
    correctly once, then spelled it out to confirm it, with the LLM
    stub DELIBERATELY reproducing the exact garbled confirmation the
    real call produced -- proving the final response the visitor
    actually receives has been corrected by the deterministic guard,
    not that the model happened to behave.
    """

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = False

    def test_spelled_out_confirmation_after_a_correct_first_answer(self):
        conversation_id = "conv-real-scenario"

        # Turn 1: visitor gives the email correctly. Real production
        # entity extraction runs here -- not stubbed -- so this proves
        # storage genuinely captured the correct value, the same
        # structural check confirmed separately for this call in
        # tests/test_entity_extractor_budget.py.
        self.engine.llm.generate = lambda messages: "Thanks."
        self.engine.process_message(
            conversation_id, f"It is {REAL_STORED_EMAIL}.", channel="voice"
        )

        lead = self.engine._get_lead(conversation_id)
        self.assertEqual(
            lead.email, REAL_STORED_EMAIL,
            "Setup assumption failed: the correct email was not stored "
            "after turn 1, so this test would not be exercising the "
            "real scenario.",
        )

        # Turn 2: visitor spells it out letter by letter to confirm --
        # contains no literal "@", so EntityExtractor cannot touch
        # lead.email either way (this is what proves storage was never
        # the bug). The LLM stub deliberately returns the exact garbled
        # confirmation the real call produced.
        self.engine.llm.generate = lambda messages: REAL_GARBLED_MODEL_RESPONSE

        response = self.engine.process_message(
            conversation_id, REAL_SPELLED_OUT_CONFIRMATION_ATTEMPT, channel="voice"
        )

        # The email is still the correct stored value -- confirms the
        # storage side really was untouched by the spelled-out attempt.
        self.assertEqual(self.engine._get_lead(conversation_id).email, REAL_STORED_EMAIL)

        # The SPOKEN confirmation the visitor actually receives is the
        # exact stored value, not the model's garbled reconstruction.
        self.assertIn(REAL_STORED_EMAIL, response)
        self.assertNotIn("yorbo", response)
        self.assertNotIn("oskar.m@. yorbo.com", response)

    def test_the_corrected_response_is_what_gets_stored_in_history_too(self):
        """The guard runs before memory.add_assistant_message, so the
        garbled version can never be replayed back into a later
        prompt's history or shown on the admin transcript view."""
        conversation_id = "conv-real-scenario-history"

        self.engine.llm.generate = lambda messages: "Thanks."
        self.engine.process_message(
            conversation_id, f"It is {REAL_STORED_EMAIL}.", channel="voice"
        )

        self.engine.llm.generate = lambda messages: REAL_GARBLED_MODEL_RESPONSE
        self.engine.process_message(
            conversation_id, REAL_SPELLED_OUT_CONFIRMATION_ATTEMPT, channel="voice"
        )

        stored = self.engine.memory.get_conversation(conversation_id)
        assistant_messages = [m["content"] for m in stored if m["role"] == "assistant"]

        self.assertIn(REAL_STORED_EMAIL, assistant_messages[-1])
        self.assertNotIn("yorbo", assistant_messages[-1])


if __name__ == "__main__":
    unittest.main()
