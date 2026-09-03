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
        # Google returns an expiry with the token; it has to be persisted
        # or every later load treats the token as never-expiring.
        mock_credentials.expiry = datetime(2026, 7, 29, 12, 0, 0)

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
                "expiry": "2026-07-29T12:00:00",
            },
        )

    @patch("scheduling.render_env_sync.persist_calendar_refresh_token")
    @patch("google_auth_oauthlib.flow.Flow.from_client_config")
    def test_callback_persists_refresh_token_to_render_when_present(
        self, mock_from_client_config, mock_persist
    ):
        """
        calendar_tokens.db does not survive a redeploy (Render has no
        persistent disk) -- this durable write is what actually does.
        Must fire with the exact business_id/refresh_token this callback
        just obtained from Google.
        """
        mock_credentials = MagicMock()
        mock_credentials.token = "access-token"
        mock_credentials.refresh_token = "refresh-token"
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.scopes = SCOPES
        mock_credentials.expiry = datetime(2026, 7, 29, 12, 0, 0)

        mock_flow = MagicMock()
        mock_flow.credentials = mock_credentials
        mock_from_client_config.return_value = mock_flow

        provider = _make_provider(token_store=MagicMock())
        provider.handle_oauth_callback(
            "business-a",
            "http://localhost:8000/oauth/google/callback?code=abc123&state=business-a",
        )

        mock_persist.assert_called_once_with("business-a", "refresh-token")

    @patch("scheduling.render_env_sync.persist_calendar_refresh_token")
    @patch("google_auth_oauthlib.flow.Flow.from_client_config")
    def test_callback_does_not_persist_when_google_returned_no_refresh_token(
        self, mock_from_client_config, mock_persist
    ):
        """
        Defensive only -- get_authorization_url always passes
        prompt="consent" so a real connect/reconnect does receive one --
        but must never call Render's API with None regardless.
        """
        mock_credentials = MagicMock()
        mock_credentials.token = "access-token"
        mock_credentials.refresh_token = None
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.scopes = SCOPES
        mock_credentials.expiry = datetime(2026, 7, 29, 12, 0, 0)

        mock_flow = MagicMock()
        mock_flow.credentials = mock_credentials
        mock_from_client_config.return_value = mock_flow

        provider = _make_provider(token_store=MagicMock())
        provider.handle_oauth_callback(
            "business-a",
            "http://localhost:8000/oauth/google/callback?code=abc123&state=business-a",
        )

        mock_persist.assert_not_called()


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
        mock_credentials.expiry = datetime(2020, 1, 1, 0, 0, 0)
        mock_credentials.refresh_token = "refresh-token"
        mock_credentials.token = "refreshed-access-token"
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.scopes = SCOPES
        mock_credentials_cls.return_value = mock_credentials

        # A real refresh() replaces expiry with the new token's; the
        # refreshed expiry (not the stale one) is what must be persisted.
        def _refresh(_request):
            mock_credentials.expiry = datetime(2030, 1, 1, 0, 0, 0)

        mock_credentials.refresh.side_effect = _refresh

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
                "expiry": "2030-01-01T00:00:00",
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

    def test_is_connected_false_when_expired_and_no_refresh_token(self):
        """
        A row with no refresh_token whose access token has already
        expired can never recover on its own (_load_credentials only
        refreshes when credentials.refresh_token is truthy) -- this is
        the fix for is_connected() previously passing on a genuinely
        dead connection, which only failed later, silently, inside
        get_free_busy_windows.
        """
        expired = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)).isoformat()
        token_store = MagicMock()
        token_store.load_token.return_value = {
            "business_id": "business-a",
            "token": "t",
            "refresh_token": None,
            "expiry": expired,
        }

        provider = _make_provider(token_store=token_store)
        self.assertFalse(provider.is_connected("business-a"))

    def test_is_connected_true_when_expired_but_refresh_token_present(self):
        """
        An expired access token with a live refresh_token is the normal
        state between conversations -- access tokens are short-lived by
        design, and _load_credentials refreshes them transparently on
        next use. Must NOT report as disconnected, or the calendar would
        falsely appear dead every time nobody has chatted in the last
        hour.
        """
        expired = (datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)).isoformat()
        token_store = MagicMock()
        token_store.load_token.return_value = {
            "business_id": "business-a",
            "token": "t",
            "refresh_token": "refresh-token",
            "expiry": expired,
        }

        provider = _make_provider(token_store=token_store)
        self.assertTrue(provider.is_connected("business-a"))

    def test_is_connected_true_when_not_yet_expired_and_no_refresh_token(self):
        not_yet_expired = (
            datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1)
        ).isoformat()
        token_store = MagicMock()
        token_store.load_token.return_value = {
            "business_id": "business-a",
            "token": "t",
            "refresh_token": None,
            "expiry": not_yet_expired,
        }

        provider = _make_provider(token_store=token_store)
        self.assertTrue(provider.is_connected("business-a"))

    @patch("scheduling.render_env_sync.load_refresh_token")
    def test_is_connected_true_from_env_var_even_with_no_local_row(self, mock_load_refresh_token):
        """
        The exact scenario this whole fix exists for: a fresh process
        after a redeploy where calendar_tokens.db was wiped (no local
        row at all), but GOOGLE_CALENDAR_REFRESH_TOKENS still holds this
        business's refresh_token. Must report connected without ever
        consulting the local store.
        """
        mock_load_refresh_token.return_value = "env-refresh-token"
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        self.assertTrue(provider.is_connected("business-a"))
        token_store.load_token.assert_not_called()

    @patch("scheduling.render_env_sync.load_refresh_token")
    def test_is_connected_falls_back_to_local_row_when_env_var_has_nothing_for_this_business(
        self, mock_load_refresh_token
    ):
        mock_load_refresh_token.return_value = None
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        self.assertFalse(provider.is_connected("business-a"))
        token_store.load_token.assert_called_once_with("business-a")


