import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scheduling.google_calendar_provider import GoogleCalendarProvider, SCOPES

UTC = ZoneInfo("UTC")


class _StubBusinessConfigRepository:
    """Deterministic stand-in for BusinessConfigRepository -- returns a
    fixed UTC timezone regardless of business_id, so get_free_busy_slots
    tests never depend on real config/businesses/kaivix/identity.yaml
    or on DST/offset quirks of a real timezone."""

    def __init__(self, timezone: str = "UTC"):
        self._timezone = timezone

    def load(self, business_id):
        return SimpleNamespace(identity=SimpleNamespace(timezone=self._timezone))


def _make_provider(token_store=None, business_config_repository=None):
    with patch.dict(
        "os.environ",
        {"GOOGLE_CLIENT_ID": "test-client-id", "GOOGLE_CLIENT_SECRET": "test-client-secret"},
    ):
        return GoogleCalendarProvider(
            token_store=token_store or MagicMock(),
            business_config_repository=business_config_repository
            or _StubBusinessConfigRepository(),
        )


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


class TestGoogleCalendarProviderSubtractBusy(unittest.TestCase):
    """
    Pure-logic tests for the free/busy subtraction and slot formatting,
    using fixed datetimes rather than the real current time, so these
    never depend on the date/day-of-week the test suite happens to run
    on.
    """

    def test_no_busy_blocks_returns_full_window(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)

        result = GoogleCalendarProvider._subtract_busy(start, end, [])
        self.assertEqual(result, [(start, end)])

    def test_busy_block_in_middle_splits_window_into_two_gaps(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)
        busy_start = datetime(2026, 3, 10, 12, 0, tzinfo=UTC)
        busy_end = datetime(2026, 3, 10, 13, 0, tzinfo=UTC)

        result = GoogleCalendarProvider._subtract_busy(start, end, [(busy_start, busy_end)])
        self.assertEqual(result, [(start, busy_start), (busy_end, end)])

    def test_busy_block_covering_entire_window_returns_no_gaps(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)
        all_day_busy = (
            datetime(2026, 3, 10, 0, 0, tzinfo=UTC),
            datetime(2026, 3, 11, 0, 0, tzinfo=UTC),
        )

        result = GoogleCalendarProvider._subtract_busy(start, end, [all_day_busy])
        self.assertEqual(result, [])

    def test_busy_block_outside_window_is_ignored(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)
        unrelated_busy = (
            datetime(2026, 3, 11, 9, 0, tzinfo=UTC),
            datetime(2026, 3, 11, 10, 0, tzinfo=UTC),
        )

        result = GoogleCalendarProvider._subtract_busy(start, end, [unrelated_busy])
        self.assertEqual(result, [(start, end)])

    def test_multiple_busy_blocks_leave_multiple_gaps(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)
        busy_blocks = [
            (datetime(2026, 3, 10, 10, 0, tzinfo=UTC), datetime(2026, 3, 10, 11, 0, tzinfo=UTC)),
            (datetime(2026, 3, 10, 14, 0, tzinfo=UTC), datetime(2026, 3, 10, 15, 0, tzinfo=UTC)),
        ]

        result = GoogleCalendarProvider._subtract_busy(start, end, busy_blocks)
        self.assertEqual(
            result,
            [
                (start, datetime(2026, 3, 10, 10, 0, tzinfo=UTC)),
                (datetime(2026, 3, 10, 11, 0, tzinfo=UTC), datetime(2026, 3, 10, 14, 0, tzinfo=UTC)),
                (datetime(2026, 3, 10, 15, 0, tzinfo=UTC), end),
            ],
        )

    def test_format_slot_produces_human_readable_string(self):
        start = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)  # a Tuesday
        end = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)

        formatted = GoogleCalendarProvider._format_slot(start, end)
        self.assertEqual(formatted, "Tuesday 2:00 PM - 3:00 PM")


class TestGoogleCalendarProviderFreeBusySlots(unittest.TestCase):
    """
    Exercises the full get_free_busy_slots() call path with Credentials
    and googleapiclient.discovery.build entirely mocked -- no real
    network calls.
    """

    _STORED_TOKEN = {
        "business_id": "business-a",
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": SCOPES,
    }

    def test_returns_empty_list_when_calendar_not_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        self.assertEqual(provider.get_free_busy_slots("business-a"), [])

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_returns_formatted_slots_when_no_busy_blocks(self, mock_credentials_cls, mock_build):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}}
        }
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        slots = provider.get_free_busy_slots("business-a")

        # An 8-day window (today + 7 days ahead) always contains at
        # least 5 weekdays regardless of what day the suite runs on, so
        # with zero busy blocks there is always at least one -- and at
        # most 3 -- open slot to return.
        self.assertGreater(len(slots), 0)
        self.assertLessEqual(len(slots), 3)
        for slot in slots:
            self.assertIsInstance(slot, str)
            self.assertIn(" - ", slot)

        _args, build_kwargs = mock_build.call_args
        self.assertIs(build_kwargs["credentials"], mock_credentials)
        self.assertTrue(build_kwargs["static_discovery"])

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_returns_empty_list_when_entire_window_is_busy(self, mock_credentials_cls, mock_build):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        # One giant busy block spanning far past any realistic
        # days_ahead=7 window from "now", regardless of when this test
        # actually runs.
        mock_service = MagicMock()
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [{"start": "2000-01-01T00:00:00+00:00", "end": "2100-01-01T00:00:00+00:00"}]
                }
            }
        }
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        self.assertEqual(provider.get_free_busy_slots("business-a"), [])

    def test_returns_empty_list_on_any_unexpected_failure(self):
        # An invalid timezone string raises inside get_free_busy_slots
        # (after credentials load successfully) -- exercising the "any
        # failure -> return [], never raise" contract without needing to
        # mock googleapiclient at all.
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        provider = _make_provider(
            token_store=token_store,
            business_config_repository=_StubBusinessConfigRepository(timezone="Not/AZone"),
        )

        self.assertEqual(provider.get_free_busy_slots("business-a"), [])


if __name__ == "__main__":
    unittest.main()
