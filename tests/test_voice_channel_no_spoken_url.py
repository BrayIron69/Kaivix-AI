"""
A visitor on a phone call cannot click a link, and reading a raw URL
aloud is not something anyone can act on. Proves that none of the five
known sources of a spoken URL can still produce one for channel="voice":

  1. UnbackedActionCategory.OUT_OF_CHAT_MESSAGE's fixed decline template
  2. UnbackedActionCategory.ALTERNATE_BOOKING_MECHANISM's fixed decline
  3. UnbackedActionCategory.HUMAN_HANDOFF's fixed decline
  4. _handle_conversation_summary_email_request's failed-send fallback
  5. The generative BOOKING SYSTEM ERROR prompt section -- the one a
     simple string check on a fixed template can't catch, since it is
     the model's own free generation, not Python-owned text. Proven with
     a live process_message() turn and an LLM stub that DELIBERATELY
     violates the channel instruction, so the claim is "the deterministic
     backstop caught it", not "the model happened to behave this run".

Each case is also checked against channel="chat" (or no channel argument
at all) to prove the fix is genuinely channel-conditional -- a chat
visitor can click a link, and that behaviour must be completely
unaffected, not collaterally removed.
"""

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
from core_ai.lead_profile import LeadProfile

UTC = ZoneInfo("UTC")


class _IsolatedDatabasesMixin:
    """
    Isolates CRM, long-term-memory, AND conversation-memory storage --
    all three, not just the first two.

    Several existing files with a same-named mixin (e.g.
    tests/test_conversation_engine_unbacked_actions.py,
    tests/test_conversation_engine_summary_email.py,
    tests/test_conversation_engine_booking.py) isolate only CRM and
    long-term memory, never memory.conversation_store's
    SQLiteConversationStore.DB_PATH -- so every ConversationEngine() they
    construct writes real turns into the real
    memory/conversation_memory.db on disk. That was invisible there
    because none of those files assert on stored conversation history.
    This file's whole point is asserting on exactly that
    (engine.memory.get_conversation(...)), and running it against the
    mixin's incomplete pattern silently accumulated duplicate messages
    under this file's own test conversation_ids in the real database --
    caught while verifying these tests actually detect a regression (see
    the session notes on this fix), not by inspection. Matches the
    correct, complete pattern tests/test_multi_business_serving.py's own
    _IsolatedDatabasesMixin already uses.
    """

    def _isolate_databases(self):
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


class _ForbiddenLLMCall(AssertionError):
    """Raised if the real LLM is ever invoked -- these cases must
    short-circuit before generation, same discipline as
    tests/test_conversation_engine_unbacked_actions.py."""


def _contains_url(text: str) -> bool:
    """
    Deliberately a DIFFERENT, dumber check than production's
    ConversationEngine._response_contains_a_url -- a test asserting on
    the thing it imports from the code under test would prove nothing if
    that regex itself had a bug. A plain substring scan is enough to
    prove the property that actually matters here.
    """
    lowered = text.lower()
    return "http://" in lowered or "https://" in lowered or "calendly.com" in lowered or "www." in lowered


