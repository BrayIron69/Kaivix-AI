"""
Authentication on POST /chat/{business_id}.

Closes the gap recorded as a trade-off in Decision #023: the per-business
route existed with no authorization at all, so any caller who knew or guessed
a business_id could hold a conversation as that business.

Two properties matter most in this file, and they pull in opposite
directions:

- TestCrossBusinessKeyRejection: a key issued for one business must be
  useless against another. A shared-secret scheme that authenticated the
  caller but not the *business* would look like it worked and would still
  let tenant A talk as tenant B.
- TestPlainChatRemainsOpen: plain POST /chat must stay unauthenticated and
  byte-identical. That is the live marketing widget's traffic. It reuses the
  byte-identical assertion from tests/test_multi_business_serving.py's
  TestPlainChatEndpointUnchanged, now with the auth layer installed, so the
  proof covers the endpoint as it actually runs today.
"""

import json
import os
import unittest
from unittest.mock import patch

from auth import business_api_keys
from auth.business_api_keys import KEY_PREFIX
from core_ai.business_config import DEFAULT_BUSINESS_ID
from tests.test_multi_business_serving import BUSINESS_B, _MultiBusinessMixin

BUSINESS_C = "test-business-c"

# Has a key issued but no resolvable config, so the route authenticates and
# then fails to load a business. Proves the 404-not-500 behaviour Decision
# #023 added is still reachable now that auth runs in front of it.
UNCONFIGURED_BUSINESS = "no-such-business"


class _AuthMixin(_MultiBusinessMixin):
    """
    _MultiBusinessMixin already isolates BUSINESS_API_KEYS to a
    test-controlled value (so no test ever reads a real key from a
    developer's own .env) and exposes issue_key()/revoke_key(). This adds
    business-b's plaintext key, which these tests need to present by hand
    rather than via auth_headers().
    """

    def _setup_auth(self, llm_stub=None):
        self._setup_two_businesses(llm_stub=llm_stub)
        self.business_b_key = self.auth_headers(BUSINESS_B)["X-API-Key"]

    def _post_to_business_b(self, conversation_id, message="Hi", headers=None):
        return self.client.post(
            f"/chat/{BUSINESS_B}",
            json={"conversation_id": conversation_id, "message": message},
            headers=headers,
        )


class TestValidKeyIsAccepted(_AuthMixin, unittest.TestCase):
    def setUp(self):
        self._setup_auth(llm_stub=lambda messages: "stubbed-response")

    def test_valid_key_succeeds(self):
        response = self._post_to_business_b(
            "auth_ok_1", headers={"X-API-Key": self.business_b_key}
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])

    def test_valid_key_still_returns_the_normal_response_shape(self):
        """Auth must not alter the payload for an authorized caller."""
        response = self._post_to_business_b(
            "auth_ok_2", headers={"X-API-Key": self.business_b_key}
        )
        self.assertEqual(
            set(response.json().keys()),
            {"success", "conversation_id", "response"},
        )

    def test_header_name_is_case_insensitive(self):
        """HTTP header names are case-insensitive; a client sending
        'x-api-key' must not be rejected over casing."""
        response = self._post_to_business_b(
            "auth_ok_3", headers={"x-api-key": self.business_b_key}
        )
        self.assertEqual(response.status_code, 200)


