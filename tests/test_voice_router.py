"""
Vapi custom-LLM webhook (api/routers/voice.py).

Reuses _MultiBusinessMixin verbatim from tests/test_multi_business_serving.py
-- the same "swap chat_router_module.chat_service for a test-controlled
double, and patch BUSINESS_API_KEYS to a test-controlled value" approach
already established for the chat integration tests. voice.py accesses chat_router.chat_service and
chat_router.require_business_api_key as module ATTRIBUTES at call/request
time rather than binding local names at import time, so that swap reaches
voice.py's requests automatically -- no separate voice-specific mocking
mechanism was built.

What these tests are actually proving, per the four things this build was
asked for:
  1. A real webhook-shaped request (Vapi's documented OpenAI-compatible
     custom-LLM request body) reaches the right business's
     ConversationEngine, unmodified.
  2. The real response comes back in the correct
     (OpenAI chat.completion) shape.
  3. business_id scoping and the call.id -> conversation_id mapping work.
  4. Nothing here re-implements auth, validation, or engine logic --
     it is reused, and these tests exercise the reused paths rather than
     re-proving their internals (require_business_api_key's own auth
     matrix is exhaustively covered in tests/test_chat_business_auth.py
     and is not repeated here).
"""

import json
import unittest

from api.routers import chat as chat_router_module
from core_ai.business_config import DEFAULT_BUSINESS_ID
from memory.conversation_memory import ConversationMemory
from schemas.chat import MAX_MESSAGE_LENGTH
from tests.test_multi_business_serving import (
    BUSINESS_B,
    BUSINESS_B_IDENTITY,
    BUSINESS_B_KNOWLEDGE,
    _MultiBusinessMixin,
)

VOICE_URL = f"/voice/{BUSINESS_B}/chat/completions"


def _reassemble_sse_content(response) -> str:
    """
    Parse a `text/event-stream` chat.completion.chunk response the way a
    real SSE client (Vapi's own) actually does: join every frame's
    `delta.content` in order, stopping at the literal `data: [DONE]`
    line. `_vapi_request` sets `stream: True` by default -- matching a
    real Vapi request -- so this is what most of these tests need to
    read the full reply back with, now that the route honors that field
    instead of silently ignoring it (see api/routers/voice.py's module
    docstring for why that changed).
    """
    content = ""
    for line in response.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[len("data: "):]
        if payload == "[DONE]":
            break
        chunk = json.loads(payload)
        delta = chunk["choices"][0]["delta"]
        content += delta.get("content") or ""
    return content


def _vapi_request(
    user_text: str,
    call_id: str = "call_default",
    extra_messages: list[dict] | None = None,
    **overrides,
) -> dict:
    """
    A realistic Vapi custom-LLM request body, per
    https://docs.vapi.ai/customization/custom-llm/using-your-server and
    the VapiAI/example-server-javascript-deno reference implementations:
    model/messages/max_tokens/temperature/stream/call, with `call`
    carrying at least an `id` plus the other real fields Vapi's Call
    object documents (assistantId, phoneNumberId, customer, status, ...).
    """
    messages = (extra_messages or []) + [{"role": "user", "content": user_text}]
    payload = {
        "model": "gpt-4",
        "messages": messages,
        "max_tokens": 250,
        "temperature": 0.7,
        "stream": True,
        "call": {
            "id": call_id,
            "assistantId": "asst_test_1",
            "phoneNumberId": "pn_test_1",
            "type": "inboundPhoneCall",
            "status": "in-progress",
            "customer": {"number": "+15555550100"},
        },
    }
    payload.update(overrides)
    return payload


