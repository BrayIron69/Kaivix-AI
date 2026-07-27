from abc import ABC, abstractmethod

from core_ai.business_config import DEFAULT_BUSINESS_ID


class BaseCalendarProvider(ABC):
    """
    Storage/provider-agnostic contract for calendar integrations.

    Mirrors crm/base_crm.py's shape: one abstract method per capability,
    business_id defaulting to Kaivix's own DEFAULT_BUSINESS_ID everywhere,
    so each business connects and uses its own calendar account
    independently. Swapping Google Calendar for another provider later
    means writing a new subclass of this class.

    get_free_busy_slots is read-only: it only surfaces availability.
    create_event is the one method with a real, external, hard-to-undo
    side effect -- it actually creates a calendar event -- so
    implementations must never raise from it; failures are reported in
    the returned dict instead (see its docstring below).
    """

    @abstractmethod
    def is_connected(self, business_id: str = DEFAULT_BUSINESS_ID) -> bool:
        """Whether this business has a stored, usable calendar connection."""
        raise NotImplementedError

    @abstractmethod
    def get_authorization_url(self, business_id: str = DEFAULT_BUSINESS_ID) -> str:
        """Build the URL to send this business's user to for OAuth consent."""
        raise NotImplementedError

    @abstractmethod
    def handle_oauth_callback(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        authorization_response_url: str = "",
    ) -> None:
        """Complete the OAuth flow and persist the resulting token."""
        raise NotImplementedError

    @abstractmethod
    def list_calendars(self, business_id: str = DEFAULT_BUSINESS_ID) -> list[dict]:
        """Return this business's connected account's calendars."""
        raise NotImplementedError

    @abstractmethod
    def get_free_busy_slots(
        self, business_id: str = DEFAULT_BUSINESS_ID, days_ahead: int = 7
    ) -> list[str]:
        """
        Return at most 3 upcoming open time windows within this
        business's working hours over the next `days_ahead` days, as
        human-readable strings (e.g. "Tuesday 2:00 PM - 3:00 PM") ready
        to be inserted directly into prompt text -- not raw ISO
        timestamps. Read-only: never creates or modifies an event.

        Must return an empty list (never raise) if the calendar isn't
        connected for this business_id, or if the lookup fails for any
        reason -- callers must be able to treat this as "no availability
        to offer right now" without special-casing failures.
        """
        raise NotImplementedError

    @abstractmethod
    def create_event(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        summary: str = "",
        start_time=None,
        end_time=None,
        attendee_email: str = "",
    ) -> dict:
        """
        Create a real calendar event on this business's connected
        calendar, inviting `attendee_email`. Uses whatever write scope
        was already granted at connection time -- no new consent flow.

        Must never raise: any failure (not connected, malformed
        times, the underlying API call failing) is caught by the
        implementation and reported in the returned dict instead, since
        callers need to distinguish "nothing to book" from "tried to
        book and it failed" for a real, hard-to-undo side effect like
        this one.

        Returns {"success": bool, "event_link": str | None, "error": str | None}.
        """
        raise NotImplementedError