class TestFixedDeclineTemplatesNeverSpeakAURL(_IsolatedDatabasesMixin, unittest.TestCase):
    """Cases 1-3 of 5. Engine-level, through the real short-circuit path
    -- the LLM is forbidden, so a URL here could only come from
    Python-owned template text."""

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.llm = MagicMock()
        self.engine.llm.generate.side_effect = _ForbiddenLLMCall(
            "LLM.generate() was called -- the unbacked-action gate did "
            "not short-circuit before generation."
        )
        # These decline paths now call email_provider.is_connected() for
        # voice (see _voice_booking_alternative); a fresh
        # ConversationEngine's real EmailProvider would otherwise hit
        # the real local calendar_tokens.db.
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = False

    def test_out_of_chat_message_voice_response_has_no_url(self):
        response = self.engine.process_message(
            "conv-ooc-voice", "can you text me a summary?", channel="voice"
        )
        self.assertFalse(_contains_url(response), response)

    def test_out_of_chat_message_chat_response_still_has_the_url(self):
        response = self.engine.process_message(
            "conv-ooc-chat", "can you text me a summary?", channel="chat"
        )
        self.assertTrue(_contains_url(response), response)

    def test_alternate_booking_mechanism_voice_response_has_no_url(self):
        response = self.engine.process_message(
            "conv-abm-voice", "can you email me the available times", channel="voice"
        )
        self.assertFalse(_contains_url(response), response)

    def test_alternate_booking_mechanism_chat_response_still_has_the_url(self):
        response = self.engine.process_message(
            "conv-abm-chat", "can you email me the available times", channel="chat"
        )
        self.assertTrue(_contains_url(response), response)

    def test_human_handoff_voice_response_has_no_url(self):
        response = self.engine.process_message(
            "conv-hh-voice", "can I talk to a real person", channel="voice"
        )
        self.assertFalse(_contains_url(response), response)

    def test_human_handoff_chat_response_still_has_the_url(self):
        response = self.engine.process_message(
            "conv-hh-chat", "can I talk to a real person", channel="chat"
        )
        self.assertTrue(_contains_url(response), response)

    def test_no_channel_argument_at_all_defaults_to_chat_with_the_url(self):
        """
        Backward compatibility: every existing chat.py call site never
        passes channel, and must be completely unaffected by this
        change.
        """
        response = self.engine.process_message(
            "conv-default", "can I talk to a real person"
        )
        self.assertTrue(_contains_url(response), response)


class TestSummaryEmailFailureFallbackNeverSpeaksAURL(_IsolatedDatabasesMixin, unittest.TestCase):
    """Case 4 of 5: the conversation-summary-email failure fallback --
    reached only after a real send attempt for the SUMMARY itself has
    already failed."""

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.llm = MagicMock()
        self.engine.llm.generate.side_effect = _ForbiddenLLMCall(
            "LLM.generate() was called -- CONVERSATION_SUMMARY_EMAIL "
            "did not short-circuit before generation."
        )
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = True
        self.engine.email_provider.send_email.return_value = {
            "success": False, "error": "smtp timeout",
        }

    def test_voice_response_has_no_url_when_the_summary_send_fails(self):
        conversation_id = "conv-summary-fail-voice"
        self.engine._update_lead_profile(conversation_id, "my email is alice@example.com")

        response = self.engine.process_message(
            conversation_id,
            "Can you email me a summary of this conversation?",
            channel="voice",
        )

        self.assertFalse(_contains_url(response), response)
        # No wasteful retry of the send that just failed, in the same
        # turn, to the same address -- see
        # _voice_booking_alternative's docstring on why this branch
        # deliberately does not reuse it.
        self.engine.email_provider.send_email.assert_called_once()

    def test_chat_response_still_has_the_url_when_the_summary_send_fails(self):
        conversation_id = "conv-summary-fail-chat"
        self.engine._update_lead_profile(conversation_id, "my email is bob@example.com")

        response = self.engine.process_message(
            conversation_id,
            "Can you email me a summary of this conversation?",
            channel="chat",
        )

        self.assertTrue(_contains_url(response), response)