class TestWebhookReachesTheRightConversationEngine(_MultiBusinessMixin, unittest.TestCase):
    """Item 1: a real webhook-shaped request reaches ConversationEngine
    correctly -- the right business, with the visitor's real message."""

    def setUp(self):
        # Echoes the system prompt back as the "response", so the test can
        # assert on what actually reached the model -- the same pattern
        # TestPerBusinessRoute.test_response_reflects_business_b_persona_not_kaivix
        # already uses for /chat/{business_id}.
        self._setup_two_businesses()

    def test_request_reaches_business_bs_engine_not_kaivix(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("Do you take Delta Dental?", call_id="call_biz_1"),
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        content = _reassemble_sse_content(response)

        self.assertIn(BUSINESS_B_IDENTITY.splitlines()[0], content)
        self.assertNotIn("Bray", content)
        self.assertNotIn("Kaivix", content)

    def test_request_reaches_business_bs_knowledge_base(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("insurance and hours", call_id="call_biz_2"),
            headers=self.auth_headers(),
        )

        self.assertIn(
            BUSINESS_B_KNOWLEDGE,
            _reassemble_sse_content(response),
        )

    def test_call_id_becomes_the_conversation_id(self):
        """
        ConversationEngine tracks history per conversation_id. If call.id
        were not correctly threaded through, this turn would either land
        under the wrong id or under none at all.
        """
        self.client.post(
            VOICE_URL,
            json=_vapi_request("hello from the phone", call_id="call_xyz_789"),
            headers=self.auth_headers(),
        )

        stored = ConversationMemory(business_id=BUSINESS_B).get_conversation(
            "call_xyz_789"
        )
        self.assertEqual(
            [m for m in stored if m["role"] == "user"],
            [{"role": "user", "content": "hello from the phone"}],
        )

    def test_two_different_calls_do_not_share_history(self):
        self.client.post(
            VOICE_URL,
            json=_vapi_request("caller one message", call_id="call_one"),
            headers=self.auth_headers(),
        )
        self.client.post(
            VOICE_URL,
            json=_vapi_request("caller two message", call_id="call_two"),
            headers=self.auth_headers(),
        )

        memory = ConversationMemory(business_id=BUSINESS_B)
        call_one_text = " ".join(m["content"] for m in memory.get_conversation("call_one"))
        call_two_text = " ".join(m["content"] for m in memory.get_conversation("call_two"))

        self.assertIn("caller one message", call_one_text)
        self.assertNotIn("caller two message", call_one_text)
        self.assertIn("caller two message", call_two_text)
        self.assertNotIn("caller one message", call_two_text)

    def test_only_the_latest_user_message_is_fed_to_the_engine(self):
        """
        Vapi resends the FULL transcript on every request (stateless,
        OpenAI-style). ConversationEngine is stateful per conversation_id
        (it owns its own history). If the route naively fed the whole
        `messages` array through instead of just the newest utterance,
        earlier turns would be duplicated into ConversationMemory on
        every single request.
        """
        self.client.post(
            VOICE_URL,
            json=_vapi_request(
                "second real utterance",
                call_id="call_multiturn",
                extra_messages=[
                    {"role": "system", "content": "You are Nova."},
                    {"role": "user", "content": "first real utterance"},
                    {"role": "assistant", "content": "an earlier reply"},
                ],
            ),
            headers=self.auth_headers(),
        )

        stored = ConversationMemory(business_id=BUSINESS_B).get_conversation(
            "call_multiturn"
        )
        user_messages = [m["content"] for m in stored if m["role"] == "user"]

        # Only the newest utterance was handed to process_message and
        # stored -- "first real utterance" was never replayed in, and
        # Vapi's system/assistant transcript entries were not stored
        # either (ConversationEngine builds its own system prompt).
        self.assertEqual(user_messages, ["second real utterance"])


class TestResponseIsOpenAIChatCompletionShaped(_MultiBusinessMixin, unittest.TestCase):
    """
    Item 2: the real response comes back in the correct shape, for a
    non-streaming request (`stream: False`, explicit on every call here
    since `_vapi_request` defaults `stream` to True to model a real Vapi
    request -- see TestStreamingResponseIsOpenAISSEChunkShaped below for
    the shape a real request actually gets).
    """

    def setUp(self):
        self._setup_two_businesses(llm_stub=lambda messages: "the spoken reply")

    def test_top_level_shape_matches_openai_chat_completion(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_shape_1", stream=False),
            headers=self.auth_headers(),
        )

        body = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(body.keys()), {"id", "object", "created", "model", "choices"}
        )
        self.assertEqual(body["object"], "chat.completion")
        self.assertIsInstance(body["id"], str)
        self.assertTrue(body["id"])
        self.assertIsInstance(body["created"], int)

    def test_choice_shape_matches_openai(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_shape_2", stream=False),
            headers=self.auth_headers(),
        )

        choice = response.json()["choices"][0]
        self.assertEqual(choice["index"], 0)
        self.assertEqual(choice["finish_reason"], "stop")
        self.assertEqual(
            set(choice["message"].keys()), {"role", "content"}
        )
        self.assertEqual(choice["message"]["role"], "assistant")

    def test_response_content_is_the_engines_real_output_verbatim(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_shape_3", stream=False),
            headers=self.auth_headers(),
        )

        self.assertEqual(
            response.json()["choices"][0]["message"]["content"], "the spoken reply"
        )

    def test_response_ids_are_unique_per_request(self):
        first = self.client.post(
            VOICE_URL, json=_vapi_request("hi", call_id="call_id_1", stream=False),
            headers=self.auth_headers(),
        ).json()
        second = self.client.post(
            VOICE_URL, json=_vapi_request("hi again", call_id="call_id_1", stream=False),
            headers=self.auth_headers(),
        ).json()

        self.assertNotEqual(first["id"], second["id"])


