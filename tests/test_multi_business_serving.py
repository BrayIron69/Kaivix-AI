"""
One process serving more than one business.

ConversationEngine was already correctly business_id-scoped end to end
(Decision #011): QualificationEngine, KnowledgeBase, CRM, LongTermMemory,
ConversationMemory and calendar tokens all take business_id. What was
missing lived entirely at the serving layer -- ChatService held exactly ONE
engine, and /chat had no concept of which business a request was for.

These tests cover that layer only. Nothing in core_ai/ was changed to make
this work, which is itself the evidence that the isolation was already
complete.

The single most important test here is
TestPlainChatEndpointUnchanged.test_response_is_byte_identical: the live
marketing widget posts to plain /chat, so a regression there is a
production outage.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import crm.database as crm_database
import memory.conversation_store as conversation_store_module
import memory.long_term_memory as ltm_module
from api.main import app
from api.routers import chat as chat_router_module
from core_ai.business_config import DEFAULT_BUSINESS_ID
from core_ai.conversation_engine import ConversationEngine
from crm.sqlite_crm import SQLiteCRM
from schemas.chat import MAX_MESSAGE_LENGTH
from services.chat_service import ChatService

BUSINESS_B = "test-business-b"

# Distinct enough from Kaivix's persona that a mix-up is unmissable.
BUSINESS_B_IDENTITY = (
    "You are Nova, the scheduling coordinator for Ridgeline Dental.\n"
    "You help patients book cleanings and answer insurance questions."
)
BUSINESS_B_KNOWLEDGE = (
    "Ridgeline Dental accepts Delta Dental and opens late on Thursdays."
)


class _IsolatedDatabasesMixin:
    """
    Points the CRM, long-term-memory and conversation stores at fresh temp
    files, so constructing real engines never touches crm/leads.db,
    memory/long_term_memory.db or memory/conversation_memory.db.

    Extends the mixin in tests/test_conversation_engine_business_config.py
    with the conversation store, which these tests need because they assert
    on per-business conversation history.
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


class _RepositoryReturning:
    """Stands in for BusinessConfigRepository, returning a fixed config."""

    def __init__(self, config):
        self._config = config

    def load(self, business_id):
        return self._config


class _MultiBusinessMixin(_IsolatedDatabasesMixin):
    """
    Builds a synthetic second business and swaps the router's module-level
    ChatService for one wired to it.

    business-b is a SimpleNamespace stand-in plus a temp knowledge dir --
    the same pattern the existing business-scoping tests use. Deliberately
    no config/businesses/test-business-b/ directory is created: no real
    second business exists, and inventing config files for a fake one would
    leave real artifacts behind.
    """

    def _setup_two_businesses(self, llm_stub=None):
        self._isolate_databases()

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        knowledge_dir = Path(tmp.name)
        (knowledge_dir / "clinic.md").write_text(BUSINESS_B_KNOWLEDGE, encoding="utf-8")

        # KnowledgeBase does Path(__file__).parent / namespace, which discards
        # the left side when namespace is absolute -- so an absolute temp path
        # works as a namespace here.
        self.business_b_config = SimpleNamespace(
            persona=SimpleNamespace(
                identity_statement=BUSINESS_B_IDENTITY,
                response_style=SimpleNamespace(max_sentences=2),
            ),
            qualification=SimpleNamespace(
                fields=[
                    SimpleNamespace(id="name", prompt_hint="Ask their name.", required=True),
                    SimpleNamespace(id="email", prompt_hint="Ask their email.", required=True),
                ]
            ),
            knowledge=SimpleNamespace(namespace=str(knowledge_dir)),
            providers=SimpleNamespace(
                llm_provider="groq",
                crm_provider="sqlite",
                calendar_provider="none",
                knowledge_provider="file",
            ),
            tools=SimpleNamespace(enabled_tools=[]),
        )

        # Returns the system prompt as the "response" so tests can assert on
        # what actually reached the model, and never calls Groq.
        default_stub = llm_stub or (lambda messages: messages[0]["content"])

        def factory(business_id):
            if business_id == BUSINESS_B:
                engine = ConversationEngine(
                    business_id=business_id,
                    business_config_repository=_RepositoryReturning(
                        self.business_b_config
                    ),
                )
            else:
                engine = ConversationEngine(business_id=business_id)
            engine.llm.generate = default_stub
            return engine

        self.service = ChatService(engine_factory=factory)

        original_service = chat_router_module.chat_service
        chat_router_module.chat_service = self.service
        self.addCleanup(
            lambda: setattr(chat_router_module, "chat_service", original_service)
        )

        self.client = TestClient(app)


