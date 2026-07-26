import unittest
from unittest.mock import MagicMock, patch

from scheduling.google_calendar_provider import GoogleCalendarProvider, SCOPES


def _make_provider(token_store=None):
    with patch.dict(
        "os.environ",
        {"GOOGLE_CLIENT_ID": "test-client-id", "GOOGLE_CLIENT_SECRET": "test-client-secret"},
    ):
        return GoogleCalendarProvider(token_store=token_store or MagicMock())


class TestGoogleCalendarProviderAuthorizationUrl(unittest.TestCase):
    @patch("google_auth_oauthlib.flow.Flow.from_client_config")
    def test_get_authorization_url_encodes_business_id_into_state(self, mock_from_client_config):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=business-a", "business-a")
        mock_from_client_config.return_value = mock_flow

        provider = _make_provider()
        auth_url = provider.get_authorization_url("business-a")

        self.assertEqual(auth_url, "https://accounts.google.com/o/oauth2/auth?state=business-a")

        _config, kwargs = mock_from_client_config.call_args
        self.assertEqual(kwargs["state"], "business-a")
        self.assertEqual(kwargs["scopes"], SCOPES)
        self.assertEqual(kwargs["redirect_uri"], "http://localhost:8000/oauth/google/callback")

    @patch("google_auth_oauthlib.flow.Flow.from_client_config")
    def test_different_business_ids_get_different_state(self, mock_from_client_config):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://example.com/auth", "state")
        mock_from_client_config.return_value = mock_flow

        provider = _make_provider()
        provider.get_authorization_url("business-a")
        provider.get_authorization_url("business-b")

        states = [call.kwargs["state"] for call in mock_from_client_config.call_args_list]
        self.assertEqual(states, ["business-a", "business-b"])


class TestGoogleCalendarProviderOAuthCallback(unittest.TestCase):
    @patch("google_auth_oauthlib.flow.Flow.from_client_config")
    def test_handle_oauth_callback_saves_token_under_right_business_id(self, mock_from_client_config):
        mock_credentials = MagicMock()
        mock_credentials.token = "access-token"
        mock_credentials.refresh_token = "refresh-token"
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.scopes = SCOPES

        mock_flow = MagicMock()
        mock_flow.credentials = mock_credentials
        mock_from_client_config.return_value = mock_flow

        token_store = MagicMock()
        provider = _make_provider(token_store=token_store)

        callback_url = "http://localhost:8000/oauth/google/callback?code=abc123&state=business-a"
        provider.handle_oauth_callback("business-a", callback_url)

        mock_flow.fetch_token.assert_called_once_with(authorization_response=callback_url)
        token_store.save_token.assert_called_once_with(
            "business-a",
            {
                "token": "access-token",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": SCOPES,
            },
        )


class TestGoogleCalendarProviderListCalendars(unittest.TestCase):
    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_list_calendars_refreshes_expired_token_before_calling_api(
        self, mock_credentials_cls, mock_build
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = {
            "business_id": "business-a",
            "token": "old-access-token",
            "refresh_token": "refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": SCOPES,
        }

        mock_credentials = MagicMock()
        mock_credentials.expired = True
        mock_credentials.refresh_token = "refresh-token"
        mock_credentials.token = "refreshed-access-token"
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.scopes = SCOPES
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_service.calendarList().list().execute.return_value = {
            "items": [{"summary": "Primary", "id": "primary"}]
        }
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        calendars = provider.list_calendars("business-a")

        mock_credentials.refresh.assert_called_once()
        token_store.save_token.assert_called_with(
            "business-a",
            {
                "token": "refreshed-access-token",
                "refresh_token": "refresh-token",
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": SCOPES,
            },
        )

        _args, build_kwargs = mock_build.call_args
        self.assertIs(build_kwargs["credentials"], mock_credentials)
        self.assertTrue(build_kwargs["static_discovery"])

        self.assertEqual(calendars, [{"summary": "Primary", "id": "primary"}])

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_list_calendars_does_not_refresh_a_still_valid_token(
        self, mock_credentials_cls, mock_build
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = {
            "business_id": "business-a",
            "token": "still-valid-token",
            "refresh_token": "refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": SCOPES,
        }

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_service.calendarList().list().execute.return_value = {"items": []}
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        provider.list_calendars("business-a")

        mock_credentials.refresh.assert_not_called()
        # Only the original save from setup, never a re-save from refresh.
        token_store.save_token.assert_not_called()

    def test_list_calendars_raises_clearly_when_business_never_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)

        with self.assertRaises(RuntimeError) as ctx:
            provider.list_calendars("business-never-connected")

        self.assertIn("business-never-connected", str(ctx.exception))


class TestGoogleCalendarProviderIsConnected(unittest.TestCase):
    def test_is_connected_true_when_token_present(self):
        token_store = MagicMock()
        token_store.load_token.return_value = {"business_id": "business-a", "token": "t"}

        provider = _make_provider(token_store=token_store)
        self.assertTrue(provider.is_connected("business-a"))

    def test_is_connected_false_when_no_token(self):
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        self.assertFalse(provider.is_connected("business-a"))


if __name__ == "__main__":
    unittest.main()