class TestMissingOrWrongKeyIsRejected(_AuthMixin, unittest.TestCase):
    def setUp(self):
        self._setup_auth(llm_stub=lambda messages: "stubbed-response")

    def test_missing_header_is_401(self):
        response = self._post_to_business_b("auth_missing")
        self.assertEqual(response.status_code, 401)

    def test_wrong_key_is_401(self):
        response = self._post_to_business_b(
            "auth_wrong", headers={"X-API-Key": KEY_PREFIX + "not-the-real-key"}
        )
        self.assertEqual(response.status_code, 401)

    def test_empty_header_value_is_401(self):
        response = self._post_to_business_b(
            "auth_empty", headers={"X-API-Key": ""}
        )
        self.assertEqual(response.status_code, 401)

    def test_business_with_no_key_issued_is_401_not_open(self):
        """
        Unprovisioned means closed. The dangerous failure mode would be
        treating "no key on record" as "no key required".
        """
        response = self.client.post(
            f"/chat/{BUSINESS_C}",
            json={"conversation_id": "auth_nokey", "message": "Hi"},
        )
        self.assertEqual(response.status_code, 401)

    def test_revoked_key_stops_working(self):
        self.revoke_key(BUSINESS_B)

        response = self._post_to_business_b(
            "auth_revoked", headers={"X-API-Key": self.business_b_key}
        )
        self.assertEqual(response.status_code, 401)

    def test_rotating_the_key_invalidates_the_old_one(self):
        old_key = self.business_b_key
        new_key = self.issue_key(BUSINESS_B)

        self.assertEqual(
            self._post_to_business_b(
                "auth_rot_old", headers={"X-API-Key": old_key}
            ).status_code,
            401,
        )
        self.assertEqual(
            self._post_to_business_b(
                "auth_rot_new", headers={"X-API-Key": new_key}
            ).status_code,
            200,
        )

    def test_401_names_the_header_the_caller_should_send(self):
        response = self._post_to_business_b("auth_msg")
        self.assertIn("X-API-Key", response.json()["error"]["message"])

    def test_401_does_not_echo_the_presented_key(self):
        """The rejection must not put a credential into a response body
        (which may be logged by an intermediary)."""
        presented = KEY_PREFIX + "some-guessed-value"
        response = self._post_to_business_b(
            "auth_noecho", headers={"X-API-Key": presented}
        )
        self.assertNotIn(presented, response.text)

    def test_unauthorized_request_never_builds_an_engine(self):
        """
        Auth runs as a dependency, before the handler body -- so an
        unauthorized caller costs no config load and no knowledge-base read.
        """
        self._post_to_business_b("auth_nowork")
        self.assertEqual(self.service.cached_business_ids, [])

    def test_unauthorized_request_never_reaches_the_model(self):
        calls = []
        engine = self.service.get_engine(BUSINESS_B)
        engine.llm.generate = lambda messages: calls.append(messages) or "x"

        self._post_to_business_b("auth_nollm")

        self.assertEqual(calls, [])


class TestCrossBusinessKeyRejection(_AuthMixin, unittest.TestCase):
    """
    The sharpest form of the requirement: a valid key is valid for exactly
    one business_id.
    """

    def setUp(self):
        self._setup_auth(llm_stub=lambda messages: "stubbed-response")
        self.business_c_key = self.issue_key(BUSINESS_C)

    def test_key_for_c_does_not_work_against_b(self):
        response = self._post_to_business_b(
            "cross_1", headers={"X-API-Key": self.business_c_key}
        )
        self.assertEqual(response.status_code, 401)

    def test_key_for_b_does_not_work_against_c(self):
        response = self.client.post(
            f"/chat/{BUSINESS_C}",
            json={"conversation_id": "cross_2", "message": "Hi"},
            headers={"X-API-Key": self.business_b_key},
        )
        self.assertEqual(response.status_code, 401)

    def test_each_business_gets_a_distinct_key(self):
        self.assertNotEqual(self.business_b_key, self.business_c_key)

    def test_kaivix_key_does_not_unlock_another_business(self):
        """
        The realistic attack: our own production key leaks, and is tried
        against a customer's business_id.
        """
        kaivix_key = self.issue_key(DEFAULT_BUSINESS_ID)

        response = self._post_to_business_b(
            "cross_3", headers={"X-API-Key": kaivix_key}
        )
        self.assertEqual(response.status_code, 401)


class TestUnknownBusinessId(_AuthMixin, unittest.TestCase):
    def setUp(self):
        self._setup_auth(llm_stub=lambda messages: "stubbed-response")

    def test_unknown_business_id_without_a_key_is_401_not_404(self):
        """
        Auth deliberately runs before business resolution, so this endpoint
        cannot be used to enumerate which business_ids exist: an unknown id
        is indistinguishable from a known one to an unauthorized caller.
        """
        response = self.client.post(
            f"/chat/{UNCONFIGURED_BUSINESS}",
            json={"conversation_id": "unknown_1", "message": "Hi"},
        )
        self.assertEqual(response.status_code, 401)

    def test_authenticated_request_for_a_broken_business_is_still_404(self):
        """
        Decision #023's 404-not-500 behaviour is preserved for a caller who
        IS authorized -- it now signals "your business's config is broken",
        which is exactly who should see it.
        """
        key = self.issue_key(UNCONFIGURED_BUSINESS)

        response = self.client.post(
            f"/chat/{UNCONFIGURED_BUSINESS}",
            json={"conversation_id": "unknown_2", "message": "Hi"},
            headers={"X-API-Key": key},
        )

        self.assertEqual(response.status_code, 404)
        self.assertIn(UNCONFIGURED_BUSINESS, response.json()["error"]["message"])