class TestEngineCacheBehaviour(_MultiBusinessMixin, unittest.TestCase):
    def setUp(self):
        self._setup_two_businesses()

    def test_no_engine_is_built_until_requested(self):
        """Requirement 1: nothing eager. A business nobody messaged costs nothing."""
        self.assertEqual(self.service.cached_business_ids, [])

    def test_engine_is_built_on_first_request_and_cached(self):
        first = self.service.get_engine(BUSINESS_B)
        second = self.service.get_engine(BUSINESS_B)

        self.assertIs(first, second)
        self.assertEqual(self.service.cached_business_ids, [BUSINESS_B])

    def test_distinct_businesses_get_distinct_engines(self):
        kaivix = self.service.get_engine(DEFAULT_BUSINESS_ID)
        business_b = self.service.get_engine(BUSINESS_B)

        self.assertIsNot(kaivix, business_b)
        self.assertEqual(kaivix.business_id, DEFAULT_BUSINESS_ID)
        self.assertEqual(business_b.business_id, BUSINESS_B)
        self.assertEqual(
            self.service.cached_business_ids,
            sorted([DEFAULT_BUSINESS_ID, BUSINESS_B]),
        )

    def test_requesting_business_b_does_not_build_kaivix(self):
        self.service.get_engine(BUSINESS_B)
        self.assertNotIn(DEFAULT_BUSINESS_ID, self.service.cached_business_ids)

    def test_engine_property_still_resolves_to_the_default_business(self):
        """The pre-change public surface of ChatService."""
        self.assertIs(
            self.service.engine, self.service.get_engine(DEFAULT_BUSINESS_ID)
        )


