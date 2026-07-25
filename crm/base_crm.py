from abc import ABC, abstractmethod


class BaseCRM(ABC):
    @abstractmethod
    def save_lead(self, lead: dict):
        """
        Save a lead to the CRM.
        """
        pass