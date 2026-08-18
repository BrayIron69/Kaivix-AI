import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scheduling.google_calendar_provider import GoogleCalendarProvider

UTC = ZoneInfo("UTC")


def _make_provider(token_store=None):
    with patch.dict(
        "os.environ",
        {"GOOGLE_CLIENT_ID": "test-client-id", "GOOGLE_CLIENT_SECRET": "test-client-secret"},
    ):
        return GoogleCalendarProvider(token_store=token_store or MagicMock())


class TestCalendarConfirmationEmailAlreadyCovered(unittest.TestCase):
    """
    Backs the finding from today's investigation into item 3b (confirm
    whether Google Calendar's own invite system already emails a
    booking confirmation, or whether EmailProvider needs to send a
    separate one): create_event already calls events().insert(...,
    sendUpdates="all") with the visitor as an invited attendee, and
    Google's own Calendar API sends that attendee a real invite/
    confirmation email as a side effect of insertion -- see
    https://developers.google.com/calendar/api/v3/reference/events/insert,
    sendUpdates. Nothing needed wiring on the EmailProvider side; this
    guards the finding against a future refactor silently dropping
    sendUpdates and reintroducing the gap without anyone noticing, since
    nothing else in this codebase currently asserts on it (see
    tests/test_google_calendar_provider.py's create_event tests, none
    of which check sendUpdates).
    """

    _STORED_TOKEN = {
        "token": "access-token",
        "refresh_token": "refresh-token",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
        "expiry": None,
    }

    @patch("googleapiclient.discovery.build")
    @patch("google.oauth2.credentials.Credentials")
    def test_create_event_requests_google_to_send_the_confirmation_email(
        self, mock_credentials_cls, mock_build
    ):
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
            summary="Kaivix Demo Call - Dana",
            start_time=datetime(2026, 3, 10, 14, 0, tzinfo=UTC),
            end_time=datetime(2026, 3, 10, 15, 0, tzinfo=UTC),
            attendee_email="dana@example.com",
        )

        self.assertTrue(result["success"])

        _args, insert_kwargs = mock_service.events().insert.call_args
        self.assertEqual(insert_kwargs["sendUpdates"], "all")
        self.assertEqual(
            insert_kwargs["body"]["attendees"], [{"email": "dana@example.com"}]
        )


if __name__ == "__main__":
    unittest.main()
