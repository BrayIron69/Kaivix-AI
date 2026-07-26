from typing import Optional

from core_ai.business_config import (
    BusinessConfig,
    BusinessConfigRepository,
    DEFAULT_BUSINESS_ID,
)
from core_ai.lead_profile import LeadProfile

# Shared, process-lifetime repository for the default (Kaivix) BusinessConfig
# used whenever a caller doesn't pass one explicitly (same pattern as
# core_ai/prompt_builder.py's _default_business_config_repository).
_default_business_config_repository = BusinessConfigRepository()


class QualificationEngine:
    """
    Determines whether a lead is qualified and
    identifies which required fields are still missing.
    """

    def __init__(self, business_config: Optional[BusinessConfig] = None):

        if business_config is None:
            business_config = _default_business_config_repository.load(DEFAULT_BUSINESS_ID)

        self.required_fields = [
            field.id
            for field in business_config.qualification.fields
            if field.required
        ]

    def get_missing_fields(
        self,
        lead: LeadProfile,
    ) -> list[str]:

        missing = []

        for field in self.required_fields:

            value = getattr(
                lead,
                field,
                "",
            )

            if value is None or str(value).strip() == "":
                missing.append(field)

        return missing

    def is_qualified(
        self,
        lead: LeadProfile,
    ) -> bool:

        return len(
            self.get_missing_fields(lead)
        ) == 0

    def qualification_progress(
        self,
        lead: LeadProfile,
    ) -> dict:

        collected = 0

        for field in self.required_fields:

            value = getattr(
                lead,
                field,
                "",
            )

            if value not in ("", None):
                collected += 1

        total = len(self.required_fields)

        return {
            "collected": collected,
            "total": total,
            "missing": self.get_missing_fields(lead),
            "qualified": collected == total,
            "completion_percentage": round(
                collected / total * 100,
                1,
            ),
        }