class TestPerBusinessRoute(_MultiBusinessMixin, unittest.TestCase):
    """Requirement 4a: business-b's conversation reflects business-b."""

    def setUp(self):
        self._setup_two_businesses()

    def test_route_exists_and_succeeds(self):
        response = self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": "b_conv_1", "message": "Do you take Delta Dental?"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_response_reflects_business_b_persona_not_kaivix(self):
        response = self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": "b_conv_2", "message": "Hello"},
        )

        body = response.json()["response"]
        self.assertIn("Nova", body)
        self.assertIn("Ridgeline Dental", body)
        # Kaivix's own persona must be nowhere in it.
        self.assertNotIn("Bray", body)
        self.assertNotIn("Kaivix", body)

    def test_response_reflects_business_b_knowledge_not_kaivix(self):
        response = self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": "b_conv_3", "message": "insurance and hours"},
        )

        self.assertIn("Delta Dental", response.json()["response"])

    def test_same_shape_as_plain_chat(self):
        """Requirement 2: identical request/response shape."""
        plain = self.client.post(
            "/chat", json={"conversation_id": "shape_a", "message": "Hi"}
        ).json()
        scoped = self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": "shape_b", "message": "Hi"},
        ).json()

        self.assertEqual(set(plain.keys()), set(scoped.keys()))
        self.assertEqual(set(plain.keys()), {"success", "conversation_id", "response"})

    def test_unknown_business_id_is_404_not_500(self):
        """
        A typo'd business_id in the URL is a client error. Without explicit
        handling, BusinessConfigError would surface as a bare 500.
        """
        response = self.client.post(
            "/chat/no-such-business",
            json={"conversation_id": "missing_1", "message": "Hi"},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("no-such-business", response.json()["error"]["message"])


class TestPlainChatEndpointUnchanged(_MultiBusinessMixin, unittest.TestCase):
    """
    Requirement 4c -- the most important tests in this file.

    chat_widget.html on the live marketing site posts to plain /chat with no
    business_id. This change is additive; if any of these fail, production
    is broken.
    """

    def setUp(self):
        # A fixed stub, so the response body is exactly predictable.
        self._setup_two_businesses(llm_stub=lambda messages: "stubbed-response")

    def test_plain_chat_still_returns_200(self):
        response = self.client.post(
            "/chat", json={"conversation_id": "conv_001", "message": "Hi"}
        )
        self.assertEqual(response.status_code, 200)

    def test_response_is_byte_identical(self):
        """
        The exact JSON body the widget has always received. Compared as
        bytes, including key order, not as a parsed dict.
        """
        response = self.client.post(
            "/chat", json={"conversation_id": "conv_001", "message": "Hi"}
        )

        expected = json.dumps(
            {
                "success": True,
                "conversation_id": "conv_001",
                "response": "stubbed-response",
            },
            separators=(",", ":"),
        ).encode()

        self.assertEqual(response.content, expected)

    def test_plain_chat_routes_to_the_default_business(self):
        self.client.post(
            "/chat", json={"conversation_id": "conv_002", "message": "Hi"}
        )
        self.assertEqual(self.service.cached_business_ids, [DEFAULT_BUSINESS_ID])

    def test_plain_chat_never_builds_another_business_engine(self):
        for i in range(3):
            self.client.post(
                "/chat", json={"conversation_id": f"conv_{i}", "message": "Hi"}
            )
        self.assertEqual(self.service.cached_business_ids, [DEFAULT_BUSINESS_ID])

    def test_two_argument_service_call_still_works(self):
        """The original ChatService.chat(conversation_id, message) signature."""
        self.assertEqual(
            self.service.chat(conversation_id="conv_legacy", message="Hi"),
            "stubbed-response",
        )

    def test_widget_payload_shape_is_accepted(self):
        """
        Exactly the body chat_widget.html sends: conversation_id + message,
        nothing else.
        """
        response = self.client.post(
            "/chat",
            json={"conversation_id": "session_abc123", "message": "Hey, just landed on your website"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], "session_abc123")


class TestCrossBusinessLeadIsolation(_MultiBusinessMixin, unittest.TestCase):
    """
    Requirement 4b: a lead captured through one business's conversation must
    not appear in the other's CRM records. Reuses the isolation-proof shape
    of tests/test_crm_business_scoping.py.
    """

    def setUp(self):
        self._setup_two_businesses()

    def test_lead_from_business_b_does_not_appear_in_kaivix(self):
        email = "nadia@ridgeline-test.com"

        self.client.post(
            f"/chat/{BUSINESS_B}",
            json={
                "conversation_id": "b_lead_1",
                "message": f"Hi, I'm Nadia and my email is {email}.",
            },
        )

        crm = SQLiteCRM()
        self.assertIsNotNone(crm.get_lead_by_email(email, business_id=BUSINESS_B))
        self.assertIsNone(
            crm.get_lead_by_email(email, business_id=DEFAULT_BUSINESS_ID)
        )

        # Long-term memory is scoped the same way, and the original
        # business-scoping tests assert both together.
        long_term_memory = ltm_module.LongTermMemory()
        self.assertIsNotNone(long_term_memory.recall(email, business_id=BUSINESS_B))
        self.assertIsNone(
            long_term_memory.recall(email, business_id=DEFAULT_BUSINESS_ID)
        )

    def test_lead_from_kaivix_does_not_appear_in_business_b(self):
        email = "tom@kaivixclient-test.com"

        self.client.post(
            "/chat",
            json={
                "conversation_id": "k_lead_1",
                "message": f"Hi, I'm Tom and my email is {email}.",
            },
        )

        crm = SQLiteCRM()
        self.assertIsNotNone(
            crm.get_lead_by_email(email, business_id=DEFAULT_BUSINESS_ID)
        )
        self.assertIsNone(crm.get_lead_by_email(email, business_id=BUSINESS_B))

    def test_same_email_in_both_businesses_stays_two_separate_records(self):
        """
        The sharpest version of the isolation claim: an identical email in
        both businesses must not collapse into one shared lead. Distinct
        names prove they are genuinely two records, not one seen twice.
        """
        shared = "same.person@example.com"

        self.client.post(
            "/chat",
            json={
                "conversation_id": "shared_k",
                "message": f"Hi, I'm Kaivixname and my email is {shared}.",
            },
        )
        self.client.post(
            f"/chat/{BUSINESS_B}",
            json={
                "conversation_id": "shared_b",
                "message": f"Hi, I'm Beename and my email is {shared}.",
            },
        )

        crm = SQLiteCRM()
        kaivix_lead = crm.get_lead_by_email(shared, business_id=DEFAULT_BUSINESS_ID)
        b_lead = crm.get_lead_by_email(shared, business_id=BUSINESS_B)

        self.assertIsNotNone(kaivix_lead)
        self.assertIsNotNone(b_lead)
        self.assertNotEqual(kaivix_lead.name, b_lead.name)


class TestNoStateLeakBetweenEngines(_MultiBusinessMixin, unittest.TestCase):
    """
    Requirement 4d: two engines live in one process without one's state
    reaching the other -- even when they share a conversation_id, which is
    the case most likely to collide.
    """

    def setUp(self):
        self._setup_two_businesses()

    def test_conversation_history_is_not_shared_across_businesses(self):
        shared_conversation_id = "collision_conv"

        self.client.post(
            "/chat",
            json={"conversation_id": shared_conversation_id, "message": "KAIVIX_ONLY_MARKER"},
        )
        self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": shared_conversation_id, "message": "BUSINESS_B_ONLY_MARKER"},
        )

        kaivix_history = self.service.get_engine(DEFAULT_BUSINESS_ID).memory.get_conversation(
            shared_conversation_id
        )
        b_history = self.service.get_engine(BUSINESS_B).memory.get_conversation(
            shared_conversation_id
        )

        kaivix_text = " ".join(m["content"] for m in kaivix_history)
        b_text = " ".join(m["content"] for m in b_history)

        self.assertIn("KAIVIX_ONLY_MARKER", kaivix_text)
        self.assertNotIn("BUSINESS_B_ONLY_MARKER", kaivix_text)

        self.assertIn("BUSINESS_B_ONLY_MARKER", b_text)
        self.assertNotIn("KAIVIX_ONLY_MARKER", b_text)

    def test_engines_do_not_share_component_instances(self):
        kaivix = self.service.get_engine(DEFAULT_BUSINESS_ID)
        business_b = self.service.get_engine(BUSINESS_B)

        for attribute in (
            "memory",
            "knowledge",
            "qualification_engine",
            "planning_engine",
            "memory_manager",
            "lead_service",
            "_lead_profiles",
        ):
            self.assertIsNot(
                getattr(kaivix, attribute),
                getattr(business_b, attribute),
                msg=f"{attribute} is shared between engines",
            )

    def test_lead_profiles_do_not_leak(self):
        shared_conversation_id = "profile_collision"

        self.client.post(
            "/chat",
            json={
                "conversation_id": shared_conversation_id,
                "message": "I'm Kaivix Person, email kp@example.com",
            },
        )
        self.client.post(
            f"/chat/{BUSINESS_B}",
            json={
                "conversation_id": shared_conversation_id,
                "message": "I'm Bee Person, email bp@example.com",
            },
        )

        kaivix_profiles = self.service.get_engine(DEFAULT_BUSINESS_ID)._lead_profiles
        b_profiles = self.service.get_engine(BUSINESS_B)._lead_profiles

        self.assertEqual(
            kaivix_profiles[shared_conversation_id].email, "kp@example.com"
        )
        self.assertEqual(b_profiles[shared_conversation_id].email, "bp@example.com")

    def test_business_b_qualification_schema_is_its_own(self):
        kaivix = self.service.get_engine(DEFAULT_BUSINESS_ID)
        business_b = self.service.get_engine(BUSINESS_B)

        self.assertEqual(
            business_b.qualification_engine.required_fields, ["name", "email"]
        )
        self.assertNotEqual(
            kaivix.qualification_engine.required_fields,
            business_b.qualification_engine.required_fields,
        )