class TestPlainChatRemainsOpen(_AuthMixin, unittest.TestCase):
    """
    The non-negotiable half of this change.

    chat_widget.html on the live marketing site posts to plain /chat with no
    credential and no way to hold one. If anything here fails, the widget is
    down.
    """

    def setUp(self):
        self._setup_auth(llm_stub=lambda messages: "stubbed-response")

    def test_plain_chat_needs_no_key(self):
        response = self.client.post(
            "/chat", json={"conversation_id": "open_1", "message": "Hi"}
        )
        self.assertEqual(response.status_code, 200)

    def test_response_is_byte_identical_with_auth_installed(self):
        """
        The same assertion as TestPlainChatEndpointUnchanged
        .test_response_is_byte_identical in
        tests/test_multi_business_serving.py, re-run with the API-key layer
        in place: the exact bytes the widget has always received, key order
        included.
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

    def test_plain_chat_ignores_a_garbage_api_key_header(self):
        """
        A stale or wrong X-API-Key arriving on plain /chat (a proxy adding
        one, an old integration) must not turn into a 401 -- this route does
        not consult the header at all.
        """
        response = self.client.post(
            "/chat",
            json={"conversation_id": "open_2", "message": "Hi"},
            headers={"X-API-Key": "kvx_totally-invalid"},
        )
        self.assertEqual(response.status_code, 200)

    def test_plain_chat_works_with_no_keys_issued_at_all(self):
        """
        An empty api_keys table must not close the public endpoint -- the
        widget has to keep working on a fresh deployment where no key has
        ever been issued.
        """
        self.revoke_key(BUSINESS_B)

        response = self.client.post(
            "/chat", json={"conversation_id": "open_3", "message": "Hi"}
        )
        self.assertEqual(response.status_code, 200)

    def test_plain_chat_still_routes_to_the_default_business(self):
        self.client.post(
            "/chat", json={"conversation_id": "open_4", "message": "Hi"}
        )
        self.assertEqual(self.service.cached_business_ids, [DEFAULT_BUSINESS_ID])

    def test_widget_payload_shape_still_accepted(self):
        response = self.client.post(
            "/chat",
            json={
                "conversation_id": "session_abc123",
                "message": "Hey, just landed on your website",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conversation_id"], "session_abc123")


class TestBusinessAPIKeys(unittest.TestCase):
    """
    Unit-level coverage of the env-backed key source that replaced
    auth/api_key_store.py.

    Every test patches BUSINESS_API_KEYS explicitly, so none of them can
    see a real key from a developer's own .env -- the same isolation
    discipline the deleted SQLite tests got from a temp database file.
    """

    def _env(self, mapping: dict) -> dict:
        return {business_api_keys.ENV_VAR: json.dumps(mapping)}

    def _with_key(self, business_id: str) -> tuple[str, dict]:
        """A generated key plus the env mapping that makes it valid."""
        key = business_api_keys.generate_key()
        return key, self._env({business_id: business_api_keys.hash_key(key)})

    # --- generation -------------------------------------------------

    def test_generated_key_carries_the_prefix(self):
        self.assertTrue(business_api_keys.generate_key().startswith(KEY_PREFIX))

    def test_generated_keys_are_long_enough_to_be_unguessable(self):
        key = business_api_keys.generate_key()
        self.assertGreaterEqual(len(key[len(KEY_PREFIX):]), 40)

    def test_two_generated_keys_differ(self):
        self.assertNotEqual(
            business_api_keys.generate_key(), business_api_keys.generate_key()
        )

    def test_hash_is_a_sha256_hex_digest(self):
        digest = business_api_keys.hash_key("kvx_whatever")
        self.assertEqual(len(digest), 64)
        self.assertEqual(digest, business_api_keys.hash_key("kvx_whatever"))

    # --- verification -----------------------------------------------

    def test_valid_key_verifies(self):
        key, env = self._with_key("business-a")
        with patch.dict(os.environ, env):
            self.assertTrue(business_api_keys.verify_key("business-a", key))

    def test_wrong_key_does_not_verify(self):
        _key, env = self._with_key("business-a")
        with patch.dict(os.environ, env):
            self.assertFalse(business_api_keys.verify_key("business-a", "kvx_wrong"))

    def test_none_and_empty_do_not_verify(self):
        _key, env = self._with_key("business-a")
        with patch.dict(os.environ, env):
            self.assertFalse(business_api_keys.verify_key("business-a", None))
            self.assertFalse(business_api_keys.verify_key("business-a", ""))

    def test_business_with_no_key_never_verifies(self):
        _key, env = self._with_key("business-a")
        with patch.dict(os.environ, env):
            self.assertFalse(
                business_api_keys.verify_key("business-nokey", "kvx_anything")
            )

    def test_key_is_scoped_to_its_business(self):
        """
        The property that makes this authenticate the BUSINESS, not just
        the caller -- Decision #024's central requirement, preserved.
        """
        key_a = business_api_keys.generate_key()
        key_b = business_api_keys.generate_key()
        env = self._env({
            "business-a": business_api_keys.hash_key(key_a),
            "business-b": business_api_keys.hash_key(key_b),
        })

        with patch.dict(os.environ, env):
            self.assertTrue(business_api_keys.verify_key("business-a", key_a))
            self.assertFalse(business_api_keys.verify_key("business-b", key_a))
            self.assertTrue(business_api_keys.verify_key("business-b", key_b))
            self.assertFalse(business_api_keys.verify_key("business-a", key_b))

    def test_business_ids_with_hyphens_are_used_verbatim(self):
        """
        The reason this is one JSON variable rather than a
        BUSINESS_API_KEY_<ID> naming convention: `test-business-b` cannot
        be an env var name, and normalising it to TEST_BUSINESS_B would
        collide with `test_business_b`. Here the id is a literal dict key,
        so no normalisation happens and no collision is possible.
        """
        key = business_api_keys.generate_key()
        env = self._env({"test-business-b": business_api_keys.hash_key(key)})

        with patch.dict(os.environ, env):
            self.assertTrue(business_api_keys.verify_key("test-business-b", key))
            self.assertFalse(business_api_keys.verify_key("test_business_b", key))

    # --- the env var itself -----------------------------------------

    def test_the_plaintext_key_is_never_in_the_environment(self):
        """
        Hash-at-rest, carried over from Decision #024: an env dump or a
        screenshot of the dashboard must not yield a usable credential.
        """
        key, env = self._with_key("business-a")
        raw = env[business_api_keys.ENV_VAR]

        self.assertNotIn(key, raw)
        self.assertNotIn(key[len(KEY_PREFIX):], raw)
        self.assertIn(business_api_keys.hash_key(key), raw)

    def test_unset_variable_denies_everything(self):
        with patch.dict(os.environ):
            os.environ.pop(business_api_keys.ENV_VAR, None)
            self.assertFalse(business_api_keys.verify_key("business-a", "kvx_x"))
            self.assertEqual(business_api_keys.configured_business_ids(), [])

    def test_empty_variable_denies_everything(self):
        with patch.dict(os.environ, {business_api_keys.ENV_VAR: "   "}):
            self.assertFalse(business_api_keys.verify_key("business-a", "kvx_x"))

    def test_malformed_json_fails_closed_rather_than_open(self):
        """Unparseable config must deny, never allow, and never 500."""
        with patch.dict(os.environ, {business_api_keys.ENV_VAR: "{not json"}):
            self.assertFalse(business_api_keys.verify_key("business-a", "kvx_x"))
            self.assertEqual(business_api_keys.configured_business_ids(), [])

    def test_json_that_is_not_an_object_fails_closed(self):
        with patch.dict(os.environ, {business_api_keys.ENV_VAR: '["a","b"]'}):
            self.assertFalse(business_api_keys.verify_key("business-a", "kvx_x"))

    def test_one_bad_entry_does_not_lock_out_the_other_businesses(self):
        key = business_api_keys.generate_key()
        env = self._env({
            "business-a": business_api_keys.hash_key(key),
            "business-broken": None,
        })

        with patch.dict(os.environ, env):
            self.assertTrue(business_api_keys.verify_key("business-a", key))
            self.assertFalse(business_api_keys.verify_key("business-broken", key))

    def test_value_is_read_fresh_on_every_call_not_cached_at_import(self):
        """
        Rotating the variable on the host has to take effect on restart
        without a code change -- and tests patching it have to be seen.
        """
        key_one = business_api_keys.generate_key()
        key_two = business_api_keys.generate_key()

        with patch.dict(os.environ, self._env({"b": business_api_keys.hash_key(key_one)})):
            self.assertTrue(business_api_keys.verify_key("b", key_one))
            self.assertFalse(business_api_keys.verify_key("b", key_two))

        with patch.dict(os.environ, self._env({"b": business_api_keys.hash_key(key_two)})):
            self.assertFalse(business_api_keys.verify_key("b", key_one))
            self.assertTrue(business_api_keys.verify_key("b", key_two))

    def test_configured_business_ids_reports_what_is_provisioned(self):
        env = self._env({
            "b-two": business_api_keys.hash_key("kvx_2"),
            "b-one": business_api_keys.hash_key("kvx_1"),
        })
        with patch.dict(os.environ, env):
            self.assertEqual(
                business_api_keys.configured_business_ids(), ["b-one", "b-two"]
            )


if __name__ == "__main__":
    unittest.main()
