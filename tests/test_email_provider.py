import unittest
from unittest.mock import MagicMock, patch

from scheduling.email_provider import GMAIL_SEND_SCOPE, EmailProvider
from scheduling.google_calendar_provider import SCOPES as CALENDAR_SCOPES

# The two scopes an account connected *before* gmail.send existed would
# have -- used to prove is_connected() correctly reports False for it,
# not just for a totally absent connection.
_PRE_GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def _make_provider(token_store=None):
    with patch.dict(
        "os.environ",
        {"GOOGLE_CLIENT_ID": "test-client-id", "GOOGLE_CLIENT_SECRET": "test-client-secret"},
    ):
        return EmailProvider(token_store=token_store or MagicMock())


class TestEmailProviderIsConnected(unittest.TestCase):
    """
    is_connected() must be a real scope check, not a row-existence
    check -- see EmailProvider.is_connected's docstring on why a
    calendar-only connection (made before gmail.send was added to
    GoogleCalendarProvider.SCOPES) must report False.
    """

    def test_no_stored_token_is_not_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = None
        provider = _make_provider(token_store=token_store)

        self.assertFalse(provider.is_connected("business-a"))

    def test_calendar_only_scopes_are_not_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = {"scopes": _PRE_GMAIL_SCOPES}
        provider = _make_provider(token_store=token_store)

        self.assertFalse(provider.is_connected("business-a"))

    def test_gmail_send_scope_present_is_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = {"scopes": CALENDAR_SCOPES}
        provider = _make_provider(token_store=token_store)

        self.assertIn(GMAIL_SEND_SCOPE, CALENDAR_SCOPES)
        self.assertTrue(provider.is_connected("business-a"))

    def test_missing_scopes_key_is_not_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = {}
        provider = _make_provider(token_store=token_store)

        self.assertFalse(provider.is_connected("business-a"))


class TestEmailProviderSendEmail(unittest.TestCase):
    _STORED_TOKEN = {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": CALENDAR_SCOPES,
        "expiry": None,
    }

    def test_no_recipient_fails_without_touching_credentials_or_api(self):
        token_store = MagicMock()
        provider = _make_provider(token_store=token_store)

        result = provider.send_email("business-a", to="", subject="Hi", body_text="body")

        self.assertEqual(result, {"success": False, "error": "No recipient email address."})
        token_store.load_token.assert_not_called()

    def test_not_connected_fails_with_clear_error(self):
        token_store = MagicMock()
        token_store.load_token.return_value = None
        provider = _make_provider(token_store=token_store)

        result = provider.send_email(
            "business-a", to="visitor@example.com", subject="Hi", body_text="body"
        )

        self.assertFalse(result["success"])
        self.assertIn("No Google connection stored", result["error"])

    @patch("google.oauth2.credentials.Credentials")
    def test_connected_but_gmail_send_not_granted_fails_with_clear_error(
        self, mock_credentials_cls
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(
            self._STORED_TOKEN, scopes=_PRE_GMAIL_SCOPES
        )

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials.scopes = _PRE_GMAIL_SCOPES
        mock_credentials_cls.return_value = mock_credentials

        provider = _make_provider(token_store=token_store)
        result = provider.send_email(
            "business-a", to="visitor@example.com", subject="Hi", body_text="body"
        )

        self.assertFalse(result["success"])
        self.assertIn("gmail.send", result["error"])
        self.assertIn("reconnect", result["error"].lower())

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_success_sends_real_message_via_gmail_api(
        self, mock_credentials_cls, mock_build
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials.scopes = CALENDAR_SCOPES
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        result = provider.send_email(
            "business-a",
            to="visitor@example.com",
            subject="Your conversation summary",
            body_text="Here is what we covered.",
        )

        self.assertEqual(result, {"success": True, "error": None})

        mock_build.assert_called_once_with(
            "gmail", "v1", credentials=mock_credentials, static_discovery=True
        )
        _args, send_kwargs = mock_service.users().messages().send.call_args
        self.assertEqual(send_kwargs["userId"], "me")
        self.assertIn("raw", send_kwargs["body"])

        import base64

        decoded = base64.urlsafe_b64decode(send_kwargs["body"]["raw"]).decode()
        self.assertIn("visitor@example.com", decoded)
        self.assertIn("Your conversation summary", decoded)
        self.assertIn("Here is what we covered.", decoded)

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_gmail_api_failure_is_caught_and_reported_not_raised(
        self, mock_credentials_cls, mock_build
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials.scopes = CALENDAR_SCOPES
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_service.users().messages().send().execute.side_effect = RuntimeError(
            "Gmail API exploded"
        )
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        provider.logger = MagicMock()

        result = provider.send_email(
            "business-a", to="visitor@example.com", subject="Hi", body_text="body"
        )

        self.assertFalse(result["success"])
        self.assertIn("Gmail API exploded", result["error"])
        provider.logger.error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
