from crm.sqlite_crm import SQLiteCRM


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

    def save(self, lead):
        print("[LeadService] Saving lead...")
        result = self.crm.save_lead(self._normalize_payload(lead))
        print("[LeadService] Lead saved.")
        return result

    # Backward compatibility
    def save_lead(self, lead):
        return self.save(lead)

    def get_by_email(self, email):
        return self.crm.get_lead_by_email(email)

    def get_lead_by_email(self, email):
        return self.get_by_email(email)

    def get_all(self):
        return self.crm.get_all_leads()

    def get_all_leads(self):
        return self.get_all()

    def update(self, email, **updates):
        normalized = self._normalize_payload(updates)
        normalized.pop("email", None)
        return self.crm.update_lead(email, **normalized)

    def update_lead(self, email, **updates):
        return self.update(email, **updates)

    def delete(self, email):
        return self.crm.delete_lead(email)

    def delete_lead(self, email):
        return self.delete(email)