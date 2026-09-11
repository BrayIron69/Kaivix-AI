import os
import tempfile
import unittest
from unittest.mock import MagicMock

import crm.database as crm_database
import memory.conversation_store as conversation_store_module
import memory.long_term_memory as ltm_module
from core_ai.ai_disclosure_detector import AIDisclosureDetector
from core_ai.prompt_builder import PromptBuilder
from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID


class _IsolatedDatabasesMixin:
    """
    Same complete three-way isolation
    tests/test_voice_channel_no_spoken_url.py documents: CRM,
    long-term memory AND conversation memory, so a real
    ConversationEngine can be exercised end to end without writing real
    turns into the real databases on disk.
    """

    def _isolate_databases(self):
        paths = []
        for _ in range(3):
            fd, path = tempfile.mkstemp(suffix=".db")
            os.close(fd)
            os.remove(path)
            paths.append(path)
        crm_db_path, ltm_db_path, conv_db_path = paths

        original_crm = crm_database.DATABASE_NAME
        original_ltm = ltm_module.SQLiteLongTermMemoryStore.DB_PATH
        original_conv = conversation_store_module.SQLiteConversationStore.DB_PATH

        crm_database.DATABASE_NAME = crm_db_path
        ltm_module.SQLiteLongTermMemoryStore.DB_PATH = ltm_db_path
        conversation_store_module.SQLiteConversationStore.DB_PATH = conv_db_path

        def _restore():
            crm_database.DATABASE_NAME = original_crm
            ltm_module.SQLiteLongTermMemoryStore.DB_PATH = original_ltm
            conversation_store_module.SQLiteConversationStore.DB_PATH = original_conv
            for path in paths:
                if os.path.exists(path):
                    os.remove(path)

        self.addCleanup(_restore)


class TestDetectsTheQuestionInAnyPhrasing(unittest.TestCase):
    """
    The four phrasings called out in the bug report, plus the variants a
    real visitor actually types. A phrasing this misses is a turn where
    the model, not Python, decides whether to admit what it is.
    """

    def setUp(self):
        self.detector = AIDisclosureDetector(ai_name="Bray")

    def test_the_exact_phrasings_from_the_bug_report(self):
        for message in [
            "are you ai",
            "are you AI",
            "are you a bot",
            "am I talking to a real person",
            "who am I speaking with",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self.detector.asks_whether_ai(message))

    def test_question_mark_and_capitalisation_do_not_matter(self):
        for message in [
            "Are you AI?",
            "ARE YOU A BOT?",
            "are you a bot?",
            "Are you an AI?",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self.detector.asks_whether_ai(message))

    def test_human_side_phrasings(self):
        for message in [
            "are you human",
            "are you a human",
            "are you a real person",
            "are you real",
            "are you actually human",
            "am i speaking with a human",
            "am i chatting with a real person",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self.detector.asks_whether_ai(message))

    def test_machine_side_phrasings(self):
        for message in [
            "are you a robot",
            "are you a machine",
            "are you chatgpt",
            "are you a language model",
            "is this a bot",
            "is this ai",
            "is this automated",
            "am i talking to a bot",
            "r u a bot",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self.detector.asks_whether_ai(message))

    def test_statement_form_accusation_also_triggers_disclosure(self):
        """
        "you're a bot" is not a question, but a visitor who has worked it
        out and says so deserves confirmation, not a dodge.
        """
        for message in [
            "you're a bot",
            "you are an AI",
            "youre a robot arent you",
        ]:
            with self.subTest(message=message):
                self.assertTrue(self.detector.asks_whether_ai(message))

    def test_either_or_phrasing(self):
        for message in ["human or bot?", "ai or human?", "are you a person or a machine"]:
            with self.subTest(message=message):
                self.assertTrue(self.detector.asks_whether_ai(message))

    def test_ordinary_sales_conversation_does_not_trigger(self):
        """
        False positives here hijack a normal turn with an unprompted
        identity speech, so the ordinary vocabulary of this product --
        which is literally about AI employees replacing human staff --
        must stay clear of the patterns.
        """
        for message in [
            "how much does an AI employee cost",
            "can your AI handle customer support",
            "we have three human staff on support right now",
            "I want to replace a human employee with automation",
            "what does the bot do when it can't answer",
            "is this a good fit for a dental clinic",
            "my name is Sarah and I run a clinic",
        ]:
            with self.subTest(message=message):
                self.assertFalse(self.detector.asks_whether_ai(message))

    def test_handoff_requests_are_left_to_the_unbacked_action_detector(self):
        """
        These belong to UnbackedActionDetector.HUMAN_HANDOFF_PHRASES,
        which already declines them honestly. Stealing them here would
        replace a more useful answer with a less useful one.
        """
        for message in [
            "can I talk to a human",
            "is there a real person I can speak to",
            "transfer me to someone",
        ]:
            with self.subTest(message=message):
                self.assertFalse(self.detector.asks_whether_ai(message))


