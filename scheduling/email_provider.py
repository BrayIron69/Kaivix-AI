import base64
import os
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from core_ai.business_config import DEFAULT_BUSINESS_ID
from scheduling.calendar_token_store import CalendarTokenStore
from scheduling.google_calendar_provider import GoogleCalendarProvider, _EXPIRY_REFRESH_MARGIN
from utils.logger import Logger

# Must be present in the connected account's granted scopes (see
# GoogleCalendarProvider.SCOPES) for a send to be attempted at all --
# not merely requested, but actually echoed back by Google's own token
# response, since that's what CalendarTokenStore's `scopes` column
# holds (see GoogleCalendarProvider._credentials_to_dict).
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class EmailProvider:
    """
    Real Gmail sending via the founder's connected Google Workspace
    account.

    Deliberately reuses GoogleCalendarProvider's OAuth connection rather
    than inventing a second one: same GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET
    shared OAuth app, same CalendarTokenStore row per business_id (one
    Google connection per business, covering every scope granted at
    consent time -- see CalendarTokenStore's docstring), same proactive
    refresh-before-expiry margin (_EXPIRY_REFRESH_MARGIN, imported
    directly rather than redefined, so the two providers can never drift
    on when a token counts as "about to expire"). There is no
    /oauth/gmail/connect route and none is needed -- gmail.send was
    added to GoogleCalendarProvider.SCOPES, so the one existing
    /oauth/google/connect consent screen grants both calendar and email
    access in a single flow.

    _load_credentials below intentionally mirrors
    GoogleCalendarProvider._load_credentials's structure line-for-line
    (same Credentials construction, same refresh-if-needed check, same
    save-back-after-refresh) rather than subclassing or importing a
    shared instance method, since GoogleCalendarProvider's version is
    already covered by its own well-exercised test suite and refactoring
    it into a shared base purely to serve this new class would risk that
    coverage for no behavioral gain -- the two delicate, easy-to-get-
    wrong pieces (expiry parsing, refresh-margin comparison) are pulled
    from GoogleCalendarProvider directly (its @staticmethod
    _deserialize_expiry/_serialize_expiry, and the shared
    _EXPIRY_REFRESH_MARGIN constant) so there is still exactly one
    definition of each, not two that can silently diverge.
    """

    def __init__(
        self,
        token_store: Optional[CalendarTokenStore] = None,
        logger: Optional[Logger] = None,
    ):
        self.client_id = os.getenv("GOOGLE_CLIENT_ID")
        self.client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
        self.token_store = token_store or CalendarTokenStore()
        self.logger = logger or Logger()

    # ------------------------------------------------------------------
    # Internal -- credential loading (mirrors GoogleCalendarProvider,
    # see class docstring for why this isn't shared code instead)
    # ------------------------------------------------------------------

    def _needs_refresh(self, credentials) -> bool:
        expiry = GoogleCalendarProvider._deserialize_expiry(
            getattr(credentials, "expiry", None)
        )
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
            expiry=GoogleCalendarProvider._deserialize_expiry(stored.get("expiry")),
        )

        if self._needs_refresh(credentials) and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_store.save_token(
                business_id,
                {
                    "token": credentials.token,
                    "refresh_token": credentials.refresh_token,
                    "token_uri": credentials.token_uri,
                    "scopes": credentials.scopes,
                    "expiry": GoogleCalendarProvider._serialize_expiry(
                        getattr(credentials, "expiry", None)
                    ),
                },
            )

        return credentials

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_connected(self, business_id: str = DEFAULT_BUSINESS_ID) -> bool:
        """
        Whether this business has a stored Google connection that has
        actually been granted gmail.send.

        Deliberately NOT the same check as GoogleCalendarProvider.is_connected:
        a row existing is not enough here, since a connection made before
        gmail.send was added to SCOPES has a real, usable token with only
        the two calendar scopes -- Google does not retroactively grant a
        scope that was never consented to. Checking `stored["scopes"]`
        (what Google's token response actually echoed back) rather than
        assuming the current SCOPES list was granted is what makes this
        accurate for an account that hasn't reconnected yet.
        """
        stored = self.token_store.load_token(business_id)
        if stored is None:
            return False
        return GMAIL_SEND_SCOPE in (stored.get("scopes") or [])

    def send_email(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        to: str = "",
        subject: str = "",
        body_text: str = "",
    ) -> dict:
        """
        Send a real email via the Gmail API. Mirrors
        GoogleCalendarProvider.create_event's contract for a real,
        external, side-effecting call: never raises, every failure mode
        (no recipient, not connected, scope not granted, the API call
        itself failing) is caught and reported in the returned dict
        instead, since callers need to distinguish "nothing to send"
        from "tried to send and it failed."

        Returns {"success": bool, "error": str | None}.
        """
        try:
            if not to:
                return {"success": False, "error": "No recipient email address."}

            credentials = self._load_credentials(business_id)
            if credentials is None:
                return {
                    "success": False,
                    "error": f"No Google connection stored for business_id={business_id!r}.",
                }

            if GMAIL_SEND_SCOPE not in (credentials.scopes or []):
                return {
                    "success": False,
                    "error": (
                        "Connected Google account has not granted "
                        "gmail.send. Reconnect via /oauth/google/connect "
                        "to add email sending -- OAuth scopes are fixed "
                        "at consent time and cannot be granted "
                        "incrementally."
                    ),
                }

            from googleapiclient.discovery import build

            service = build("gmail", "v1", credentials=credentials, static_discovery=True)

            message = MIMEText(body_text)
            message["to"] = to
            message["subject"] = subject
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

            service.users().messages().send(userId="me", body={"raw": raw}).execute()

            return {"success": True, "error": None}

        except Exception as error:
            self.logger.error(
                f"[EmailProvider] send_email failed "
                f"(business_id={business_id!r}, to={to!r}): "
                f"{type(error).__name__}: {error}"
            )
            return {"success": False, "error": str(error)}
