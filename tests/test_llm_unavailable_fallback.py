"""
Graceful degradation when the LLM provider is down.

Before this, utils/llm.py called Groq with no exception handling at all and
the chat path had no handler above it. When the Groq quota was exhausted the
call raised, nothing caught it, and api/handlers/exceptions.py's catch-all
flattened it into:

    HTTP 500 {"success": false, "error": {"code": 500,
                                          "message": "Internal Server Error"}}

That is what the live deployment was returning -- /health stayed 200 because
it never touches the LLM, so nothing alerted. Every visitor who opened the
widget got a dead end.

These tests pin the replacement behaviour:
  * the provider's own exception types never escape utils/llm.py
  * a real bug is still a real bug and is NOT masked as an outage
  * the endpoint answers 503 + a usable message, not 500
  * secrets never reach the log line written on the failure path
"""

import unittest
from types import SimpleNamespace

import httpx
from fastapi.testclient import TestClient

import groq

from api.handlers.exceptions import LLM_UNAVAILABLE_MESSAGE
from api.main import app
from api.routers import chat as chat_router_module
from utils.exceptions import LLMUnavailableError
from utils.llm import LLM


# Deliberately does NOT use Groq's real "gsk_" key prefix: this string is
# committed, and a realistic-looking prefix trips secret scanners (GitHub
# push protection would block the push). Its only job is to be a distinctive
# needle we can assert is absent from the log output.
SENTINEL_API_KEY = "NOT-A-REAL-KEY-llm-fallback-test-sentinel-0000"

_REQUEST = httpx.Request(
    "POST", "https://api.groq.com/openai/v1/chat/completions"
)


def _status_error(cls, status_code, message="provider said no"):
    """Build a real groq APIStatusError subclass with an HTTP status."""
    return cls(
        message,
        response=httpx.Response(status_code, request=_REQUEST),
        body=None,
    )


def _llm_raising(error):
    """
    An LLM instance whose underlying Groq client raises `error`.

    Builds the object without __init__ so no real Groq client (and no API
    key) is required, then installs a stub client.
    """
    llm = LLM.__new__(LLM)

    def _create(**kwargs):
        raise error

    llm.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
    )
    return llm


class TestProviderErrorsAreTranslated(unittest.TestCase):
    """
    Every GroqError subclass must surface as LLMUnavailableError. GroqError
    is the single base class for all of them, which is why one except clause
    is sufficient -- this test pins that assumption so a future provider
    swap can't silently regress it.
    """

    def test_rate_limit_becomes_llm_unavailable(self):
        """The actual production failure: quota exhausted -> 429."""
        llm = _llm_raising(_status_error(groq.RateLimitError, 429))

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertEqual(caught.exception.provider, "groq")
        self.assertEqual(caught.exception.reason, "RateLimitError")
        self.assertEqual(caught.exception.status_code, 429)

    def test_authentication_error_becomes_llm_unavailable(self):
        llm = _llm_raising(_status_error(groq.AuthenticationError, 401))

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertEqual(caught.exception.reason, "AuthenticationError")
        self.assertEqual(caught.exception.status_code, 401)

    def test_provider_5xx_becomes_llm_unavailable(self):
        llm = _llm_raising(_status_error(groq.InternalServerError, 503))

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertEqual(caught.exception.reason, "InternalServerError")
        self.assertEqual(caught.exception.status_code, 503)

    def test_connection_error_becomes_llm_unavailable_with_no_status(self):
        """
        A network failure never got an HTTP response, so there is no status
        to report. status_code must be None rather than blowing up on a
        missing attribute.
        """
        llm = _llm_raising(groq.APIConnectionError(request=_REQUEST))

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertEqual(caught.exception.reason, "APIConnectionError")
        self.assertIsNone(caught.exception.status_code)

    def test_timeout_becomes_llm_unavailable(self):
        llm = _llm_raising(groq.APITimeoutError(request=_REQUEST))

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertEqual(caught.exception.reason, "APITimeoutError")

    def test_no_groq_exception_type_escapes_the_llm_module(self):
        """
        Nothing above utils/llm.py should have to import a vendor SDK to
        handle an outage. Assert the raised exception is not any GroqError.
        """
        llm = _llm_raising(_status_error(groq.RateLimitError, 429))

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertNotIsInstance(caught.exception, groq.GroqError)


class TestRealBugsAreNotMasked(unittest.TestCase):
    """
    The fallback must not become a blanket `except Exception`. A genuine
    defect has to keep surfacing as a defect, otherwise this change would
    convert every crash in the LLM layer into a soothing "try again later"
    and hide it from monitoring.
    """

    def test_non_provider_exception_propagates_unchanged(self):
        llm = _llm_raising(TypeError("genuine bug in our own code"))

        with self.assertRaises(TypeError):
            llm.generate([{"role": "user", "content": "hi"}])

    def test_malformed_success_payload_is_not_an_outage(self):
        """
        A 200 response with an unexpected shape is a bug, not an outage --
        it must not be dressed up as LLMUnavailableError.
        """
        llm = LLM.__new__(LLM)
        llm.client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kw: SimpleNamespace(choices=[])
                )
            )
        )

        with self.assertRaises(IndexError):
            llm.generate([{"role": "user", "content": "hi"}])