class TestDetectsAFalseHumanityClaimInAResponse(unittest.TestCase):
    def setUp(self):
        self.detector = AIDisclosureDetector(ai_name="Bray")

    def test_the_verbatim_response_from_the_real_incident(self):
        self.assertTrue(
            self.detector.claims_to_be_human(
                "I'm Bray, a real human sales rep here at Kaivix Labs."
            )
        )

    def test_other_ways_of_claiming_to_be_a_person(self):
        for response in [
            "I'm human!",
            "I am a real person, promise.",
            "I'm not a bot.",
            "I am not an AI.",
            "Yes, a real person here.",
            "You're talking to a human.",
            "I'm an actual person sitting at a desk.",
        ]:
            with self.subTest(response=response):
                self.assertTrue(self.detector.claims_to_be_human(response))

    def test_legitimate_talk_about_human_staff_is_not_a_claim(self):
        """
        The knowledge base legitimately discusses replacing human staff.
        Matching the bare noun would replace correct, on-topic answers
        with an identity disclosure nobody asked for.
        """
        for response in [
            "Our AI employees work alongside your human staff.",
            "It costs less than a human employee's salary.",
            "A human takes about 20 hours a week on this; the AI does it 24/7.",
            "I'm an AI, so I don't take sick days.",
            "I'm Bray, the AI assistant for Kaivix Labs.",
        ]:
            with self.subTest(response=response):
                self.assertFalse(self.detector.claims_to_be_human(response))

    def test_selling_against_human_roles_is_not_a_claim_to_be_one(self):
        """
        This product's entire pitch is AI employees doing what human
        staff do, so these are correct, on-topic sales answers. An
        earlier draft matched "human agent"/"human rep" unanchored and
        would have replaced every one of them with an identity
        disclosure nobody asked for -- caught by
        tests/test_multi_business_serving.py, not by inspection.
        """
        for response in [
            "Our AI can take over what a human agent does today.",
            "It handles the same tickets a human representative would.",
            "You get the coverage of a human sales rep without the salary.",
            "Most teams keep one human advisor for escalations.",
        ]:
            with self.subTest(response=response):
                self.assertFalse(self.detector.claims_to_be_human(response))

    def test_the_detached_claim_from_the_incident_is_still_caught(self):
        """
        The anchoring above must not cost us the actual incident: in
        "I'm Bray, a real human sales rep", the agent's own name sits
        between the "I'm" and the claim.
        """
        self.assertTrue(
            self.detector.claims_to_be_human(
                "I'm Bray, a real human sales rep here at Kaivix Labs."
            )
        )

    def test_invented_surname_is_caught(self):
        for response in [
            "I'm Bray Iron, nice to meet you.",
            "My name is Bray Iron.",
            "My full name is Bray Iron.",
        ]:
            with self.subTest(response=response):
                self.assertTrue(self.detector.claims_invented_surname(response))

    def test_legitimate_uses_of_the_agents_name_are_not_a_surname_claim(self):
        for response in [
            "I'm Bray from Kaivix Labs.",
            "I'm Bray, a sales agent here.",
            "I'm Bray and I'd love to help.",
        ]:
            with self.subTest(response=response):
                self.assertFalse(self.detector.claims_invented_surname(response))