class TestGoogleCalendarProviderLoadCredentialsFromEnv(unittest.TestCase):
    """
    _load_credentials preferring GOOGLE_CALENDAR_REFRESH_TOKENS over the
    local SQLite row -- the durable copy wins because the local row may
    have been wiped by a redeploy, or may simply be stale relative to a
    token rotated through a later reconnect.
    """

    @patch("google.auth.transport.requests.Request")
    @patch("google.oauth2.credentials.Credentials")
    @patch("scheduling.render_env_sync.load_refresh_token")
    def test_builds_credentials_from_env_token_and_refreshes_even_with_no_local_row(
        self, mock_load_refresh_token, mock_credentials_cls, mock_request_cls
    ):
        mock_load_refresh_token.return_value = "env-refresh-token"
        mock_credentials = MagicMock()
        mock_credentials_cls.return_value = mock_credentials

        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        result = provider._load_credentials("business-a")

        mock_credentials_cls.assert_called_once_with(
            token=None,
            refresh_token="env-refresh-token",
            token_uri="https://oauth2.googleapis.com/token",
            client_id=provider.client_id,
            client_secret=provider.client_secret,
            scopes=SCOPES,
            expiry=None,
        )
        mock_credentials.refresh.assert_called_once()
        token_store.save_token.assert_called_once()
        self.assertIs(result, mock_credentials)

    @patch("google.auth.transport.requests.Request")
    @patch("google.oauth2.credentials.Credentials")
    @patch("scheduling.render_env_sync.load_refresh_token")
    def test_env_token_wins_over_a_present_but_different_local_row(
        self, mock_load_refresh_token, mock_credentials_cls, mock_request_cls
    ):
        """
        Even when a local row DOES exist, the env-sourced token is
        treated as the source of truth -- it may have been rotated
        through a reconnect that happened on a different process/deploy
        than the one that wrote the current local row.
        """
        mock_load_refresh_token.return_value = "env-refresh-token"
        mock_credentials = MagicMock()
        mock_credentials_cls.return_value = mock_credentials

        token_store = MagicMock()
        token_store.load_token.return_value = {
            "business_id": "business-a",
            "token": "stale-local-token",
            "refresh_token": "stale-local-refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": SCOPES,
            "expiry": None,
        }

        provider = _make_provider(token_store=token_store)
        provider._load_credentials("business-a")

        _, kwargs = mock_credentials_cls.call_args
        self.assertEqual(kwargs["refresh_token"], "env-refresh-token")

    @patch("scheduling.render_env_sync.load_refresh_token")
    def test_falls_back_to_local_row_when_env_var_has_nothing_for_this_business(
        self, mock_load_refresh_token
    ):
        mock_load_refresh_token.return_value = None
        token_store = MagicMock()
        token_store.load_token.return_value = None

        provider = _make_provider(token_store=token_store)
        result = provider._load_credentials("business-a")

        self.assertIsNone(result)


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

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_exception_during_lookup_is_logged_not_silently_swallowed(
        self, mock_credentials_cls, mock_build
    ):
        """
        The bare `except Exception: return []` used to swallow the real
        error entirely -- a broken/expired token failing here looked
        identical in the logs to "genuinely no availability," which is
        exactly why the false-booking-confirmation gap went undetected.
        The real exception must now reach the logger before the
        empty-list fallback returns.
        """
        token_store = MagicMock()
        token_store.load_token.return_value = dict(self._STORED_TOKEN)

        mock_credentials = MagicMock()
        mock_credentials.expired = False
        mock_credentials_cls.return_value = mock_credentials

        mock_build.side_effect = RuntimeError(
            "invalid_grant: token has been expired or revoked"
        )

        provider = _make_provider(token_store=token_store)
        mock_logger = MagicMock()
        provider.logger = mock_logger

        windows = provider.get_free_busy_windows("business-a")

        self.assertEqual(windows, [])
        mock_logger.error.assert_called_once()
        logged_message = mock_logger.error.call_args[0][0]
        self.assertIn("RuntimeError", logged_message)
        self.assertIn("invalid_grant: token has been expired or revoked", logged_message)
        self.assertIn("business-a", logged_message)


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