class TestStreamingResponseIsOpenAISSEChunkShaped(_MultiBusinessMixin, unittest.TestCase):
    """
    A real live call proved Vapi's own client parses zero content out of
    a flat JSON body when its request sets `stream: true` (the default),
    despite Vapi's docs claiming both response shapes are accepted --
    see api/routers/voice.py's module docstring for the full trace from
    that call's own event log. These tests cover the SSE shape the route
    now sends instead, which `_vapi_request`'s default `stream: True`
    exercises without needing to pass it explicitly.
    """

    def setUp(self):
        self._setup_two_businesses(llm_stub=lambda messages: "the spoken reply")

    def test_stream_true_returns_sse_not_json(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_stream_1"),
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])

    def test_chunks_reassemble_to_the_engines_real_output_verbatim(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_stream_2"),
            headers=self.auth_headers(),
        )

        self.assertEqual(_reassemble_sse_content(response), "the spoken reply")

    def test_first_chunk_carries_the_assistant_role(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_stream_3"),
            headers=self.auth_headers(),
        )

        first_data_line = next(
            line for line in response.text.splitlines() if line.startswith("data: ")
        )
        first_chunk = json.loads(first_data_line[len("data: "):])
        self.assertEqual(
            first_chunk["choices"][0]["delta"]["role"], "assistant"
        )

    def test_stream_ends_with_a_finish_reason_chunk_then_done(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_stream_4"),
            headers=self.auth_headers(),
        )

        data_lines = [
            line[len("data: "):]
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

        self.assertEqual(data_lines[-1], "[DONE]")
        final_chunk = json.loads(data_lines[-2])
        self.assertEqual(final_chunk["choices"][0]["finish_reason"], "stop")
        self.assertIsNone(final_chunk["choices"][0]["delta"].get("content"))

    def test_every_chunk_is_chat_completion_chunk_object_type(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_stream_5"),
            headers=self.auth_headers(),
        )

        for line in response.text.splitlines():
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            chunk = json.loads(line[len("data: "):])
            self.assertEqual(chunk["object"], "chat.completion.chunk")


class TestRequestValidation(_MultiBusinessMixin, unittest.TestCase):
    def setUp(self):
        self._setup_two_businesses(llm_stub=lambda messages: "ok")

    def test_missing_call_object_is_400(self):
        payload = _vapi_request("hi")
        del payload["call"]

        response = self.client.post(
            VOICE_URL, json=payload, headers=self.auth_headers()
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("call", response.json()["error"]["message"].lower())

    def test_no_user_role_message_is_400(self):
        payload = _vapi_request("unused")
        payload["messages"] = [
            {"role": "system", "content": "You are Nova."},
            {"role": "assistant", "content": "Hi, how can I help?"},
        ]

        response = self.client.post(
            VOICE_URL, json=payload, headers=self.auth_headers()
        )

        self.assertEqual(response.status_code, 400)

    def test_oversized_message_is_400_same_as_chat(self):
        """Reuses api/routers/chat.py's own guard -- same limit, same
        behaviour, not a second implementation."""
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("x" * (MAX_MESSAGE_LENGTH + 1), call_id="call_big"),
            headers=self.auth_headers(),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn(str(MAX_MESSAGE_LENGTH), response.json()["error"]["message"])

    def test_unknown_business_id_is_404_not_500(self):
        response = self.client.post(
            "/voice/no-such-business/chat/completions",
            json=_vapi_request("hi", call_id="call_unknown"),
            headers=self.auth_headers("no-such-business"),
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn("no-such-business", response.json()["error"]["message"])

    def test_full_realistic_vapi_payload_with_unknown_extra_fields_is_accepted(self):
        """
        Vapi's request is OpenAI-request-shaped and can carry fields this
        integration has no use for (tools, top_p, an added field Vapi
        introduces later). None of that should ever turn into a 422.
        """
        payload = _vapi_request("hi", call_id="call_extra")
        payload["tools"] = []
        payload["top_p"] = 1
        payload["call"]["cost"] = 0.0
        payload["call"]["somethingVapiAddsLater"] = {"nested": True}
        payload["somethingElseEntirely"] = "ignored"

        response = self.client.post(
            VOICE_URL, json=payload, headers=self.auth_headers()
        )

        self.assertEqual(response.status_code, 200)


class TestVoiceRouteAuthenticationIsReused(_MultiBusinessMixin, unittest.TestCase):
    """
    Not a re-proof of require_business_api_key's own behaviour (that is
    tests/test_chat_business_auth.py's job, exhaustively) -- just proof
    that voice.py actually wires the SAME dependency in, the same way
    /chat/{business_id} does.
    """

    def setUp(self):
        self._setup_two_businesses(llm_stub=lambda messages: "ok")

    def test_missing_key_is_401(self):
        response = self.client.post(
            VOICE_URL, json=_vapi_request("hi", call_id="call_noauth")
        )
        self.assertEqual(response.status_code, 401)

    def test_missing_key_never_reaches_the_engine(self):
        calls = []
        engine = self.service.get_engine(BUSINESS_B)
        engine.llm.generate = lambda messages: calls.append(messages) or "x"

        self.client.post(VOICE_URL, json=_vapi_request("hi", call_id="call_noauth2"))

        self.assertEqual(calls, [])

    def test_valid_business_b_key_is_accepted(self):
        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_authok"),
            headers=self.auth_headers(BUSINESS_B),
        )
        self.assertEqual(response.status_code, 200)

    def test_kaivix_key_does_not_unlock_business_b(self):
        kaivix_key = self.issue_key(DEFAULT_BUSINESS_ID)

        response = self.client.post(
            VOICE_URL,
            json=_vapi_request("hi", call_id="call_cross"),
            headers={"X-API-Key": kaivix_key},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
