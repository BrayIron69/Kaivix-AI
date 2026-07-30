"""
providers.yaml actually drives provider selection.

Before this, config/businesses/<id>/providers.yaml was loaded and validated
by BusinessConfig and then never read. ConversationEngine did:

    self.llm = LLM()                 # always Groq
    self.lead_service = LeadService() # always SQLiteCRM

so llm_provider / crm_provider were decorative -- a business could declare
any value and get Groq + SQLite regardless.

The point of these tests is to prove *selection*, not merely that the field
is read. Asserting "config says groq and we got Groq" would pass even if the
code still hardcoded Groq and ignored the field entirely. So each test
registers a second, distinct stub provider and proves a config naming it
yields THAT class -- which is only possible if the value is genuinely
dispatched on.
"""

import unittest
from types import SimpleNamespace

from core_ai.business_config import (
    BusinessConfig,
    BusinessConfigRepository,
    DEFAULT_BUSINESS_ID,
    ProvidersConfig,
)
from core_ai.conversation_engine import ConversationEngine
from crm.base_crm import BaseCRM
from crm.registry import (
    UnknownCRMProviderError,
    available_crm_providers,
    get_crm_provider,
    get_crm_provider_class,
    register_crm_provider,
)
from crm.sqlite_crm import SQLiteCRM
from services.lead_service import LeadService
from utils.llm import LLM
from utils.llm_provider import (
    BaseLLMProvider,
    UnknownLLMProviderError,
    available_llm_providers,
    get_llm_provider,
    get_llm_provider_class,
    register_llm_provider,
)


# --------------------------------------------------------------------------
# Stub providers. Hypothetical on purpose -- no second real provider exists
# yet, and the seam has to be provable without inventing one.
# --------------------------------------------------------------------------

class StubEchoLLM(BaseLLMProvider):
    """Distinct from Groq in a way a test can observe."""

    def generate(self, messages: list[dict]) -> str:
        return "stub-echo-provider-response"


class StubMemoryCRM(BaseCRM):
    """In-memory CRM implementing the full BaseCRM contract."""

    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}

    def save_lead(self, lead: dict, business_id: str = DEFAULT_BUSINESS_ID):
        key = (lead.get("email", ""), business_id)
        self.rows[key] = dict(lead)
        return self.rows[key]

    def get_lead_by_email(self, email: str, business_id: str = DEFAULT_BUSINESS_ID):
        return self.rows.get((email, business_id))

    def get_all_leads(self, business_id: str = DEFAULT_BUSINESS_ID):
        return [v for (_, b), v in self.rows.items() if b == business_id]

    def update_lead(self, email: str, business_id: str = DEFAULT_BUSINESS_ID, **updates):
        row = self.rows.setdefault((email, business_id), {"email": email})
        row.update(updates)
        return row

    def delete_lead(self, email: str, business_id: str = DEFAULT_BUSINESS_ID):
        return self.rows.pop((email, business_id), None) is not None


def _business_config_with_providers(providers: ProvidersConfig) -> BusinessConfig:
    """
    A real Kaivix BusinessConfig with only the providers section swapped.

    Everything else stays genuine so the engine constructs normally; the one
    varying axis is the thing under test.
    """
    base = BusinessConfigRepository().load(DEFAULT_BUSINESS_ID)
    return base.model_copy(update={"providers": providers}, deep=True)


class _RepositoryReturning:
    """Stands in for BusinessConfigRepository, returning a fixed config."""

    def __init__(self, config: BusinessConfig):
        self._config = config

    def load(self, business_id: str) -> BusinessConfig:
        return self._config


class ProviderRegistryTestCase(unittest.TestCase):
    """Registers stubs in setUp and removes them again in tearDown."""

    def setUp(self):
        register_llm_provider("stub-echo", StubEchoLLM)
        register_crm_provider("stub-memory", StubMemoryCRM)

    def tearDown(self):
        # Reach into the registries to undo the test-only registrations, so
        # provider names never leak between tests.
        import crm.registry as crm_registry
        import utils.llm_provider as llm_registry

        llm_registry._REGISTRY.pop("stub-echo", None)
        crm_registry._REGISTRY.pop("stub-memory", None)


