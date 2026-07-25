from core_ai.lead_profile import LeadProfile


class QualificationEngine:
    """
    Determines whether a lead is qualified and
    identifies which required fields are still missing.
    """

    def __init__(self):

        self.required_fields = [
            "name",
            "email",
            "company",
            "budget",
            "timeline",
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