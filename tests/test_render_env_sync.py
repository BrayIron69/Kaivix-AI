import json
import unittest
from unittest.mock import MagicMock, patch

from scheduling import render_env_sync
from scheduling.render_env_sync import (
    REFRESH_TOKENS_ENV_VAR,
    load_refresh_token,
    persist_calendar_refresh_token,
)


def _env_var_page(pairs: dict) -> list:
    """Shape a {key: value} dict the way Render's real GET response does:
    a list of {"envVar": {"key": ..., "value": ...}} items."""
    return [{"envVar": {"key": key, "value": value}} for key, value in pairs.items()]


class TestPersistCalendarRefreshTokenMissingCredentials(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    @patch("scheduling.render_env_sync.requests")
    def test_returns_false_and_never_calls_render_when_api_key_unset(self, mock_requests):
        result = persist_calendar_refresh_token("kaivix", "refresh-token-value")

        self.assertFalse(result)
        mock_requests.get.assert_not_called()
        mock_requests.put.assert_not_called()

    @patch.dict("os.environ", {"RENDER_API_KEY": "rnd_test_key"}, clear=True)
    @patch("scheduling.render_env_sync.requests")
    def test_returns_false_and_never_calls_render_when_service_id_unset(self, mock_requests):
        result = persist_calendar_refresh_token("kaivix", "refresh-token-value")

        self.assertFalse(result)
        mock_requests.get.assert_not_called()
        mock_requests.put.assert_not_called()


@patch.dict(
    "os.environ",
    {"RENDER_API_KEY": "rnd_test_key", "RENDER_SERVICE_ID": "srv-test123"},
    clear=True,
)
class TestPersistCalendarRefreshTokenSuccess(unittest.TestCase):
    @patch("scheduling.render_env_sync.requests")
    def test_writes_new_token_when_env_var_did_not_exist_yet(self, mock_requests):
        mock_requests.get.return_value = MagicMock(
            status_code=200, json=lambda: _env_var_page({"GROQ_API_KEY": "groq-value"})
        )
        mock_requests.put.return_value = MagicMock(status_code=200)

        result = persist_calendar_refresh_token("kaivix", "new-refresh-token")

        self.assertTrue(result)
        put_kwargs = mock_requests.put.call_args.kwargs
        sent_pairs = {item["key"]: item["value"] for item in put_kwargs["json"]}

        # The unrelated existing variable must survive untouched.
        self.assertEqual(sent_pairs["GROQ_API_KEY"], "groq-value")
        self.assertEqual(
            json.loads(sent_pairs[REFRESH_TOKENS_ENV_VAR]),
            {"kaivix": "new-refresh-token"},
        )

    def test_merges_into_existing_tokens_without_wiping_other_businesses(self):
        with patch("scheduling.render_env_sync.requests") as mock_requests:
            existing_value = json.dumps({"acme": "acme-refresh-token"})
            mock_requests.get.return_value = MagicMock(
                status_code=200,
                json=lambda: _env_var_page({REFRESH_TOKENS_ENV_VAR: existing_value}),
            )
            mock_requests.put.return_value = MagicMock(status_code=200)

            result = persist_calendar_refresh_token("kaivix", "kaivix-refresh-token")

            self.assertTrue(result)
            put_kwargs = mock_requests.put.call_args.kwargs
            sent_pairs = {item["key"]: item["value"] for item in put_kwargs["json"]}
            merged = json.loads(sent_pairs[REFRESH_TOKENS_ENV_VAR])

            self.assertEqual(
                merged,
                {"acme": "acme-refresh-token", "kaivix": "kaivix-refresh-token"},
            )

    def test_malformed_existing_json_is_dropped_not_merged_into(self):
        """
        A corrupt existing value must never be blindly merged into --
        that risks silently perpetuating garbage. It is logged and
        treated as empty, so the write still succeeds with just this
        business's token.
        """
        with patch("scheduling.render_env_sync.requests") as mock_requests:
            mock_requests.get.return_value = MagicMock(
                status_code=200,
                json=lambda: _env_var_page({REFRESH_TOKENS_ENV_VAR: "{not valid json"}),
            )
            mock_requests.put.return_value = MagicMock(status_code=200)

            result = persist_calendar_refresh_token("kaivix", "kaivix-refresh-token")

            self.assertTrue(result)
            put_kwargs = mock_requests.put.call_args.kwargs
            sent_pairs = {item["key"]: item["value"] for item in put_kwargs["json"]}
            self.assertEqual(
                json.loads(sent_pairs[REFRESH_TOKENS_ENV_VAR]),
                {"kaivix": "kaivix-refresh-token"},
            )

    def test_get_failure_returns_false_and_never_attempts_a_write(self):
        with patch("scheduling.render_env_sync.requests") as mock_requests:
            mock_requests.get.side_effect = ConnectionError("network blip")

            result = persist_calendar_refresh_token("kaivix", "kaivix-refresh-token")

            self.assertFalse(result)
            mock_requests.put.assert_not_called()

    def test_put_failure_returns_false(self):
        with patch("scheduling.render_env_sync.requests") as mock_requests:
            mock_requests.get.return_value = MagicMock(status_code=200, json=lambda: [])
            mock_requests.put.side_effect = ConnectionError("network blip")

            result = persist_calendar_refresh_token("kaivix", "kaivix-refresh-token")

            self.assertFalse(result)

    def test_paginates_through_multiple_pages_of_existing_env_vars(self):
        """
        _ENV_VARS_PAGE_SIZE is 100 -- a service with more env vars than
        that must not have the extra ones silently dropped from the
        merge, which would look like a successful write while actually
        wiping every variable past the first page.
        """
        with patch("scheduling.render_env_sync.requests") as mock_requests:
            first_page = _env_var_page({f"VAR_{i}": str(i) for i in range(100)})
            for index, item in enumerate(first_page):
                item["cursor"] = f"cursor-{index}"
            second_page = _env_var_page({"LAST_VAR": "last-value"})

            mock_requests.get.side_effect = [
                MagicMock(status_code=200, json=lambda: first_page),
                MagicMock(status_code=200, json=lambda: second_page),
            ]
            mock_requests.put.return_value = MagicMock(status_code=200)

            result = persist_calendar_refresh_token("kaivix", "kaivix-refresh-token")

            self.assertTrue(result)
            self.assertEqual(mock_requests.get.call_count, 2)
            put_kwargs = mock_requests.put.call_args.kwargs
            sent_pairs = {item["key"]: item["value"] for item in put_kwargs["json"]}
            self.assertEqual(sent_pairs["LAST_VAR"], "last-value")
            self.assertEqual(sent_pairs["VAR_0"], "0")


class TestLoadRefreshToken(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_returns_none_when_env_var_unset(self):
        self.assertIsNone(load_refresh_token("kaivix"))

    @patch.dict(
        "os.environ",
        {REFRESH_TOKENS_ENV_VAR: json.dumps({"kaivix": "kaivix-token", "acme": "acme-token"})},
        clear=True,
    )
    def test_returns_the_right_businesss_token(self):
        self.assertEqual(load_refresh_token("kaivix"), "kaivix-token")
        self.assertEqual(load_refresh_token("acme"), "acme-token")

    @patch.dict("os.environ", {REFRESH_TOKENS_ENV_VAR: json.dumps({"acme": "acme-token"})}, clear=True)
    def test_returns_none_for_a_business_not_present(self):
        self.assertIsNone(load_refresh_token("kaivix"))

    @patch.dict("os.environ", {REFRESH_TOKENS_ENV_VAR: "{not valid json"}, clear=True)
    def test_returns_none_for_malformed_json(self):
        self.assertIsNone(load_refresh_token("kaivix"))

    @patch.dict("os.environ", {REFRESH_TOKENS_ENV_VAR: json.dumps(["not", "a", "dict"])}, clear=True)
    def test_returns_none_when_value_is_not_a_json_object(self):
        self.assertIsNone(load_refresh_token("kaivix"))


if __name__ == "__main__":
    unittest.main()