class TestGoogleCalendarProviderProactiveRefresh(unittest.TestCase):
    """
    Expiry-driven refresh (_needs_refresh / _load_credentials).

    Before expiry was persisted, every reloaded credential had
    expiry=None, which google-auth documents as "never expires" --
    Credentials.expired returned False unconditionally, so the refresh
    branch never ran and the first sign of a dead token was a 401.
    """

    @staticmethod
    def _naive_utc_now():
        return datetime.now(UTC).replace(tzinfo=None)

    def _stored(self, expiry):
        return {
            "business_id": "business-a",
            "token": "stored-token",
            "refresh_token": "refresh-token",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": SCOPES,
            "expiry": expiry,
        }

    def _load_with(self, stored_expiry, mock_credentials_cls, credentials_expired=False):
        token_store = MagicMock()
        token_store.load_token.return_value = self._stored(stored_expiry)

        mock_credentials = MagicMock()
        mock_credentials.refresh_token = "refresh-token"
        mock_credentials.token = "some-token"
        mock_credentials.token_uri = "https://oauth2.googleapis.com/token"
        mock_credentials.scopes = SCOPES
        mock_credentials.expired = credentials_expired
        # Credentials() is mocked, so it won't set .expiry from the kwarg
        # the way a real one does -- mirror it explicitly.
        mock_credentials.expiry = GoogleCalendarProvider._deserialize_expiry(
            stored_expiry
        )
        mock_credentials_cls.return_value = mock_credentials

        provider = _make_provider(token_store=token_store)
        provider._load_credentials("business-a")

        return mock_credentials, token_store

    @patch("google.oauth2.credentials.Credentials")
    def test_token_expiring_within_the_margin_is_refreshed_before_use(
        self, mock_credentials_cls
    ):
        expiring_soon = (self._naive_utc_now() + timedelta(minutes=2)).isoformat()

        credentials, token_store = self._load_with(expiring_soon, mock_credentials_cls)

        credentials.refresh.assert_called_once()
        token_store.save_token.assert_called_once()

    @patch("google.oauth2.credentials.Credentials")
    def test_already_expired_token_is_refreshed(self, mock_credentials_cls):
        long_gone = (self._naive_utc_now() - timedelta(hours=3)).isoformat()

        credentials, _ = self._load_with(long_gone, mock_credentials_cls)

        credentials.refresh.assert_called_once()

    @patch("google.oauth2.credentials.Credentials")
    def test_token_with_plenty_of_life_left_is_not_refreshed(
        self, mock_credentials_cls
    ):
        plenty_left = (self._naive_utc_now() + timedelta(minutes=55)).isoformat()

        credentials, token_store = self._load_with(plenty_left, mock_credentials_cls)

        credentials.refresh.assert_not_called()
        token_store.save_token.assert_not_called()

    @patch("google.oauth2.credentials.Credentials")
    def test_refresh_fires_earlier_than_the_libraries_own_threshold(
        self, mock_credentials_cls
    ):
        """
        google-auth's REFRESH_THRESHOLD is ~3m45s. A token 4 minutes out
        is 'not expired' by that measure but is inside our 5-minute
        margin -- this is the window the live 401s came from.
        """
        four_minutes_out = (self._naive_utc_now() + timedelta(minutes=4)).isoformat()

        credentials, _ = self._load_with(
            four_minutes_out, mock_credentials_cls, credentials_expired=False
        )

        credentials.refresh.assert_called_once()

    @patch("google.oauth2.credentials.Credentials")
    def test_stored_expiry_is_passed_into_credentials(self, mock_credentials_cls):
        self._load_with("2030-01-01T00:00:00", mock_credentials_cls)

        _args, kwargs = mock_credentials_cls.call_args
        self.assertEqual(kwargs["expiry"], datetime(2030, 1, 1, 0, 0, 0))

    @patch("google.oauth2.credentials.Credentials")
    def test_timezone_aware_stored_expiry_is_normalized_to_naive_utc(
        self, mock_credentials_cls
    ):
        """
        google-auth compares expiry against a naive utcnow(); an aware
        datetime would raise on every comparison.
        """
        self._load_with("2030-01-01T00:00:00+02:00", mock_credentials_cls)

        _args, kwargs = mock_credentials_cls.call_args
        self.assertEqual(kwargs["expiry"], datetime(2029, 12, 31, 22, 0, 0))
        self.assertIsNone(kwargs["expiry"].tzinfo)

    @patch("google.oauth2.credentials.Credentials")
    def test_unknown_expiry_falls_back_to_the_library_check_when_expired(
        self, mock_credentials_cls
    ):
        """Rows written before the expiry column existed."""
        credentials, _ = self._load_with(
            None, mock_credentials_cls, credentials_expired=True
        )

        credentials.refresh.assert_called_once()

    @patch("google.oauth2.credentials.Credentials")
    def test_unknown_expiry_does_not_refresh_a_credential_reported_valid(
        self, mock_credentials_cls
    ):
        credentials, _ = self._load_with(
            None, mock_credentials_cls, credentials_expired=False
        )

        credentials.refresh.assert_not_called()

    @patch("google.oauth2.credentials.Credentials")
    def test_unparseable_stored_expiry_does_not_raise(self, mock_credentials_cls):
        credentials, _ = self._load_with(
            "not-a-timestamp", mock_credentials_cls, credentials_expired=False
        )

        credentials.refresh.assert_not_called()

    def test_serialize_expiry_handles_none_and_non_datetimes(self):
        self.assertIsNone(GoogleCalendarProvider._serialize_expiry(None))
        self.assertIsNone(GoogleCalendarProvider._serialize_expiry("whatever"))
        self.assertEqual(
            GoogleCalendarProvider._serialize_expiry(datetime(2030, 1, 1, 0, 0, 0)),
            "2030-01-01T00:00:00",
        )


if __name__ == "__main__":
    unittest.main()
