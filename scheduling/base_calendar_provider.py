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

    This is scaffolding only -- booking-specific methods (create_event,
    check availability, etc.) intentionally do not exist yet. That is a
    later milestone; this one is the OAuth + token-storage foundation.
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
