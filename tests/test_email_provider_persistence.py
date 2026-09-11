"""
EmailProvider reading the durable, env-var-backed Google connection
rather than only the wiped-on-deploy SQLite row.

GoogleCalendarProvider got this fix in 9ec91fd; EmailProvider mirrors
that method rather than sharing it (see its class docstring) and was
never updated, so email went silently dead after every single Render
deploy while the calendar kept working. That is why Bray truthfully told
a real visitor it had no way to send an email: the capability was fully
built and correctly reporting itself disconnected.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

from scheduling import render_env_sync
from scheduling.email_provider import GMAIL_SEND_SCOPE, EmailProvider
from scheduling.render_env_sync import REFRESH_TOKENS_ENV_VAR

CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"


def _env(entry) -> dict:
    return {REFRESH_TOKENS_ENV_VAR: json.dumps({"kaivix": entry})}


class TestIsConnectedReadsTheDurableRecord(unittest.TestCase):
    def setUp(self):
        self.token_store = MagicMock()
        # The post-deploy reality this whole fix is about: the SQLite
        # file is gone, so the row lookup returns nothing.
        self.token_store.load_token.return_value = None
        self.provider = EmailProvider(token_store=self.token_store)

    def test_connected_when_env_records_gmail_send_even_with_no_local_row(self):
        entry = {"refresh_token": "rt", "scopes": [CALENDAR_SCOPE, GMAIL_SEND_SCOPE]}
        with patch.dict("os.environ", _env(entry), clear=True):
            self.assertTrue(self.provider.is_connected("kaivix"))

    def test_not_connected_when_env_records_calendar_scopes_only(self):
        """
        An account that connected before gmail.send was added holds a
        real, usable calendar-only token. Google does not retroactively
        grant a scope nobody consented to.
        """
        entry = {"refresh_token": "rt", "scopes": [CALENDAR_SCOPE]}
        with patch.dict("os.environ", _env(entry), clear=True):
            self.assertFalse(self.provider.is_connected("kaivix"))

    def test_unknown_scopes_declines_rather_than_assuming(self):
        """
        The plain-string form carries no scope information. Assuming the
        current SCOPES list was granted would have Bray offer to send
        mail the account may not permit, then fail after promising --
        the exact claim-then-walk-it-back pattern this codebase treats
        as a trust defect.
        """
        with patch.dict("os.environ", _env("plain-string-refresh-token"), clear=True):
            self.assertFalse(self.provider.is_connected("kaivix"))

    def test_falls_back_to_the_local_row_when_no_env_entry_exists(self):
        self.token_store.load_token.return_value = {
            "scopes": [CALENDAR_SCOPE, GMAIL_SEND_SCOPE]
        }
        with patch.dict("os.environ", {}, clear=True):
            self.assertTrue(self.provider.is_connected("kaivix"))

    def test_not_connected_when_nothing_anywhere(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(self.provider.is_connected("kaivix"))


class TestLoadCredentialsPrefersTheDurableRecord(unittest.TestCase):
    @patch("google.auth.transport.requests.Request")
    @patch("google.oauth2.credentials.Credentials")
    def test_builds_from_env_token_and_refreshes_with_no_local_row(
        self, mock_credentials_cls, mock_request
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = None
        provider = EmailProvider(token_store=token_store)

        entry = {"refresh_token": "env-rt", "scopes": [GMAIL_SEND_SCOPE]}
        with patch.dict("os.environ", _env(entry), clear=True):
            result = provider._load_credentials("kaivix")

        _, kwargs = mock_credentials_cls.call_args
        self.assertEqual(kwargs["refresh_token"], "env-rt")
        self.assertEqual(kwargs["scopes"], [GMAIL_SEND_SCOPE])
        mock_credentials_cls.return_value.refresh.assert_called_once()
        self.assertIs(result, mock_credentials_cls.return_value)

    @patch("google.oauth2.credentials.Credentials")
    def test_returns_none_when_neither_source_has_anything(self, mock_credentials_cls):
        token_store = MagicMock()
        token_store.load_token.return_value = None
        provider = EmailProvider(token_store=token_store)

        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(provider._load_credentials("kaivix"))


class TestEnvVarEntryShapes(unittest.TestCase):
    """
    Production is holding a plain-string entry written by the previous
    version of persist_calendar_refresh_token. Reading it is what keeps
    the live calendar connected across the deploy that introduces the
    object form -- this is not legacy cruft, it is the current value.
    """

    def test_plain_string_entry_still_yields_its_refresh_token(self):
        with patch.dict("os.environ", _env("legacy-token"), clear=True):
            self.assertEqual(render_env_sync.load_refresh_token("kaivix"), "legacy-token")
            self.assertIsNone(render_env_sync.load_granted_scopes("kaivix"))

    def test_object_entry_yields_both(self):
        entry = {"refresh_token": "new-token", "scopes": [GMAIL_SEND_SCOPE]}
        with patch.dict("os.environ", _env(entry), clear=True):
            self.assertEqual(render_env_sync.load_refresh_token("kaivix"), "new-token")
            self.assertEqual(
                render_env_sync.load_granted_scopes("kaivix"), [GMAIL_SEND_SCOPE]
            )

    def test_object_entry_without_scopes_reports_unknown_not_empty(self):
        """
        None means "not recorded", and callers must not read it as
        "nothing was granted".
        """
        with patch.dict("os.environ", _env({"refresh_token": "t", "scopes": []}), clear=True):
            self.assertIsNone(render_env_sync.load_granted_scopes("kaivix"))


@patch.dict(
    "os.environ",
    {"RENDER_API_KEY": "rnd_test", "RENDER_SERVICE_ID": "srv-test"},
    clear=True,
)
class TestPersistingScopesDoesNotDamageOtherBusinesses(unittest.TestCase):
    @patch("scheduling.render_env_sync.requests")
    def test_another_businesss_object_entry_is_not_stringified(self, mock_requests):
        """
        A merge that str()-ed existing values would rewrite another
        business's {"refresh_token", "scopes"} entry as the repr of a
        dict and destroy their connection on the next read.
        """
        existing = json.dumps(
            {"acme": {"refresh_token": "acme-rt", "scopes": [GMAIL_SEND_SCOPE]}}
        )
        mock_requests.get.return_value = MagicMock(
            status_code=200,
            json=lambda: [{"envVar": {"key": REFRESH_TOKENS_ENV_VAR, "value": existing}}],
        )
        mock_requests.put.return_value = MagicMock(status_code=200)

        render_env_sync.persist_calendar_refresh_token(
            "kaivix", "kaivix-rt", scopes=[GMAIL_SEND_SCOPE]
        )

        sent = {
            item["key"]: item["value"]
            for item in mock_requests.put.call_args.kwargs["json"]
        }
        written = json.loads(sent[REFRESH_TOKENS_ENV_VAR])

        self.assertEqual(
            written["acme"], {"refresh_token": "acme-rt", "scopes": [GMAIL_SEND_SCOPE]}
        )
        self.assertEqual(
            written["kaivix"], {"refresh_token": "kaivix-rt", "scopes": [GMAIL_SEND_SCOPE]}
        )


if __name__ == "__main__":
    unittest.main()