class TestSecretsNeverReachTheLog(unittest.TestCase):
    """
    The failure path writes a log line. Provider error text can echo request
    details, and an AuthenticationError message may quote part of the API
    key -- so llm.py logs the exception CLASS and HTTP status, never
    str(error). This test is the guard on that decision.
    """

    def test_api_key_is_absent_from_the_failure_log(self):
        error = _status_error(
            groq.AuthenticationError,
            401,
            message=f"Incorrect API key provided: {SENTINEL_API_KEY}",
        )
        llm = _llm_raising(error)

        with self.assertLogs("KaivixLogger", level="ERROR") as captured:
            with self.assertRaises(LLMUnavailableError):
                llm.generate([{"role": "user", "content": "hi"}])

        joined = "\n".join(captured.output)
        self.assertNotIn(SENTINEL_API_KEY, joined)
        self.assertNotIn("Incorrect API key provided", joined)
        # but it must still be diagnosable
        self.assertIn("AuthenticationError", joined)
        self.assertIn("401", joined)

    def test_exception_string_does_not_carry_provider_message(self):
        error = _status_error(
            groq.AuthenticationError,
            401,
            message=f"Incorrect API key provided: {SENTINEL_API_KEY}",
        )
        llm = _llm_raising(error)

        with self.assertRaises(LLMUnavailableError) as caught:
            llm.generate([{"role": "user", "content": "hi"}])

        self.assertNotIn(SENTINEL_API_KEY, str(caught.exception))


class TestChatEndpointDegradesGracefully(unittest.TestCase):
    """
    End-to-end through the real engine: an LLMUnavailableError raised at the
    LLM layer has to travel up through ConversationEngine (which logs and
    re-raises it) and be turned into a 503 by the centrally registered
    handler.
    """

    def setUp(self):
        self.client = TestClient(app)
        self.engine = chat_router_module.chat_service.engine
        self.original_generate = self.engine.llm.generate

    def tearDown(self):
        self.engine.llm.generate = self.original_generate

    def _make_llm_unavailable(self):
        def _raise(messages):
            raise LLMUnavailableError(
                provider="groq", reason="RateLimitError", status_code=429
            )

        self.engine.llm.generate = _raise

    def test_returns_503_not_500(self):
        """
        The whole point. 500 says "we have a bug"; 503 says "temporarily
        unavailable, retry" -- which is both true and actionable.
        """
        self._make_llm_unavailable()

        response = self.client.post(
            "/chat",
            json={"conversation_id": "conv_503", "message": "hello"},
        )

        self.assertEqual(response.status_code, 503)

    def test_response_carries_the_graceful_message(self):
        self._make_llm_unavailable()

        response = self.client.post(
            "/chat",
            json={"conversation_id": "conv_503_msg", "message": "hello"},
        )

        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["error"]["code"], 503)
        self.assertEqual(body["error"]["message"], LLM_UNAVAILABLE_MESSAGE)

    def test_graceful_message_offers_a_channel_that_survives_the_outage(self):
        """
        An outage should cost a slow reply, not a lead -- so the message has
        to hand the visitor somewhere to go that does not depend on the AI.
        """
        self.assertIn("brayiron@kaivixlab.com", LLM_UNAVAILABLE_MESSAGE)

    def test_sets_retry_after_header(self):
        self._make_llm_unavailable()

        response = self.client.post(
            "/chat",
            json={"conversation_id": "conv_retry", "message": "hello"},
        )

        self.assertEqual(response.headers.get("retry-after"), "30")

    def test_error_envelope_matches_the_rest_of_the_api(self):
        """Same {success, error:{code, message}} shape as every other error."""
        self._make_llm_unavailable()

        response = self.client.post(
            "/chat",
            json={"conversation_id": "conv_shape", "message": "hello"},
        )

        body = response.json()
        self.assertEqual(set(body.keys()), {"success", "error"})
        self.assertEqual(set(body["error"].keys()), {"code", "message"})

    def test_healthy_chat_still_returns_200(self):
        """
        Regression guard: the fallback must only trigger on failure. A
        working LLM still produces a normal 200 with the model's reply.
        """
        self.engine.llm.generate = lambda messages: "stubbed-response"

        response = self.client.post(
            "/chat",
            json={"conversation_id": "conv_ok", "message": "hello"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertEqual(body["conversation_id"], "conv_ok")
        self.assertEqual(body["response"], "stubbed-response")


if __name__ == "__main__":
    unittest.main()
