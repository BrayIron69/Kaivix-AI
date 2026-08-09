import os
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID
from scheduling.base_calendar_provider import BaseCalendarProvider
from scheduling.calendar_token_store import CalendarTokenStore
from utils.logger import Logger

# Fixed business-hours window used by get_free_busy_slots for every
# business today (9-5, Monday-Friday, in the business's own timezone --
# see BusinessConfig.identity.timezone). Per-business configurable hours
# are a later milestone; this scaffolding assumes the same window for
# everyone.
_BUSINESS_HOURS_START = time(9, 0)
_BUSINESS_HOURS_END = time(17, 0)
_MAX_RETURNED_SLOTS = 3

# Fixed appointment length used to chunk each open gap into bookable
# slots -- without this, a totally empty day comes back as one giant
# multi-hour "slot" (e.g. 9:00 AM - 5:00 PM), which isn't something a
# visitor can meaningfully pick as a single appointment time. Hardcoded
# for now, consistent with minimum-change-per-milestone; per-business
# configurable appointment length is a later concern.
_APPOINTMENT_DURATION = timedelta(minutes=30)

# How long before a stored access token actually expires we refresh it.
# Wider than google-auth's own ~3m45s REFRESH_THRESHOLD on purpose: that
# one is evaluated when the credential is constructed, so a request that
# starts just inside it can still reach Google after the token has died
# -- the "occasional stale-token 401" seen during live verification.
_EXPIRY_REFRESH_MARGIN = timedelta(minutes=5)