class TestLLMProviderSelection(ProviderRegistryTestCase):
    def test_registry_resolves_distinct_names_to_distinct_classes(self):
        self.assertIs(get_llm_provider_class("groq"), LLM)
        self.assertIs(get_llm_provider_class("stub-echo"), StubEchoLLM)

    def test_engine_selects_the_provider_named_in_config(self):
        """
        The load-bearing test. A config naming stub-echo must produce
        StubEchoLLM -- impossible unless the field is dispatched on.
        """
        config = _business_config_with_providers(
            ProvidersConfig(llm_provider="stub-echo")
        )

        engine = ConversationEngine(
            business_config_repository=_RepositoryReturning(config)
        )

        self.assertIsInstance(engine.llm, StubEchoLLM)
        self.assertNotIsInstance(engine.llm, LLM)
        self.assertEqual(
            engine.llm.generate([{"role": "user", "content": "hi"}]),
            "stub-echo-provider-response",
        )

    def test_engine_selects_groq_when_config_says_groq(self):
        """The other side of the same dispatch, so the pair is meaningful."""
        config = _business_config_with_providers(
            ProvidersConfig(llm_provider="groq")
        )

        engine = ConversationEngine(
            business_config_repository=_RepositoryReturning(config)
        )

        self.assertIsInstance(engine.llm, LLM)
        self.assertNotIsInstance(engine.llm, StubEchoLLM)

    def test_provider_name_is_case_and_whitespace_insensitive(self):
        """providers.yaml is hand-edited; "Groq" should not be a hard error."""
        self.assertIs(get_llm_provider_class("  GROQ "), LLM)

    def test_unknown_provider_fails_loudly_at_construction(self):
        """
        A typo must not silently fall back to Groq -- serving a different
        provider than the config records is worse than refusing to start.
        """
        config = _business_config_with_providers(
            ProvidersConfig(llm_provider="does-not-exist")
        )

        with self.assertRaises(UnknownLLMProviderError) as caught:
            ConversationEngine(
                business_config_repository=_RepositoryReturning(config)
            )

        self.assertIn("does-not-exist", str(caught.exception))

    def test_registering_a_non_provider_is_rejected(self):
        class NotAProvider:
            pass

        with self.assertRaises(TypeError):
            register_llm_provider("bad", NotAProvider)

    def test_groq_is_registered_by_default(self):
        self.assertIn("groq", available_llm_providers())


class TestCRMProviderSelection(ProviderRegistryTestCase):
    def test_registry_resolves_distinct_names_to_distinct_classes(self):
        self.assertIs(get_crm_provider_class("sqlite"), SQLiteCRM)
        self.assertIs(get_crm_provider_class("stub-memory"), StubMemoryCRM)

    def test_engine_selects_the_crm_named_in_config(self):
        config = _business_config_with_providers(
            ProvidersConfig(crm_provider="stub-memory")
        )

        engine = ConversationEngine(
            business_config_repository=_RepositoryReturning(config)
        )

        self.assertIsInstance(engine.lead_service.crm, StubMemoryCRM)
        self.assertNotIsInstance(engine.lead_service.crm, SQLiteCRM)

    def test_engine_selects_sqlite_when_config_says_sqlite(self):
        config = _business_config_with_providers(
            ProvidersConfig(crm_provider="sqlite")
        )

        engine = ConversationEngine(
            business_config_repository=_RepositoryReturning(config)
        )

        self.assertIsInstance(engine.lead_service.crm, SQLiteCRM)

    def test_unknown_crm_provider_fails_loudly(self):
        with self.assertRaises(UnknownCRMProviderError):
            get_crm_provider("nope")

    def test_lead_service_default_is_unchanged_sqlite(self):
        """
        LeadService() with no arguments must behave exactly as it did when
        SQLiteCRM was hardcoded in its __init__ -- admin routers and tests
        construct it that way.
        """
        self.assertIsInstance(LeadService().crm, SQLiteCRM)

    def test_lead_service_accepts_an_injected_crm(self):
        stub = StubMemoryCRM()
        service = LeadService(crm=stub)
        self.assertIs(service.crm, stub)

    def test_sqlite_is_registered_by_default(self):
        self.assertIn("sqlite", available_crm_providers())


class TestBaseCRMContractIsComplete(unittest.TestCase):
    """
    BaseCRM previously declared save_lead alone while LeadService called
    five methods, so a partial implementation could satisfy the ABC and
    still break at runtime. These pin the full contract.
    """

    REQUIRED = [
        "save_lead",
        "get_lead_by_email",
        "get_all_leads",
        "update_lead",
        "delete_lead",
    ]

    def test_every_method_leadservice_calls_is_abstract(self):
        self.assertEqual(
            set(BaseCRM.__abstractmethods__), set(self.REQUIRED)
        )

    def test_partial_implementation_cannot_be_instantiated(self):
        class HalfCRM(BaseCRM):
            def save_lead(self, lead, business_id=DEFAULT_BUSINESS_ID):
                return lead

        with self.assertRaises(TypeError):
            HalfCRM()

    def test_sqlite_crm_satisfies_the_full_contract(self):
        self.assertFalse(getattr(SQLiteCRM, "__abstractmethods__", frozenset()))


class TestKaivixBehaviourUnchanged(unittest.TestCase):
    """
    Requirement 2d: zero behaviour change for Kaivix. Its own providers.yaml
    says groq + sqlite, which must resolve to exactly what was hardcoded
    before.
    """

    def test_kaivix_config_still_declares_groq_and_sqlite(self):
        providers = BusinessConfigRepository().load(DEFAULT_BUSINESS_ID).providers
        self.assertEqual(providers.llm_provider, "groq")
        self.assertEqual(providers.crm_provider, "sqlite")

    def test_default_engine_uses_the_previously_hardcoded_classes(self):
        engine = ConversationEngine()
        self.assertIsInstance(engine.llm, LLM)
        self.assertIsInstance(engine.lead_service.crm, SQLiteCRM)

    def test_engine_llm_is_still_stubbable_the_way_existing_tests_do_it(self):
        """
        Existing tests replace engine.llm.generate with a lambda. The
        attribute name and call signature must survive the refactor.
        """
        engine = ConversationEngine()
        engine.llm.generate = lambda messages: "stubbed-response"
        self.assertEqual(engine.llm.generate([]), "stubbed-response")


if __name__ == "__main__":
    unittest.main()
