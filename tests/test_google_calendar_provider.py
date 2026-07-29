import importlib
import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scheduling import google_calendar_provider
from scheduling.calendar_token_store import CalendarTokenStore
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


@contextmanager
def _public_base_url(base_url: str):
    """
    Sets PUBLIC_BASE_URL for the duration of the block and reloads
    scheduling.google_calendar_provider so its module-level REDIRECT_URI
    (read once at import time, per config.py's own pattern) picks up the
    override -- monkeypatching os.environ alone wouldn't be enough,
    since REDIRECT_URI is only computed once, not read fresh on every
    call. Always reloads again on the way out (even on error) so a
    later test never sees a leftover REDIRECT_URI from a previous test.
    """
    try:
        with patch.dict("os.environ", {"PUBLIC_BASE_URL": base_url}):
            importlib.reload(google_calendar_provider)
            yield
    finally:
        importlib.reload(google_calendar_provider)


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

        with _public_base_url("https://test-deployment.example.com"):
            provider = _make_provider()
            auth_url = provider.get_authorization_url("business-a")

        self.assertEqual(auth_url, "https://accounts.google.com/o/oauth2/auth?state=business-a")

        _config, kwargs = mock_from_client_config.call_args
        self.assertEqual(kwargs["state"], "business-a")
        self.assertEqual(kwargs["scopes"], SCOPES)
        self.assertEqual(
            kwargs["redirect_uri"],
            "https://test-deployment.example.com/oauth/google/callback",
        )

    @patch("google_auth_oauthlib.flow.Flow.from_client_config")
    def test_redirect_uri_falls_back_to_localhost_when_public_base_url_unset(
        self, mock_from_client_config
    ):
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/o/oauth2/auth?state=business-a", "business-a")
        mock_from_client_config.return_value = mock_flow

        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("PUBLIC_BASE_URL", None)
            importlib.reload(google_calendar_provider)
            try:
                provider = _make_provider()
                provider.get_authorization_url("business-a")
            finally:
                importlib.reload(google_calendar_provider)

        _config, kwargs = mock_from_client_config.call_args
        self.assertEqual(
            kwargs["redirect_uri"], "http://localhost:8000/oauth/google/callback"
        )

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

        formatted = GoogleCalendarProvider.format_slot(start, end)
        self.assertEqual(formatted, "Tuesday 2:00 PM - 3:00 PM")


class TestGoogleCalendarProviderChunkIntoSlots(unittest.TestCase):
    """
    Pure-logic tests for _chunk_into_slots -- the fix for a genuine gap a
    live end-to-end run found: an entirely open gap used to be returned
    as one giant multi-hour "slot" (e.g. 9:00 AM - 5:00 PM on a fully
    free day), which isn't something a visitor can meaningfully pick as
    a single appointment time.
    """

    _DURATION = timedelta(minutes=30)

    def test_full_business_day_produces_sixteen_30_minute_slots(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=UTC)  # 8 hours

        slots = GoogleCalendarProvider._chunk_into_slots(start, end, self._DURATION)

        self.assertEqual(len(slots), 16)
        self.assertEqual(slots[0], (start, start + self._DURATION))
        self.assertEqual(slots[-1], (end - self._DURATION, end))
        for slot_start, slot_end in slots:
            self.assertEqual(slot_end - slot_start, self._DURATION)

    def test_gap_shorter_than_duration_is_excluded_entirely(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 9, 15, tzinfo=UTC)  # 15 minutes, shorter than 30

        slots = GoogleCalendarProvider._chunk_into_slots(start, end, self._DURATION)

        self.assertEqual(slots, [])

    def test_exact_duration_gap_produces_exactly_one_slot(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 9, 30, tzinfo=UTC)

        slots = GoogleCalendarProvider._chunk_into_slots(start, end, self._DURATION)

        self.assertEqual(slots, [(start, end)])

    def test_remainder_shorter_than_duration_is_dropped_not_returned_short(self):
        start = datetime(2026, 3, 10, 9, 0, tzinfo=UTC)
        end = datetime(2026, 3, 10, 10, 15, tzinfo=UTC)  # 75 minutes: 2 full slots + 15 min dropped

        slots = GoogleCalendarProvider._chunk_into_slots(start, end, self._DURATION)

        self.assertEqual(
            slots,
            [
                (start, start + self._DURATION),
                (start + self._DURATION, start + 2 * self._DURATION),
            ],
        )


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


