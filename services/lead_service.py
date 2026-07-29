from crm.sqlite_crm import SQLiteCRM
from core_ai.business_config import DEFAULT_BUSINESS_ID


_PLACEHOLDER_VALUES = {"string", "none", "null"}


class LeadService:
    """
    Business layer for lead management.

    This class is the only interface the rest of the
    application should use for lead persistence.
    """

    def __init__(self):
        self.crm = SQLiteCRM()

    def _clean_text(self, value):
        if value is None:
            return ""

        if not isinstance(value, str):
            return value

        cleaned = value.strip()

        if cleaned.lower() in _PLACEHOLDER_VALUES:
            return ""

        return cleaned

    def _normalize_payload(self, lead):
        if hasattr(lead, "to_dict"):
            data = lead.to_dict()
        elif isinstance(lead, dict):
            data = lead.copy()
        else:
            raise TypeError("Unsupported lead type.")

        normalized = {}

        for key, value in data.items():
            if isinstance(value, str):
                normalized[key] = self._clean_text(value)
            else:
                normalized[key] = value

        company = self._clean_text(
            normalized.get("company") or normalized.get("business")
        )

        normalized["company"] = company
        normalized["business"] = company

        normalized["priority"] = (
            self._clean_text(normalized.get("priority")) or "Cold"
        )
        normalized["status"] = (
            self._clean_text(normalized.get("status")) or "New"
        )
        normalized["notes"] = self._clean_text(normalized.get("notes"))
        normalized["score"] = int(normalized.get("score") or 0)

        if normalized.get("last_contacted") in ("", None):
            normalized["last_contacted"] = None

        if normalized.get("created_at") in ("", None):
            normalized["created_at"] = None

        if normalized.get("score_reasons") is None:
            normalized["score_reasons"] = []

        return normalized

    def save(self, lead, business_id=DEFAULT_BUSINESS_ID):
        print("[LeadService] Saving lead...")
        result = self.crm.save_lead(
            self._normalize_payload(lead), business_id=business_id
        )
        print("[LeadService] Lead saved.")
        return result

    # Backward compatibility
    def save_lead(self, lead, business_id=DEFAULT_BUSINESS_ID):
        return self.save(lead, business_id=business_id)

    def get_by_email(self, email, business_id=DEFAULT_BUSINESS_ID):
        return self.crm.get_lead_by_email(email, business_id=business_id)

    def get_lead_by_email(self, email, business_id=DEFAULT_BUSINESS_ID):
        return self.get_by_email(email, business_id=business_id)

    def get_all(self, business_id=DEFAULT_BUSINESS_ID):
        return self.crm.get_all_leads(business_id=business_id)

    def get_all_leads(self, business_id=DEFAULT_BUSINESS_ID):
        return self.get_all(business_id=business_id)

    def update(self, email, business_id=DEFAULT_BUSINESS_ID, **updates):
        normalized = self._normalize_payload(updates)
        normalized.pop("email", None)
        normalized.pop("business_id", None)
        return self.crm.update_lead(email, business_id=business_id, **normalized)

    def update_lead(self, email, business_id=DEFAULT_BUSINESS_ID, **updates):
        return self.update(email, business_id=business_id, **updates)

    def delete(self, email, business_id=DEFAULT_BUSINESS_ID):
        return self.crm.delete_lead(email, business_id=business_id)

    def delete_lead(self, email, business_id=DEFAULT_BUSINESS_ID):
        return self.delete(email, business_id=business_id)