import os
from datetime import datetime, time, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID
from scheduling.base_calendar_provider import BaseCalendarProvider
from scheduling.calendar_token_store import CalendarTokenStore

# Fixed business-hours window used by get_free_busy_slots for every
# business today (9-5, Monday-Friday, in the business's own timezone --
# see BusinessConfig.identity.timezone). Per-business configurable hours
# are a later milestone; this scaffolding assumes the same window for
# everyone.
_BUSINESS_HOURS_START = time(9, 0)
_BUSINESS_HOURS_END = time(17, 0)
_MAX_RETURNED_SLOTS = 3

# Must match the redirect URI registered in Google Cloud for this OAuth
# client, and api/routers/calendar_oauth.py's /oauth/google/callback route.
#
# Local development note: this is plain HTTP on localhost. oauthlib
# refuses any non-HTTPS redirect unless OAUTHLIB_INSECURE_TRANSPORT=1 is
# set in the environment -- set that yourself (e.g. in your local .env)
# when running against localhost, the same way
# scripts/verify_google_calendar.py does. This module deliberately does
# NOT set it: that is a dev-environment concern, not something this
# module should decide for every caller. A real production deployment
# must use a genuine HTTPS redirect URI registered in Google Cloud, and
# OAUTHLIB_INSECURE_TRANSPORT must never be set there.
REDIRECT_URI = "http://localhost:8000/oauth/google/callback"

# Read + write, unlike the throwaway verify script's read-only scope --
# booking (a later milestone) needs to create events, not just read them.
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


