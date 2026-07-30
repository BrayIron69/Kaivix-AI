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
import tempfile
import unittest

from auth.api_key_store import KEY_PREFIX, APIKeyStore
from core_ai.business_config import DEFAULT_BUSINESS_ID
from tests.test_multi_business_serving import BUSINESS_B, _MultiBusinessMixin

BUSINESS_C = "test-business-c"

# Has a key issued but no resolvable config, so the route authenticates and
# then fails to load a business. Proves the 404-not-500 behaviour Decision
# #023 added is still reachable now that auth runs in front of it.
UNCONFIGURED_BUSINESS = "no-such-business"


class _AuthMixin(_MultiBusinessMixin):
    """
    _MultiBusinessMixin already swaps in an isolated APIKeyStore (so no test
    ever reads or writes the real auth/api_keys.db) and exposes
    self.key_store. This adds business-b's plaintext key, which these tests
    need to present by hand rather than via auth_headers().
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
        self.key_store.revoke_key(BUSINESS_B)

        response = self._post_to_business_b(
            "auth_revoked", headers={"X-API-Key": self.business_b_key}
        )
        self.assertEqual(response.status_code, 401)

    def test_rotating_the_key_invalidates_the_old_one(self):
        old_key = self.business_b_key
        new_key = self.key_store.issue_key(BUSINESS_B)

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
        self.business_c_key = self.key_store.issue_key(BUSINESS_C)

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
        kaivix_key = self.key_store.issue_key(DEFAULT_BUSINESS_ID)

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
        key = self.key_store.issue_key(UNCONFIGURED_BUSINESS)

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
        self.key_store.revoke_key(BUSINESS_B)

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


class TestAPIKeyStore(unittest.TestCase):
    """Unit-level coverage of the store itself, in the shape of
    tests/test_calendar_token_store.py."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)
        self.store = APIKeyStore(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_issued_key_verifies(self):
        key = self.store.issue_key("business-a")
        self.assertTrue(self.store.verify_key("business-a", key))

    def test_issued_key_carries_the_prefix(self):
        self.assertTrue(self.store.issue_key("business-a").startswith(KEY_PREFIX))

    def test_wrong_key_does_not_verify(self):
        self.store.issue_key("business-a")
        self.assertFalse(self.store.verify_key("business-a", "kvx_wrong"))

    def test_none_and_empty_do_not_verify(self):
        self.store.issue_key("business-a")
        self.assertFalse(self.store.verify_key("business-a", None))
        self.assertFalse(self.store.verify_key("business-a", ""))

    def test_business_with_no_key_never_verifies(self):
        self.assertFalse(self.store.verify_key("business-nokey", "kvx_anything"))

    def test_key_is_scoped_to_its_business(self):
        key_a = self.store.issue_key("business-a")
        self.store.issue_key("business-b")

        self.assertTrue(self.store.verify_key("business-a", key_a))
        self.assertFalse(self.store.verify_key("business-b", key_a))

    def test_two_businesses_get_different_keys(self):
        self.assertNotEqual(
            self.store.issue_key("business-a"),
            self.store.issue_key("business-b"),
        )

    def test_reissue_replaces_rather_than_accumulates(self):
        self.store.issue_key("business-a")
        self.store.issue_key("business-a")

        conn = self.store._get_connection()
        count = conn.execute(
            "SELECT COUNT(*) FROM api_keys WHERE business_id = ?",
            ("business-a",),
        ).fetchone()[0]
        conn.close()

        self.assertEqual(count, 1)

    def test_plaintext_key_is_not_stored_anywhere_in_the_database(self):
        """
        The core claim of hashing at rest: a raw read of the database file
        yields nothing an attacker can present to the endpoint.
        """
        key = self.store.issue_key("business-a")

        raw_bytes = open(self.db_path, "rb").read()

        self.assertNotIn(key.encode("utf-8"), raw_bytes)
        # The random half alone must be absent too, not just the prefixed form.
        self.assertNotIn(key[len(KEY_PREFIX):].encode("utf-8"), raw_bytes)

    def test_stored_value_is_a_sha256_hex_digest(self):
        key = self.store.issue_key("business-a")

        conn = self.store._get_connection()
        stored = conn.execute(
            "SELECT key_hash FROM api_keys WHERE business_id = ?",
            ("business-a",),
        ).fetchone()["key_hash"]
        conn.close()

        self.assertEqual(len(stored), 64)
        self.assertEqual(stored, APIKeyStore.hash_key(key))

    def test_has_key_reports_provisioning_state(self):
        self.assertFalse(self.store.has_key("business-a"))
        self.store.issue_key("business-a")
        self.assertTrue(self.store.has_key("business-a"))

    def test_revoke_removes_the_key(self):
        key = self.store.issue_key("business-a")
        self.store.revoke_key("business-a")

        self.assertFalse(self.store.has_key("business-a"))
        self.assertFalse(self.store.verify_key("business-a", key))

    def test_keys_are_long_enough_to_be_unguessable(self):
        key = self.store.issue_key("business-a")
        self.assertGreaterEqual(len(key[len(KEY_PREFIX):]), 40)


if __name__ == "__main__":
    unittest.main()
