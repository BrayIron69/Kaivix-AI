from abc import ABC, abstractmethod

from core_ai.business_config import DEFAULT_BUSINESS_ID


class BaseCRM(ABC):
    """
    The CRM contract LeadService depends on.

    Previously this declared save_lead alone, while LeadService called five
    methods -- so a second implementation could satisfy the ABC and still
    crash the first time anything read a lead back. The remaining four are
    declared here so "implements BaseCRM" actually means "usable by
    LeadService".

    Every method is business-scoped. business_id is not optional context:
    it is part of the lookup key, and leaving it out of a WHERE clause is
    how one business ends up reading another's leads.
    """

    @abstractmethod
    def save_lead(self, lead: dict, business_id: str = DEFAULT_BUSINESS_ID):
        """
        Save a lead to the CRM.

        Implementations are expected to upsert: merge into the existing
        record when (email, business_id) already exists rather than
        creating a duplicate.
        """

    @abstractmethod
    def get_lead_by_email(self, email: str, business_id: str = DEFAULT_BUSINESS_ID):
        """
        Return the single lead for (email, business_id), or None.

        Must not match a lead belonging to a different business_id, even
        when the email is identical.
        """

    @abstractmethod
    def get_all_leads(self, business_id: str = DEFAULT_BUSINESS_ID):
        """Return every lead for this business_id, and no others."""

    @abstractmethod
    def update_lead(self, email: str, business_id: str = DEFAULT_BUSINESS_ID, **updates):
        """Apply updates to the lead identified by (email, business_id)."""

    @abstractmethod
    def delete_lead(self, email: str, business_id: str = DEFAULT_BUSINESS_ID):
        """Delete the lead identified by (email, business_id)."""
