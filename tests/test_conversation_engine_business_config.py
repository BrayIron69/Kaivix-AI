import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import crm.database as crm_database
import memory.long_term_memory as ltm_module
from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID
from core_ai.conversation_engine import ConversationEngine
from core_ai.prompt_builder import PromptBuilder
from crm.sqlite_crm import SQLiteCRM

# The exact prior document-stem set loaded by KnowledgeBase() with no
# args (see tests/test_knowledge_base_business_config.py) — reused here to
# prove ConversationEngine()'s default construction still wires up
# Kaivix's own knowledge, unchanged.
KAIVIX_DOCUMENT_STEMS = {
    "case_studies",
    "company",
    "competitors",
    "faq",
    "integrations",
    "objections",
    "pricing",
    "process",
    "services",
}

KAIVIX_REQUIRED_FIELDS = ["name", "email", "company", "budget", "timeline"]


def _stub_llm(engine: ConversationEngine) -> None:
    """Replace the LLM call with a stub so tests never hit the real Groq
    API. Purely test-side; no production code is touched."""
    engine.llm.generate = lambda messages: "stubbed-response"


def _spy_prompt_builder(engine: ConversationEngine) -> dict:
    """
    Wrap engine.prompt_builder.build so every call's kwargs and return
    value are recorded, while still delegating to the real
    implementation. Lets tests inspect exactly what PromptBuilder
    received/produced during a real process_message() turn without
    needing any new production seam.
    """
    original_build = engine.prompt_builder.build
    captured = {"kwargs": None, "output": None}

    def spy(**kwargs):
        captured["kwargs"] = kwargs
        output = original_build(**kwargs)
        captured["output"] = output
        return output

    engine.prompt_builder.build = spy
    return captured


class _IsolatedDatabasesMixin:
    """
    Points crm/database.py and memory/long_term_memory.py's SQLite stores
    at fresh temp files for the duration of a test, so constructing a
    real ConversationEngine (which constructs a real LeadService and a
    real MemoryManager/LongTermMemory under the hood) never touches
    crm/leads.db or memory/long_term_memory.db. Same monkeypatch pattern
    used by tests/test_crm_business_scoping.py and
    tests/test_long_term_memory_business_scoping.py.
    """

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