class TestMessageLengthCap(_MultiBusinessMixin, unittest.TestCase):
    """
    Security item 3c. There was no cap, so one request could push an
    arbitrarily large body into the prompt and burn a large amount of token
    budget in a single call.
    """

    def setUp(self):
        self._setup_two_businesses(llm_stub=lambda messages: "stubbed-response")

    def test_message_at_the_limit_is_accepted(self):
        response = self.client.post(
            "/chat",
            json={"conversation_id": "len_ok", "message": "x" * MAX_MESSAGE_LENGTH},
        )
        self.assertEqual(response.status_code, 200)

    def test_message_one_over_the_limit_is_rejected(self):
        response = self.client.post(
            "/chat",
            json={"conversation_id": "len_bad", "message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        )
        self.assertEqual(response.status_code, 400)

    def test_rejection_says_what_the_limit_is(self):
        oversized = "x" * (MAX_MESSAGE_LENGTH + 500)
        response = self.client.post(
            "/chat", json={"conversation_id": "len_msg", "message": oversized}
        )

        message = response.json()["error"]["message"]
        self.assertIn(str(MAX_MESSAGE_LENGTH), message)
        self.assertIn(str(len(oversized)), message)

    def test_cap_applies_to_the_per_business_route_too(self):
        """A new route must not be able to skip the cap."""
        response = self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": "len_b", "message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        )
        self.assertEqual(response.status_code, 400)

    def test_oversized_request_never_reaches_the_model(self):
        """The whole point: rejected before any token is spent."""
        calls = []

        engine = self.service.get_engine(DEFAULT_BUSINESS_ID)
        engine.llm.generate = lambda messages: calls.append(messages) or "x"

        self.client.post(
            "/chat",
            json={"conversation_id": "len_nocall", "message": "x" * (MAX_MESSAGE_LENGTH + 1)},
        )

        self.assertEqual(calls, [])

    def test_empty_message_is_still_rejected_by_schema(self):
        """Pre-existing min_length=1 behaviour is unchanged."""
        response = self.client.post(
            "/chat", json={"conversation_id": "len_empty", "message": ""}
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
