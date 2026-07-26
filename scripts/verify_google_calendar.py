#!/usr/bin/env python
"""
One-time, throwaway verification that the Google Calendar OAuth setup
actually works end-to-end.

This is NOT the real CalendarProvider integration -- it exists only to
prove the OAuth client ID/secret registered in Google Cloud, and the
calendar.readonly scope, actually work before any real
CalendarProvider architecture gets designed. Deliberately kept out of
core_ai/, crm/, memory/, and every engine file.

What it does:
  1. Loads GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET from the environment
     (.env), the same way config.py loads GROQ_API_KEY.
  2. Runs a one-time local OAuth flow: opens a browser for you to log in
     and consent, using http://localhost:8000/oauth/google/callback as
     the redirect (matching what's registered in Google Cloud), for the
     calendar.readonly scope only.
  3. Saves the resulting token to scripts/.verify_token.json so
     re-running this script doesn't require re-consenting every time
     (refreshed automatically once the access token expires).
  4. Makes one real API call -- calendarList().list() -- and prints
     each calendar's name and ID.

Run from the repo root:
    python scripts/verify_google_calendar.py
"""

from __future__ import annotations

import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import os

load_dotenv()

# The registered redirect URI is http://localhost:8000/... (plain HTTP,
# loopback-only) -- Google's own OAuth quickstart docs document this as
# the standard, safe pattern for local-development/native-app flows, but
# oauthlib itself refuses any non-HTTPS redirect unless this is set.
# Scoped to this throwaway script only; never applies to a real deployed
# redirect URI.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")

REDIRECT_URI = "http://localhost:8000/oauth/google/callback"
CALLBACK_HOST = "localhost"
CALLBACK_PORT = 8000
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

TOKEN_PATH = Path(__file__).resolve().parent / ".verify_token.json"


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """
    Captures exactly one incoming redirect from Google
    (http://localhost:8000/oauth/google/callback?code=...&state=...)
    and stores the full URL on the server instance so the main script
    can hand it to Flow.fetch_token(authorization_response=...).
    """

    def do_GET(self):  # noqa: N802 -- required method name from BaseHTTPRequestHandler
        self.server.callback_url = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{self.path}"

        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h3>Google Calendar verification complete.</h3>"
            b"<p>You can close this tab and return to the terminal.</p>"
            b"</body></html>"
        )

    def log_message(self, format, *args):  # noqa: A002 -- silence default request logging
        pass


def _wait_for_oauth_redirect() -> str:
    server = HTTPServer((CALLBACK_HOST, CALLBACK_PORT), _OAuthCallbackHandler)
    server.callback_url = None
    print(f"Waiting for the OAuth redirect on {REDIRECT_URI} ...")
    server.handle_request()  # blocks until exactly one request arrives
    server.server_close()
    if not server.callback_url:
        raise RuntimeError("Did not receive an OAuth redirect from Google.")
    return server.callback_url


def _run_browser_consent_flow():
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [REDIRECT_URI],
        }
    }

    flow = Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )

    print("\nOpening a browser window for you to log into Google and approve access...")
    print("If nothing opens automatically, visit this URL manually:")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)

    callback_url = _wait_for_oauth_redirect()
    flow.fetch_token(authorization_response=callback_url)
    return flow.credentials


def _save_credentials(credentials) -> None:
    TOKEN_PATH.write_text(
        json.dumps(
            {
                "token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_uri": credentials.token_uri,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scopes": credentials.scopes,
            }
        ),
        encoding="utf-8",
    )


def _load_saved_credentials():
    from google.oauth2.credentials import Credentials

    if not TOKEN_PATH.is_file():
        return None

    data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    return Credentials(
        token=data["token"],
        refresh_token=data["refresh_token"],
        token_uri=data["token_uri"],
        client_id=data["client_id"],
        client_secret=data["client_secret"],
        scopes=data["scopes"],
    )


def _get_credentials():
    from google.auth.transport.requests import Request

    credentials = _load_saved_credentials()

    if credentials and credentials.valid:
        return credentials

    if credentials and credentials.expired and credentials.refresh_token:
        print("Saved token expired -- refreshing without a new browser consent...")
        credentials.refresh(Request())
        _save_credentials(credentials)
        return credentials

    credentials = _run_browser_consent_flow()
    _save_credentials(credentials)
    return credentials


def main() -> int:
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        print(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set (checked via "
            "the same os.getenv(...) + load_dotenv() pattern config.py uses "
            "for GROQ_API_KEY). Add them to .env and re-run."
        )
        return 1

    try:
        credentials = _get_credentials()

        from googleapiclient.discovery import build

        # static_discovery avoids an extra network round-trip to
        # www.googleapis.com for the API discovery document -- the
        # library already ships one for Calendar v3.
        service = build("calendar", "v3", credentials=credentials, static_discovery=True)
        calendar_list = service.calendarList().list().execute()
        calendars = calendar_list.get("items", [])

        print(f"\nFound {len(calendars)} calendar(s):")
        for calendar in calendars:
            print(f"  - {calendar.get('summary')} (id: {calendar.get('id')})")

        print("\nSUCCESS: Google Calendar API is working")
        return 0

    except Exception as exc:  # noqa: BLE001 -- top-level catch-all for a clear failure message
        print(f"\nFAILURE: Google Calendar verification failed: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