class TestGoogleCalendarProviderFreeBusyWindows(unittest.TestCase):
    """
    get_free_busy_windows() is the structured form get_free_busy_slots()
    is now a thin formatting wrapper over -- ConversationEngine calls
    this form directly so it can remember and later book the exact real
    start/end datetimes, not just their display text. Same mocking
    approach as TestGoogleCalendarProviderFreeBusySlots above.
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
        self.assertEqual(provider.get_free_busy_windows("business-a"), [])

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_returns_real_datetime_tuples_when_no_busy_blocks(
        self, mock_credentials_cls, mock_build
    ):
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
        windows = provider.get_free_busy_windows("business-a")

        self.assertGreater(len(windows), 0)
        self.assertLessEqual(len(windows), 3)
        for start, end in windows:
            self.assertIsInstance(start, datetime)
            self.assertIsInstance(end, datetime)
            self.assertLess(start, end)
            # Fixed 30-minute appointment slots, not a raw multi-hour gap.
            self.assertEqual(end - start, timedelta(minutes=30))

        # get_free_busy_slots' formatted strings must be exactly
        # format_slot() applied to these same windows -- proves the two
        # methods share one computation, not two independent ones that
        # could drift apart.
        slots = provider.get_free_busy_slots("business-a")
        self.assertEqual(
            slots, [GoogleCalendarProvider.format_slot(start, end) for start, end in windows]
        )

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_empty_calendar_day_produces_multiple_slots_not_one_giant_block(
        self, mock_credentials_cls, mock_build
    ):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        # Entirely empty calendar -- the exact scenario a live end-to-end
        # run found returning one 8-hour "slot" (9:00 AM - 5:00 PM)
        # before this fix.
        mock_service = MagicMock()
        mock_service.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}}
        }
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        windows = provider.get_free_busy_windows("business-a")

        # Capped at 3 (existing behavior) -- with a fully open 8-hour
        # business day, that cap is hit well before the day is chunked
        # through entirely, proving multiple slots come back rather than
        # one giant block.
        self.assertEqual(len(windows), 3)
        for start, end in windows:
            self.assertEqual(end - start, timedelta(minutes=30))
            self.assertLess(end - start, timedelta(hours=8))


class TestGoogleCalendarProviderCreateEvent(unittest.TestCase):
    """
    Exercises create_event() with Credentials and
    googleapiclient.discovery.build entirely mocked -- this suite must
    NEVER create a real calendar event.
    """

    _STORED_TOKEN = {
        "business_id": "business-a",
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": SCOPES,
    }

    _START = datetime(2026, 3, 10, 14, 0, tzinfo=UTC)
    _END = datetime(2026, 3, 10, 15, 0, tzinfo=UTC)

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_create_event_success_returns_event_link(self, mock_credentials_cls, mock_build):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_service.events().insert().execute.return_value = {
            "htmlLink": "https://calendar.google.com/event?eid=abc123"
        }
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)
        result = provider.create_event(
            "business-a",
            summary="Kaivix Demo Call - Alice",
            start_time=self._START,
            end_time=self._END,
            attendee_email="alice@example.com",
        )

        self.assertEqual(
            result,
            {
                "success": True,
                "event_link": "https://calendar.google.com/event?eid=abc123",
                "error": None,
            },
        )

        _args, insert_kwargs = mock_service.events().insert.call_args
        self.assertEqual(insert_kwargs["calendarId"], "primary")
        self.assertEqual(
            insert_kwargs["body"]["attendees"], [{"email": "alice@example.com"}]
        )

    def test_create_event_returns_failure_dict_when_not_connected(self):
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        result = provider.create_event(
            "business-never-connected",
            summary="Demo",
            start_time=self._START,
            end_time=self._END,
            attendee_email="alice@example.com",
        )

        self.assertFalse(result["success"])
        self.assertIsNone(result["event_link"])
        self.assertIn("business-never-connected", result["error"])

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_create_event_never_raises_on_api_failure(self, mock_credentials_cls, mock_build):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        mock_service = MagicMock()
        mock_service.events().insert().execute.side_effect = RuntimeError(
            "Google Calendar API is down"
        )
        mock_build.return_value = mock_service

        provider = _make_provider(token_store=token_store)

        try:
            result = provider.create_event(
                "business-a",
                summary="Demo",
                start_time=self._START,
                end_time=self._END,
                attendee_email="alice@example.com",
            )
        except Exception as exc:  # pragma: no cover -- the assertion below is the real point
            self.fail(f"create_event raised {exc!r} instead of returning a failure dict")

        self.assertFalse(result["success"])
        self.assertIsNone(result["event_link"])
        self.assertIn("Google Calendar API is down", result["error"])

    def test_create_event_returns_failure_dict_when_times_missing(self):
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        provider = _make_provider(token_store=token_store)
        result = provider.create_event(
            "business-a",
            summary="Demo",
            start_time=None,
            end_time=None,
            attendee_email="alice@example.com",
        )

        self.assertFalse(result["success"])
        self.assertIsNone(result["event_link"])
        self.assertIsNotNone(result["error"])


class _FakeFlow:
    """
    Minimal stand-in for google_auth_oauthlib.flow.Flow -- deliberately
    NOT a MagicMock, because a MagicMock auto-generates a fresh, truthy
    `.code_verifier` attribute for every distinct mock instance regardless
    of what any other instance was given, which would silently hide the
    exact bug this test exists to catch (a real end-to-end run found it;
    the old wholesale-mocked-Flow tests could not have).

    Mimics only the one behavior this bug hinges on: authorization_url()
    populates a real code_verifier attribute (like the real library's
    PKCE auto-generation), and fetch_token() needs that same value to
    already be set on this exact instance to succeed.
    """

    def __init__(self):
        self.code_verifier = None
        self.credentials = SimpleNamespace(
            token="access-token",
            refresh_token="refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            scopes=SCOPES,
        )
        self.fetch_token_calls: list[dict] = []

    def authorization_url(self, **kwargs):
        self.code_verifier = "real-pkce-verifier-abc123"
        return "https://accounts.google.com/o/oauth2/auth?code_challenge=fake", "kaivix"

    def fetch_token(self, **kwargs):
        if self.code_verifier is None:
            # Mirrors Google's real rejection when no verifier was set on
            # this Flow instance before the exchange.
            raise RuntimeError("(invalid_grant) Missing code verifier.")
        self.fetch_token_calls.append(dict(kwargs))


class TestGoogleCalendarProviderPKCECodeVerifierPlumbing(unittest.TestCase):
    """
    Proves the specific plumbing that fixes a real bug found during a
    real end-to-end verification run: get_authorization_url() and
    handle_oauth_callback() build two independent Flow objects across two
    separate HTTP requests. The PKCE code_verifier auto-generated by the
    first must be persisted and replayed onto the second, or Google
    rejects the token exchange with "Missing code verifier" -- confirmed
    against the real OAuth server, not a hypothetical.

    Uses a real CalendarTokenStore (temp db) -- not a mocked one -- so
    save_pending_verifier/pop_pending_verifier are genuinely exercised,
    not just asserted as mock calls.
    """

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_code_verifier_from_connect_step_is_replayed_on_callback_step(self):
        token_store = CalendarTokenStore(db_path=self.db_path)
        connect_flow = _FakeFlow()
        callback_flow = _FakeFlow()

        with patch(
            "google_auth_oauthlib.flow.Flow.from_client_config",
            side_effect=[connect_flow, callback_flow],
        ):
            provider = _make_provider(token_store=token_store)

            # --- /connect step (first HTTP request, first Flow object) ---
            provider.get_authorization_url("kaivix")

            # The real value this specific Flow instance auto-generated
            # was actually persisted -- checked directly against the
            # database, not a mock call.
            conn = token_store._get_connection()
            row = conn.execute(
                "SELECT code_verifier FROM oauth_pending_verifiers WHERE state = ?",
                ("kaivix",),
            ).fetchone()
            conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row["code_verifier"], "real-pkce-verifier-abc123")

            # --- /callback step (second HTTP request, second Flow object) ---
            callback_url = "http://localhost:8000/oauth/google/callback?code=abc123&state=kaivix"
            provider.handle_oauth_callback("kaivix", callback_url)

        # The second, independent Flow instance had the first instance's
        # verifier explicitly set on it before fetch_token() ran.
        self.assertEqual(callback_flow.code_verifier, "real-pkce-verifier-abc123")
        self.assertEqual(len(callback_flow.fetch_token_calls), 1)

        # The verifier is single-use: popped, not just read.
        conn = token_store._get_connection()
        row = conn.execute(
            "SELECT code_verifier FROM oauth_pending_verifiers WHERE state = ?",
            ("kaivix",),
        ).fetchone()
        conn.close()
        self.assertIsNone(row)

        # And the token exchange actually completed and was saved.
        saved = token_store.load_token("kaivix")
        self.assertIsNotNone(saved)
        self.assertEqual(saved["token"], "access-token")

    def test_missing_pending_verifier_raises_clear_error_instead_of_attempting_exchange(self):
        token_store = CalendarTokenStore(db_path=self.db_path)
        provider = _make_provider(token_store=token_store)

        # No get_authorization_url() call happened first -- no pending
        # verifier exists for "kaivix".
        with self.assertRaises(RuntimeError) as ctx:
            provider.handle_oauth_callback(
                "kaivix",
                "http://localhost:8000/oauth/google/callback?code=abc123&state=kaivix",
            )

        self.assertIn("kaivix", str(ctx.exception))
        self.assertIsNone(token_store.load_token("kaivix"))


if __name__ == "__main__":
    unittest.main()