# Must match the redirect URI registered in Google Cloud for this OAuth
# client, and api/routers/calendar_oauth.py's /oauth/google/callback route.
#
# Derived from PUBLIC_BASE_URL (read once at import time, same pattern as
# config.py's other env-driven values) rather than hardcoded, so this is
# correct per-deployment instead of always pointing at localhost --
# Render (and any other real deployment) needs its own real base URL
# here, not the local dev one. Defaults to localhost:8000 when
# PUBLIC_BASE_URL isn't set, so nothing breaks for existing local
# testing.
#
# Local development note: localhost is plain HTTP. oauthlib refuses any
# non-HTTPS redirect unless OAUTHLIB_INSECURE_TRANSPORT=1 is set in the
# environment -- set that yourself (e.g. in your local .env) when
# running against localhost, the same way scripts/verify_google_calendar.py
# does. This module deliberately does NOT set it: that is a
# dev-environment concern, not something this module should decide for
# every caller. A real production deployment must use a genuine HTTPS
# PUBLIC_BASE_URL registered in Google Cloud, and OAUTHLIB_INSECURE_TRANSPORT
# must never be set there.
REDIRECT_URI = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000") + "/oauth/google/callback"

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
        logger: Optional[Logger] = None,
    ):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.token_store = token_store or CalendarTokenStore()
        # Used only by get_free_busy_slots, to read the business's own
        # timezone (BusinessConfig.identity.timezone) -- same
        # optional-dependency pattern as ConversationEngine's own
        # business_config_repository.
        self.business_config_repository = business_config_repository or BusinessConfigRepository()
        self.logger = logger or Logger()

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
            "expiry": self._serialize_expiry(getattr(credentials, "expiry", None)),
        }

    @staticmethod
    def _serialize_expiry(expiry) -> str | None:
        """ISO-8601 text for CalendarTokenStore, or None if unknown."""
        if not isinstance(expiry, datetime):
            return None
        return expiry.isoformat()

    @staticmethod
    def _deserialize_expiry(value) -> Optional[datetime]:
        """
        Parse a stored expiry back into the naive-UTC datetime
        google.oauth2.credentials.Credentials expects. google-auth
        compares expiry against its own naive _helpers.utcnow(), so an
        aware datetime here would raise on every comparison -- any
        offset is applied and then dropped. Unparseable/absent values
        return None, which callers treat as "unknown".
        """
        if isinstance(value, datetime):
            parsed = value
        elif value:
            try:
                parsed = datetime.fromisoformat(str(value))
            except ValueError:
                return None
        else:
            return None

        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

        return parsed

    def _needs_refresh(self, credentials) -> bool:
        """
        Decide whether to refresh *before* using a token, rather than
        waiting for the API to reject it.

        Previously this was `credentials.expired` alone, which looked
        proactive but never fired: expiry was not persisted, so every
        reloaded credential had expiry=None, and google-auth documents
        expiry=None as "never expires" (Credentials.expired returns
        False). Every token therefore went to Google unchecked and the
        first sign of a stale one was a 401.

        With expiry stored we refresh once it is inside
        _EXPIRY_REFRESH_MARGIN of running out -- deliberately wider than
        google-auth's own ~3m45s threshold, so a long-running request
        can't start just inside the library's window and land after the
        token dies. Falls back to the library's check when expiry is
        unknown (rows written before the column existed).
        """
        expiry = self._deserialize_expiry(getattr(credentials, "expiry", None))

        if expiry is None:
            return bool(credentials.expired)

        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        return now_utc_naive >= expiry - _EXPIRY_REFRESH_MARGIN

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
            expiry=self._deserialize_expiry(stored.get("expiry")),
        )

        if self._needs_refresh(credentials) and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_store.save_token(business_id, self._credentials_to_dict(credentials))

        return credentials

    # ------------------------------------------------------------------
    # BaseCalendarProvider
    # ------------------------------------------------------------------

    def is_connected(self, business_id: str = DEFAULT_BUSINESS_ID) -> bool:
        """
        Whether a usable calendar connection exists for this business.

        A stored row alone used to be treated as "connected" -- but a
        row with no refresh_token whose access token has already expired
        can never recover on its own (_load_credentials only refreshes
        when credentials.refresh_token is truthy), so callers like
        _maybe_attach_availability would pass this check and only
        discover the connection is actually dead later, inside
        get_free_busy_windows' exception handling.

        A refresh_token being present is deliberately NOT treated as a
        disqualifier even when the stored expiry has passed -- that is
        the normal, expected state between conversations (access tokens
        are short-lived by design) and _load_credentials already
        refreshes them transparently on next use. Reuses
        _deserialize_expiry, the same expiry-parsing logic
        _needs_refresh uses for the proactive-refresh fix.
        """
        stored = self.token_store.load_token(business_id)
        if stored is None:
            return False

        if stored.get("refresh_token"):
            return True

        expiry = self._deserialize_expiry(stored.get("expiry"))
        if expiry is None:
            # Unknown expiry and no refresh_token to fall back on --
            # nothing here to disqualify the connection on.
            return True

        now_utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        return now_utc_naive < expiry

    def get_authorization_url(self, business_id: str = DEFAULT_BUSINESS_ID) -> str:
        flow = self._build_flow(business_id)
        auth_url, _state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        # authorization_url() just auto-generated flow.code_verifier (PKCE)
        # and encoded its hash into auth_url as code_challenge. This Flow
        # instance is request-scoped and discarded once this method
        # returns -- handle_oauth_callback() below runs in a separate HTTP
        # request and builds its own, independent Flow object. Without
        # persisting code_verifier here, that second Flow's fetch_token()
        # call has no verifier to send back, and Google rejects the token
        # exchange with "Missing code verifier" (confirmed via a real
        # end-to-end run, not a hypothetical).
        self.token_store.save_pending_verifier(business_id, flow.code_verifier)

        return auth_url

    def handle_oauth_callback(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        authorization_response_url: str = "",
    ) -> None:
        code_verifier = self.token_store.pop_pending_verifier(business_id)
        if code_verifier is None:
            raise RuntimeError(
                f"No pending OAuth handshake found for business_id={business_id!r}. "
                f"The authorization link may have expired or already been used -- "
                f"call get_authorization_url() again to start a fresh consent flow."
            )

        flow = self._build_flow(business_id)
        # Must be set explicitly: this Flow instance is a brand-new object
        # (see _build_flow's docstring comment on `state`) and never went
        # through authorization_url(), so it never generated its own
        # code_verifier -- it needs the one saved by get_authorization_url()
        # above, retrieved via pop_pending_verifier() just above.
        flow.code_verifier = code_verifier

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
        """
        Human-readable formatting of get_free_busy_windows() below --
        kept as its own method (rather than having callers format windows
        themselves) since PromptBuilder/ConversationPlan only ever need
        the display strings, not the underlying datetimes.
        """
        windows = self.get_free_busy_windows(business_id, days_ahead)
        return [self.format_slot(start, end) for start, end in windows]

    def get_free_busy_windows(
        self, business_id: str = DEFAULT_BUSINESS_ID, days_ahead: int = 7
    ) -> list[tuple[datetime, datetime]]:
        """
        The structured (start, end) datetime pairs behind
        get_free_busy_slots()'s display strings. ConversationEngine uses
        this form (not get_free_busy_slots()'s formatted text) to
        remember exactly which real time window a visitor picked, so
        booking it later never depends on re-parsing a display string
        like "Tuesday 2:00 PM - 3:00 PM" back into a date -- an
        inherently ambiguous operation once more than a few days have
        passed (which Tuesday?).

        Contract (see BaseCalendarProvider): never raise, always return a
        list -- an empty one whenever the calendar isn't connected or
        anything about the lookup fails, so callers can treat this as
        "nothing to offer right now" without special-casing failures.
        """
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
                for gap_start, gap_end in self._subtract_busy(
                    window_start, window_end, busy_blocks
                ):
                    open_slots.extend(
                        self._chunk_into_slots(gap_start, gap_end, _APPOINTMENT_DURATION)
                    )
                    if len(open_slots) >= _MAX_RETURNED_SLOTS:
                        break
                if len(open_slots) >= _MAX_RETURNED_SLOTS:
                    break

            return open_slots[:_MAX_RETURNED_SLOTS]

        except Exception as error:
            # Previously swallowed silently -- a broken/expired token
            # failing here was indistinguishable in the logs from
            # "genuinely no availability," which is exactly how the
            # false-booking-confirmation gap went undetected: the
            # calendar lookup died quietly and the pipeline carried on
            # with an empty slot list as if nothing were wrong.
            self.logger.error(
                f"[GoogleCalendarProvider] get_free_busy_windows failed "
                f"(business_id={business_id!r}): "
                f"{type(error).__name__}: {error}"
            )
            return []

    def create_event(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        summary: str = "",
        start_time: datetime = None,
        end_time: datetime = None,
        attendee_email: str = "",
    ) -> dict:
        """
        Create a real calendar event on the business's connected primary
        calendar, with `attendee_email` invited. Uses the
        calendar.events scope already granted at connection time -- no
        new consent needed.

        Never raises: any failure (not connected, malformed times, the
        API call itself failing) is caught and reported in the returned
        dict instead, since callers need to distinguish "nothing to book"
        from "tried to book and it failed" -- two very different
        outcomes for a real, hard-to-undo side effect like this one.

        Returns {"success": bool, "event_link": str | None, "error": str | None}.
        """
        try:
            credentials = self._load_credentials(business_id)
            if credentials is None:
                return {
                    "success": False,
                    "event_link": None,
                    "error": f"No calendar connection stored for business_id={business_id!r}.",
                }

            if start_time is None or end_time is None:
                return {
                    "success": False,
                    "event_link": None,
                    "error": "start_time and end_time are required.",
                }

            from googleapiclient.discovery import build

            service = build("calendar", "v3", credentials=credentials, static_discovery=True)
            event_body = {
                "summary": summary,
                "start": {"dateTime": start_time.isoformat()},
                "end": {"dateTime": end_time.isoformat()},
            }
            if attendee_email:
                event_body["attendees"] = [{"email": attendee_email}]

            created_event = (
                service.events()
                .insert(calendarId="primary", body=event_body, sendUpdates="all")
                .execute()
            )

            return {
                "success": True,
                "event_link": created_event.get("htmlLink"),
                "error": None,
            }

        except Exception as error:
            return {
                "success": False,
                "event_link": None,
                "error": str(error),
            }

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
    def _chunk_into_slots(
        gap_start: datetime, gap_end: datetime, duration: timedelta
    ) -> list[tuple]:
        """
        Split one open [gap_start, gap_end) gap into sequential,
        fixed-length (start, end) slots of exactly `duration`. A trailing
        remainder shorter than `duration` is dropped entirely -- never
        returned as a too-short slot.
        """
        slots = []
        cursor = gap_start
        while cursor + duration <= gap_end:
            slots.append((cursor, cursor + duration))
            cursor += duration
        return slots

    @staticmethod
    def format_slot(start: datetime, end: datetime) -> str:
        weekday = start.strftime("%A")
        start_str = start.strftime("%I:%M %p").lstrip("0")
        end_str = end.strftime("%I:%M %p").lstrip("0")
        return f"{weekday} {start_str} - {end_str}"