class TestVoiceBookingAlternative(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Direct coverage of the one helper every voice decline path shares
    (core_ai/conversation_engine.py's _voice_booking_alternative): real
    email send when possible, honest ask or honest refusal otherwise --
    never a fabricated promise (no SMS provider exists; no callback
    mechanism exists).
    """

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.email_provider = MagicMock()

    def test_not_connected_gives_the_fixed_message_with_no_url_and_sends_nothing(self):
        self.engine.email_provider.is_connected.return_value = False
        lead = LeadProfile(name="Alice", email="alice@example.com")

        result = self.engine._voice_booking_alternative("conv-1", lead)

        self.assertEqual(result, ConversationEngine._VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE)
        self.assertFalse(_contains_url(result))
        self.engine.email_provider.send_email.assert_not_called()

    def test_connected_but_email_unknown_asks_for_it_and_sends_nothing(self):
        self.engine.email_provider.is_connected.return_value = True
        lead = LeadProfile(name="Alice", email="")

        result = self.engine._voice_booking_alternative("conv-2", lead)

        self.assertIn("email address", result.lower())
        self.assertFalse(_contains_url(result))
        self.engine.email_provider.send_email.assert_not_called()

    def test_connected_and_email_known_actually_sends_and_says_so_truthfully(self):
        self.engine.email_provider.is_connected.return_value = True
        self.engine.email_provider.send_email.return_value = {"success": True, "error": None}
        lead = LeadProfile(name="Alice", email="alice@example.com")

        result = self.engine._voice_booking_alternative("conv-3", lead)

        self.assertIn("alice@example.com", result)
        self.assertIn("emailed", result.lower())
        self.assertFalse(_contains_url(result))

        _args, kwargs = self.engine.email_provider.send_email.call_args
        self.assertEqual(kwargs["to"], "alice@example.com")
        booking_link = self.engine.business_config.persona.booking_link
        # The URL is fine INSIDE the email body -- an email reader can
        # click a link, unlike a phone caller.
        self.assertIn(booking_link, kwargs["body_text"])
        # But it must never appear in the spoken response text itself.
        self.assertNotIn(booking_link, result)

    def test_connected_and_email_known_but_send_fails_asks_again_with_no_url(self):
        self.engine.email_provider.is_connected.return_value = True
        self.engine.email_provider.send_email.return_value = {
            "success": False, "error": "boom",
        }
        lead = LeadProfile(name="Alice", email="alice@example.com")

        result = self.engine._voice_booking_alternative("conv-4", lead)

        self.assertFalse(_contains_url(result))
        self.assertIn("email address", result.lower())

    def test_never_offers_to_text_the_link(self):
        """
        No SMS provider exists anywhere in this codebase --
        core_ai/unbacked_action_detector.py's own OUT_OF_CHAT_MESSAGE_
        PHRASES already treats "text me" as something Bray cannot do.
        Claiming it here would be a fabricated capability.
        """
        self.engine.email_provider.is_connected.return_value = False
        lead = LeadProfile(name="Alice", email="alice@example.com")

        result = self.engine._voice_booking_alternative("conv-5", lead)

        self.assertNotIn("text you", result.lower())
        self.assertNotIn("i'll text", result.lower())

    def test_never_promises_a_callback(self):
        """
        No callback mechanism exists in code (no queue, no notification
        to the founder) -- a passive promise about a future human action
        with nothing guaranteeing it is exactly the shape of claim
        UnbackedActionDetector exists to prevent.
        """
        self.engine.email_provider.is_connected.return_value = False
        lead = LeadProfile(name="Alice", email="alice@example.com")

        result = self.engine._voice_booking_alternative("conv-6", lead)

        self.assertNotIn("someone will call", result.lower())
        self.assertNotIn("we'll call you back", result.lower())
        self.assertNotIn("have someone", result.lower())


class TestGuardAgainstSpokenURL(_IsolatedDatabasesMixin, unittest.TestCase):
    """Direct coverage of the deterministic backstop itself
    (_guard_against_spoken_url / _response_contains_a_url)."""

    def setUp(self):
        self._isolate_databases()
        self.engine = ConversationEngine()
        self.engine.email_provider = MagicMock()
        self.engine.email_provider.is_connected.return_value = False
        self.lead = LeadProfile(name="Alice", email="alice@example.com")

    def test_chat_channel_is_always_a_no_op_even_with_a_url_present(self):
        text = "Book here: https://calendly.com/brayiron-kaivixlab/30min"

        result = self.engine._guard_against_spoken_url("conv-1", text, "chat", self.lead)

        self.assertEqual(result, text)

    def test_clean_voice_response_is_returned_unchanged(self):
        text = "Great, what's the best email address for you?"

        result = self.engine._guard_against_spoken_url("conv-2", text, "voice", self.lead)

        self.assertEqual(result, text)

    def test_scheme_url_in_voice_response_is_replaced(self):
        text = "You can book at https://calendly.com/brayiron-kaivixlab/30min anytime."

        result = self.engine._guard_against_spoken_url("conv-3", text, "voice", self.lead)

        self.assertFalse(_contains_url(result))
        self.assertEqual(result, ConversationEngine._VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE)

    def test_bare_booking_link_domain_without_a_scheme_is_still_caught(self):
        """The model dropping the scheme while paraphrasing must not
        slip through -- "calendly.com/..." alone is not naturally
        speakable either."""
        text = "Just go to calendly.com/brayiron-kaivixlab/30min to grab a time."

        result = self.engine._guard_against_spoken_url("conv-4", text, "voice", self.lead)

        self.assertNotIn("calendly.com", result)

    def test_www_style_url_is_caught(self):
        text = "Check out www.example.com for details."

        result = self.engine._guard_against_spoken_url("conv-5", text, "voice", self.lead)

        self.assertNotIn("www.", result)

    def test_a_completely_different_url_is_still_caught(self):
        """The generic scheme pattern is not scoped only to this
        business's own booking_link."""
        text = "You can read more about us at https://en.wikipedia.org/wiki/Example."

        result = self.engine._guard_against_spoken_url("conv-6", text, "voice", self.lead)

        self.assertFalse(_contains_url(result))

    def test_replacement_reuses_voice_booking_alternative_when_it_can_send(self):
        self.engine.email_provider.is_connected.return_value = True
        self.engine.email_provider.send_email.return_value = {"success": True, "error": None}
        text = "Book here: https://calendly.com/brayiron-kaivixlab/30min"

        result = self.engine._guard_against_spoken_url("conv-7", text, "voice", self.lead)

        self.assertIn("alice@example.com", result)
        self.engine.email_provider.send_email.assert_called_once()

    def test_it_logs_an_error_when_it_fires(self):
        self.engine.logger = MagicMock()
        text = "https://calendly.com/brayiron-kaivixlab/30min"

        self.engine._guard_against_spoken_url("conv-8", text, "voice", self.lead)

        self.engine.logger.error.assert_called_once()

    def test_it_logs_nothing_on_a_clean_response(self):
        self.engine.logger = MagicMock()

        self.engine._guard_against_spoken_url("conv-9", "all good here", "voice", self.lead)

        self.engine.logger.error.assert_not_called()


class TestLiveGenerativeBookingErrorNeverSpeaksAURL(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Case 5 of 5, and the one that matters most. The BOOKING SYSTEM ERROR
    prompt section is an INSTRUCTION, not a guarantee -- the model can
    ignore it, exactly the way this same pipeline's own pricing_guard.py
    was built after measuring the model ignoring "never invent a price"
    on real production-shaped runs. Checking only the fixed templates
    (cases 1-4 above) would prove nothing about this path, since those
    never reach the LLM at all.

    This drives a REAL process_message() turn through a REAL booking
    failure (mocked calendar_provider.create_event, same fixture pattern
    as tests/test_conversation_engine_booking.py's
    TestMaybeResolveBookingWithinFullTurn), with the LLM stub
    DELIBERATELY returning a URL-laden string -- simulating the exact
    failure mode this fix exists to close -- and proves the FINAL
    response has no URL because the deterministic backstop caught it,
    not because the model happened to behave.
    """

    _OFFERED_SLOTS = ["Tuesday 2:00 PM - 3:00 PM"]
    _WINDOWS = [
        (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
    ]
    _MODEL_VIOLATING_THE_INSTRUCTION = (
        "So sorry about that. You can book directly at "
        "https://calendly.com/brayiron-kaivixlab/30min. Talk soon."
    )

    def setUp(self):
        self._isolate_databases()

    def _engine_with_a_failed_booking_attempt(self, conversation_id: str) -> ConversationEngine:
        engine = ConversationEngine()
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.create_event.return_value = {
            "success": False, "event_link": None,
            "error": "calendar API rejected the request",
        }
        working_memory = engine.memory_manager.get_working_memory(conversation_id)
        working_memory.set_offered_slots(self._OFFERED_SLOTS)
        engine._offered_slot_windows[conversation_id] = list(self._WINDOWS)
        return engine

    def test_model_ignoring_the_voice_instruction_is_still_caught(self):
        conversation_id = "conv-live-voice"
        engine = self._engine_with_a_failed_booking_attempt(conversation_id)
        engine.email_provider = MagicMock()
        engine.email_provider.is_connected.return_value = False

        captured = {}

        def fake_generate(messages):
            captured["system_prompt"] = messages[0]["content"]
            return self._MODEL_VIOLATING_THE_INSTRUCTION

        engine.llm.generate = fake_generate

        response = engine.process_message(conversation_id, "1", channel="voice")

        # The prompt-level fix (item 2) took effect: the BOOKING SYSTEM
        # ERROR section itself never told the model to say the link.
        self.assertIn("BOOKING SYSTEM ERROR", captured["system_prompt"])
        self.assertNotIn(
            "offer this booking link as a fallback instead",
            captured["system_prompt"],
        )

        # The model violated the instruction anyway (by construction of
        # this test's stub) -- and the deterministic backstop is what
        # actually held regardless.
        self.assertFalse(_contains_url(response), response)
        self.assertEqual(response, ConversationEngine._VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE)

    def test_the_exact_same_model_output_reaches_a_chat_visitor_unchanged(self):
        """
        The contrast that proves this is genuinely channel-specific, not
        a blanket rewrite of every response: a chat visitor CAN click a
        link, so identical model output must reach them untouched.
        """
        conversation_id = "conv-live-chat"
        engine = self._engine_with_a_failed_booking_attempt(conversation_id)
        engine.llm.generate = lambda messages: self._MODEL_VIOLATING_THE_INSTRUCTION

        response = engine.process_message(conversation_id, "1", channel="chat")

        self.assertEqual(response, self._MODEL_VIOLATING_THE_INSTRUCTION)

    def test_the_spoken_url_never_enters_conversation_history_either(self):
        """
        The guard runs before memory.add_assistant_message, so a URL the
        model generated can never be replayed back into a later prompt's
        history or shown on the admin transcript view.
        """
        conversation_id = "conv-live-history"
        engine = self._engine_with_a_failed_booking_attempt(conversation_id)
        engine.email_provider = MagicMock()
        engine.email_provider.is_connected.return_value = False
        engine.llm.generate = lambda messages: self._MODEL_VIOLATING_THE_INSTRUCTION

        engine.process_message(conversation_id, "1", channel="voice")

        stored = engine.memory.get_conversation(conversation_id)
        assistant_messages = [m["content"] for m in stored if m["role"] == "assistant"]

        self.assertEqual(len(assistant_messages), 1)
        self.assertFalse(_contains_url(assistant_messages[0]), assistant_messages[0])

    def test_a_clean_model_response_to_a_voice_booking_failure_passes_through(self):
        """Not every voice response to a booking failure is replaced --
        only ones that actually contain a URL."""
        conversation_id = "conv-live-clean"
        engine = self._engine_with_a_failed_booking_attempt(conversation_id)
        engine.email_provider = MagicMock()
        engine.email_provider.is_connected.return_value = True
        engine.email_provider.send_email.return_value = {"success": True, "error": None}

        clean_model_output = (
            "I'm sorry, I wasn't able to get that booked just now due to "
            "a system issue. What's the best email address for you?"
        )
        engine.llm.generate = lambda messages: clean_model_output

        response = engine.process_message(conversation_id, "1", channel="voice")

        self.assertEqual(response, clean_model_output)


if __name__ == "__main__":
    unittest.main()