class TestConversationEngineDefaultPathRegression(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Proves ConversationEngine() with no args is unchanged by this
    milestone: it still resolves to Kaivix's own BusinessConfig, still
    builds the same QualificationEngine/KnowledgeBase Kaivix always had,
    and threading business_config explicitly into PromptBuilder.build()
    produces byte-identical output to the pre-milestone call that never
    passed it at all.
    """

    def setUp(self):
        self._isolate_databases()

    def test_default_construction_matches_pre_milestone_defaults(self):
        engine = ConversationEngine()

        expected_config = BusinessConfigRepository().load(DEFAULT_BUSINESS_ID)

        self.assertEqual(engine.business_id, DEFAULT_BUSINESS_ID)
        self.assertEqual(
            engine.business_config.persona.identity_statement,
            expected_config.persona.identity_statement,
        )
        self.assertEqual(engine.qualification_engine.required_fields, KAIVIX_REQUIRED_FIELDS)
        self.assertEqual(set(engine.knowledge.documents.keys()), KAIVIX_DOCUMENT_STEMS)

    def test_full_turn_prompt_building_unaffected_by_explicit_business_config(self):
        engine = ConversationEngine()
        _stub_llm(engine)
        captured = _spy_prompt_builder(engine)

        response = engine.process_message(
            "conv-default-1", "Hi, I'm Alice and my email is alice@example.com."
        )

        self.assertEqual(response, "stubbed-response")
        self.assertIsNotNone(captured["kwargs"])
        self.assertIn("business_config", captured["kwargs"])
        self.assertIsNotNone(captured["kwargs"]["business_config"])

        kwargs_without_business_config = dict(captured["kwargs"])
        kwargs_without_business_config.pop("business_config")

        # The pre-milestone call site never passed business_config at all
        # (PromptBuilder.build() defaulted it internally to Kaivix's own
        # config). Proving these two produce identical output shows this
        # milestone's change to that one call site is a genuine no-op for
        # the default path.
        explicit_output = PromptBuilder().build(**captured["kwargs"])
        implicit_output = PromptBuilder().build(**kwargs_without_business_config)

        self.assertEqual(explicit_output, implicit_output)
        self.assertEqual(captured["output"], explicit_output)


class TestConversationEngineCrossBusiness(_IsolatedDatabasesMixin, unittest.TestCase):
    """
    Constructs a second, distinct BusinessConfig ("business-b") with a
    different persona, a different (smaller) qualification schema, and
    different knowledge content than Kaivix, then proves
    ConversationEngine actually threads it through end-to-end rather
    than silently defaulting to Kaivix everywhere.
    """

    def setUp(self):
        self._isolate_databases()

        self._tmp_knowledge_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_knowledge_dir.cleanup)

        knowledge_dir = Path(self._tmp_knowledge_dir.name)
        (knowledge_dir / "widgets.md").write_text(
            "Widget Co Automation builds custom widget-fulfillment bots.",
            encoding="utf-8",
        )

        # A minimal stand-in BusinessConfig, not real YAML files loaded via
        # BusinessConfigRepository — same pattern
        # tests/test_knowledge_base_business_config.py and
        # tests/test_qualification_engine_business_config.py use for their
        # own "second business" proofs (a SimpleNamespace matching only
        # the attribute shape each consumer actually reads). This sidesteps
        # BusinessConfigRepository._get_default_sections() eagerly needing
        # a real Kaivix directory as its fallback-defaults source even when
        # every section is otherwise explicitly provided.
        #
        # `Path(__file__).parent / namespace` (inside KnowledgeBase)
        # discards the left side when namespace is itself absolute, so an
        # absolute temp-dir path works as a "namespace" here — same trick
        # used in tests/test_knowledge_base_business_config.py.
        self.business_config = SimpleNamespace(
            persona=SimpleNamespace(
                identity_statement=(
                    "You are Nova, the automation specialist for Widget Co Automation.\n"
                    "You help widget sellers automate their support and fulfillment."
                ),
                response_style=SimpleNamespace(max_sentences=2),
            ),
            qualification=SimpleNamespace(
                fields=[
                    SimpleNamespace(id="name", prompt_hint="Ask for their name.", required=True),
                    SimpleNamespace(id="email", prompt_hint="Ask for their email.", required=True),
                    SimpleNamespace(
                        id="phone",
                        prompt_hint="Ask for a phone number for delivery updates.",
                        required=True,
                    ),
                ]
            ),
            knowledge=SimpleNamespace(namespace=str(knowledge_dir)),
        )

        class _StubBusinessConfigRepository:
            def __init__(self, config):
                self._config = config

            def load(self, business_id):
                return self._config

        self.repo = _StubBusinessConfigRepository(self.business_config)

    def test_engine_reflects_business_b_persona_and_qualification_not_kaivix(self):
        engine = ConversationEngine(
            business_id="business-b", business_config_repository=self.repo
        )
        _stub_llm(engine)
        captured = _spy_prompt_builder(engine)

        # Construction-time proof: the seam is wired before any message
        # is even processed.
        self.assertEqual(engine.business_id, "business-b")
        self.assertEqual(engine.qualification_engine.required_fields, ["name", "email", "phone"])
        self.assertNotEqual(engine.qualification_engine.required_fields, KAIVIX_REQUIRED_FIELDS)
        self.assertEqual(set(engine.knowledge.documents.keys()), {"widgets"})
        self.assertNotEqual(set(engine.knowledge.documents.keys()), KAIVIX_DOCUMENT_STEMS)

        engine.process_message(
            "conv-business-b-1", "Hi, I'm Dana and my email is dana@widgetco-test.com."
        )

        system_prompt = captured["output"]
        self.assertIn("Nova", system_prompt)
        self.assertIn("Widget Co Automation", system_prompt)
        self.assertNotIn("Bray", system_prompt)
        self.assertNotIn("Kaivix", system_prompt)

        # Missing-field prompting must reflect business-b's own schema
        # (phone required; budget/timeline are not, unlike Kaivix's).
        self.assertEqual(captured["kwargs"]["missing_fields"], ["phone"])
        self.assertNotIn("budget", captured["kwargs"]["missing_fields"])
        self.assertNotIn("timeline", captured["kwargs"]["missing_fields"])

    def test_lead_saved_through_business_b_does_not_leak_into_kaivix(self):
        engine = ConversationEngine(
            business_id="business-b", business_config_repository=self.repo
        )
        _stub_llm(engine)

        email = "dana@widgetco-test.com"
        engine.process_message(
            "conv-business-b-2", f"Hi, I'm Dana and my email is {email}."
        )

        crm = SQLiteCRM()
        self.assertIsNotNone(crm.get_lead_by_email(email, business_id="business-b"))
        self.assertIsNone(crm.get_lead_by_email(email, business_id=DEFAULT_BUSINESS_ID))

        long_term_memory = ltm_module.LongTermMemory()
        self.assertIsNotNone(long_term_memory.recall(email, business_id="business-b"))
        self.assertIsNone(long_term_memory.recall(email, business_id=DEFAULT_BUSINESS_ID))


if __name__ == "__main__":
    unittest.main()