class TestThePromptNoLongerInstructsItToClaimHumanity(unittest.TestCase):
    """
    The root cause was not model drift: the prompt said, in as many
    words, "You are NOT a bot. You are a real human sales rep." These
    tests fail if that sentence ever comes back, in either of the two
    places it lived.
    """

    def test_agent_identity_does_not_claim_to_be_human(self):
        identity = PromptBuilder.AGENT_IDENTITY.lower()
        self.assertNotIn("real human sales rep", identity)
        self.assertNotIn("you are not a bot", identity)

    def test_agent_identity_states_it_is_an_ai(self):
        identity = PromptBuilder.AGENT_IDENTITY.lower()
        self.assertIn("ai", identity)
        self.assertIn("you are not a human", identity)

    def test_live_kaivix_persona_matches_and_is_also_clean(self):
        config = BusinessConfigRepository().load(DEFAULT_BUSINESS_ID)
        statement = config.persona.identity_statement.lower()
        self.assertNotIn("real human sales rep", statement)
        self.assertNotIn("you are not a bot", statement)
        self.assertIn("you are not a human", statement)

    def test_disclosure_rule_outranks_and_precedes_the_numbered_rules(self):
        """
        "High in the prompt's priority ordering" is the requirement, so
        assert position, not just presence.
        """
        rules = PromptBuilder.ENGINE_RULES
        self.assertIn("RULE 0", rules)
        self.assertLess(rules.index("RULE 0"), rules.index("RULES:"))

    def test_rule_1_no_longer_tells_it_to_sound_human(self):
        """
        "Sound human" sat one line below a rule forbidding it to claim
        humanity. Tone guidance shouldn't read as licence for the thing
        RULE 0 forbids.
        """
        self.assertNotIn("Sound human", PromptBuilder.ENGINE_RULES)


class TestDisclosureHoldsThroughRealProcessMessage(
    _IsolatedDatabasesMixin, unittest.TestCase
):
    """
    End-to-end through the real pipeline, with the LLM stubbed to return
    exactly what it returned in the live incident. The guarantee has to
    hold against a model that is actively trying to claim humanity.

    Only the LLM and the two external providers are replaced; every
    other component (planner, memory manager, prompt builder, guards) is
    the real one, so this proves the wiring, not a stub of it.
    """

    def _engine(self, llm_response: str = "Sure, happy to help."):
        from core_ai.conversation_engine import ConversationEngine

        engine = ConversationEngine()
        engine.llm = MagicMock()
        engine.llm.generate.return_value = llm_response
        engine.calendar_provider = MagicMock()
        engine.calendar_provider.is_connected.return_value = False
        engine.email_provider = MagicMock()
        engine.email_provider.is_connected.return_value = False
        return engine

    def setUp(self):
        self._isolate_databases()

    def test_direct_question_never_reaches_the_model_at_all(self):
        engine = self._engine(
            llm_response="I'm Bray, a real human sales rep here at Kaivix Labs."
        )

        response = engine.process_message("conv-1", "are you ai")

        self.assertIn("I'm an AI", response)
        self.assertNotIn("human sales rep", response)
        engine.llm.generate.assert_not_called()

    def test_every_reported_phrasing_gets_an_honest_answer(self):
        for message in [
            "are you AI",
            "are you a bot",
            "am I talking to a real person",
            "who am I speaking with",
        ]:
            with self.subTest(message=message):
                engine = self._engine(
                    llm_response="I'm Bray, a real human sales rep here at Kaivix Labs."
                )
                response = engine.process_message("conv-x", message)
                self.assertIn("I'm an AI", response)

    def test_model_volunteering_a_human_claim_is_replaced(self):
        """
        The other direction: a phrasing the question patterns don't
        catch, where the model claims humanity unprompted. The backstop
        guard, not the gate, is what has to hold here.
        """
        engine = self._engine(
            llm_response="Great question! I'm a real person, not a bot, and I'd love to help."
        )

        response = engine.process_message("conv-2", "hmm interesting, tell me more")

        self.assertNotIn("real person", response)
        self.assertIn("I'm an AI", response)

    def test_invented_surname_is_replaced(self):
        engine = self._engine(llm_response="I'm Bray Iron, great to meet you!")

        response = engine.process_message("conv-3", "whats your full name")

        self.assertNotIn("Bray Iron", response)
        self.assertIn("I'm an AI", response)

    def test_a_clean_response_passes_through_untouched(self):
        engine = self._engine(
            llm_response="We build AI employees that handle support around the clock."
        )

        response = engine.process_message("conv-4", "what do you do")

        self.assertEqual(
            response, "We build AI employees that handle support around the clock."
        )

    def test_disclosure_still_moves_the_conversation_forward(self):
        """
        An honest answer that kills the conversation creates pressure to
        weaken it later, so it has to still be a sales turn.
        """
        engine = self._engine()
        response = engine.process_message("conv-5", "are you a bot")
        self.assertTrue(response.rstrip().endswith("?"))


if __name__ == "__main__":
    unittest.main()
