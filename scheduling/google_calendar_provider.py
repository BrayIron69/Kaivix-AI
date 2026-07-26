import os

from core_ai.business_config import DEFAULT_BUSINESS_ID
from scheduling.base_calendar_provider import BaseCalendarProvider
from scheduling.calendar_token_store import CalendarTokenStore

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

    def __init__(self, token_store: CalendarTokenStore | None = None):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.token_store = token_store or CalendarTokenStore()

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
