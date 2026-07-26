from abc import ABC, abstractmethod

from core_ai.business_config import DEFAULT_BUSINESS_ID


class BaseCRM(ABC):
    @abstractmethod
    def save_lead(self, lead: dict, business_id: str = DEFAULT_BUSINESS_ID):
        """
        Save a lead to the CRM.
        """
        pass