class GoogleCalendarProvider(BaseCalendarProvider):
    """
    Google Calendar implementation of BaseCalendarProvider.

    Reuses the exact OAuth mechanics already proven working in
    scripts/verify_google_calendar.py (Flow.from_client_config, the
    refresh-if-expired logic, static_discovery=True for the API build)
    but tenant-scopes every call by business_id and persists tokens via
    CalendarTokenStore instead of a flat JSON file.

    GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are read from the environment
    at construction -- there is one shared Google Cloud OAuth app for
    all businesses today, not per-business OAuth apps (see
    CalendarTokenStore's docstring).
    """

    def __init__(
        self,
        token_store: CalendarTokenStore | None = None,
        business_config_repository: Optional[BusinessConfigRepository] = None,
    ):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.token_store = token_store or CalendarTokenStore()
        # Used only by get_free_busy_slots, to read the business's own
        # timezone (BusinessConfig.identity.timezone) -- same
        # optional-dependency pattern as ConversationEngine's own
        # business_config_repository.
        self.business_config_repository = business_config_repository or BusinessConfigRepository()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _client_config(self) -> dict:
        return {
            "web": {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI],
            }
        }

    def _build_flow(self, business_id: str):
        from google_auth_oauthlib.flow import Flow

        # state is set here, at construction, rather than passed to
        # authorization_url() -- get_authorization_url() and
        # handle_oauth_callback() build separate Flow instances (they
        # run in separate HTTP requests), and Flow's own docs require
        # state to be specified at construction time in that case for
        # it to be honored/verifiable across instances.
        return Flow.from_client_config(
            self._client_config(),
            scopes=SCOPES,
            redirect_uri=REDIRECT_URI,
            state=business_id,
        )

    def _credentials_to_dict(self, credentials) -> dict:
        return {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "scopes": credentials.scopes,
        }

    def _load_credentials(self, business_id: str):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        stored = self.token_store.load_token(business_id)
        if stored is None:
            return None

        credentials = Credentials(
            token=stored["token"],
            refresh_token=stored["refresh_token"],
            token_uri=stored["token_uri"],
            client_id=self.client_id,
            client_secret=self.client_secret,
            scopes=stored["scopes"],
        )

        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_store.save_token(business_id, self._credentials_to_dict(credentials))

        return credentials

    # ------------------------------------------------------------------
    # BaseCalendarProvider
    # ------------------------------------------------------------------

    def is_connected(self, business_id: str = DEFAULT_BUSINESS_ID) -> bool:
        return self.token_store.load_token(business_id) is not None

    def get_authorization_url(self, business_id: str = DEFAULT_BUSINESS_ID) -> str:
        flow = self._build_flow(business_id)
        auth_url, _state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )
        return auth_url

    def handle_oauth_callback(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        authorization_response_url: str = "",
    ) -> None:
        flow = self._build_flow(business_id)
        flow.fetch_token(authorization_response=authorization_response_url)
        self.token_store.save_token(business_id, self._credentials_to_dict(flow.credentials))

    def list_calendars(self, business_id: str = DEFAULT_BUSINESS_ID) -> list[dict]:
        from googleapiclient.discovery import build

        credentials = self._load_credentials(business_id)
        if credentials is None:
            raise RuntimeError(
                f"No calendar connection stored for business_id={business_id!r}. "
                f"Call get_authorization_url() / handle_oauth_callback() first."
            )

        # static_discovery avoids a network round-trip to
        # www.googleapis.com for the API discovery document -- the
        # library already ships one for Calendar v3 (see
        # scripts/verify_google_calendar.py, which hit and fixed the
        # same thing).
        service = build("calendar", "v3", credentials=credentials, static_discovery=True)
        calendar_list = service.calendarList().list().execute()
        return calendar_list.get("items", [])

    def get_free_busy_slots(
        self, business_id: str = DEFAULT_BUSINESS_ID, days_ahead: int = 7
    ) -> list[str]:
        # Contract (see BaseCalendarProvider): never raise, always return
        # a list -- an empty one whenever the calendar isn't connected or
        # anything about the lookup fails, so callers can treat this as
        # "nothing to offer right now" without special-casing failures.
        try:
            credentials = self._load_credentials(business_id)
            if credentials is None:
                return []

            business_config = self.business_config_repository.load(business_id)
            tz = ZoneInfo(business_config.identity.timezone)
            now = datetime.now(tz)

            day_windows = self._business_hour_windows(now, tz, days_ahead)
            if not day_windows:
                return []

            from googleapiclient.discovery import build

            # static_discovery avoids a network round-trip to
            # www.googleapis.com for the API discovery document -- same
            # reasoning as list_calendars above.
            service = build("calendar", "v3", credentials=credentials, static_discovery=True)
            freebusy_response = (
                service.freebusy()
                .query(
                    body={
                        "timeMin": day_windows[0][0].isoformat(),
                        "timeMax": day_windows[-1][1].isoformat(),
                        # Single connected account's own calendar -- which
                        # specific calendar to check is a later,
                        # multi-calendar milestone.
                        "items": [{"id": "primary"}],
                    }
                )
                .execute()
            )

            busy_blocks = [
                (
                    datetime.fromisoformat(block["start"]).astimezone(tz),
                    datetime.fromisoformat(block["end"]).astimezone(tz),
                )
                for block in freebusy_response.get("calendars", {})
                .get("primary", {})
                .get("busy", [])
            ]

            open_slots = []
            for window_start, window_end in day_windows:
                open_slots.extend(self._subtract_busy(window_start, window_end, busy_blocks))
                if len(open_slots) >= _MAX_RETURNED_SLOTS:
                    break

            return [
                self._format_slot(start, end) for start, end in open_slots[:_MAX_RETURNED_SLOTS]
            ]

        except Exception:
            return []

    # ------------------------------------------------------------------
    # get_free_busy_slots internals
    # ------------------------------------------------------------------

    @staticmethod
    def _business_hour_windows(now: datetime, tz: ZoneInfo, days_ahead: int) -> list[tuple]:
        """
        Build the list of (start, end) business-hour windows (9-5,
        Monday-Friday, in `tz`) from today through `days_ahead` days out.
        Today's window is clamped to start at `now` if business hours are
        already underway, and skipped entirely if today's business hours
        have already ended.
        """
        windows = []
        for offset in range(days_ahead + 1):
            day = (now + timedelta(days=offset)).date()
            if day.weekday() >= 5:  # Saturday=5, Sunday=6
                continue

            window_start = datetime.combine(day, _BUSINESS_HOURS_START, tzinfo=tz)
            window_end = datetime.combine(day, _BUSINESS_HOURS_END, tzinfo=tz)

            if window_end <= now:
                continue
            if window_start < now:
                window_start = now
            if window_start >= window_end:
                continue

            windows.append((window_start, window_end))

        return windows

    @staticmethod
    def _subtract_busy(
        window_start: datetime, window_end: datetime, busy_blocks: list[tuple]
    ) -> list[tuple]:
        """
        Return the free (start, end) sub-windows of [window_start,
        window_end) left after removing every overlapping busy block.
        """
        relevant = sorted(
            (max(busy_start, window_start), min(busy_end, window_end))
            for busy_start, busy_end in busy_blocks
            if busy_end > window_start and busy_start < window_end
        )

        open_slots = []
        cursor = window_start
        for busy_start, busy_end in relevant:
            if busy_start > cursor:
                open_slots.append((cursor, busy_start))
            cursor = max(cursor, busy_end)

        if cursor < window_end:
            open_slots.append((cursor, window_end))

        return open_slots

    @staticmethod
    def _format_slot(start: datetime, end: datetime) -> str:
        weekday = start.strftime("%A")
        start_str = start.strftime("%I:%M %p").lstrip("0")
        end_str = end.strftime("%I:%M %p").lstrip("0")
        return f"{weekday} {start_str} - {end_str}"
