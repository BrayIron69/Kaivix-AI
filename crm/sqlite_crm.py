from crm.base_crm import BaseCRM
from crm.database import get_connection

try:
    from core_ai.lead_profile import LeadProfile
except ImportError:
    LeadProfile = None

try:
    from crm.lead import Lead
except ImportError:
    Lead = None


class SQLiteCRM(BaseCRM):
    """
    SQLite-backed CRM persistence layer.

    Responsibilities:
    - insert new leads
    - update existing leads
    - preserve non-empty data
    - support LeadProfile and legacy Lead objects
    """

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    def _lead_to_dict(self, lead):
        if LeadProfile and isinstance(lead, LeadProfile):
            data = lead.to_dict()
        elif Lead and isinstance(lead, Lead):
            data = lead.to_dict()
        elif isinstance(lead, dict):
            data = lead.copy()
        else:
            raise TypeError("Unsupported lead type.")

        # Backward compatibility:
        # If the caller uses company, mirror it to business.
        if "company" in data and "business" not in data:
            data["business"] = data["company"]

        return data

    def _merge(self, existing, incoming):
        merged = existing.copy()

        for key, value in incoming.items():
            if value not in ("", None):
                merged[key] = value

        return merged

    # --------------------------------------------------
    # Public API
    # --------------------------------------------------

    def save_lead(self, lead):
        lead = self._lead_to_dict(lead)

        email = lead.get("email")
        if not email:
            raise ValueError("Lead email is required.")

        existing = self.get_lead_by_email(email)

        # --------------------------------------------------
        # INSERT
        # --------------------------------------------------
        if existing is None:
            print(f"[SQLiteCRM] Creating new lead: {email}")

            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                INSERT INTO leads (
                    name,
                    email,
                    phone,
                    company,
                    business,
                    industry,
                    budget,
                    timeline,
                    pain_point,
                    decision_maker,
                    score,
                    priority,
                    status,
                    notes,
                    last_contacted
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lead.get("name", ""),
                    email,
                    lead.get("phone", ""),
                    lead.get("company", ""),
                    lead.get("business", ""),
                    lead.get("industry", ""),
                    lead.get("budget", ""),
                    lead.get("timeline", ""),
                    lead.get("pain_point", ""),
                    lead.get("decision_maker", ""),
                    lead.get("score", 0),
                    lead.get("priority", "Cold"),
                    lead.get("status", "New"),
                    lead.get("notes", ""),
                    lead.get("last_contacted"),
                ),
            )

            conn.commit()
            conn.close()

            print(f"[SQLiteCRM] Save complete: {email}")
            return self.get_lead_by_email(email)

        # --------------------------------------------------
        # UPDATE
        # --------------------------------------------------
        print(f"[SQLiteCRM] Updating existing lead: {email}")

        existing = self._lead_to_dict(existing)
        merged = self._merge(existing, lead)

        # email is the lookup key; do not send it to update_lead again
        merged.pop("email", None)

        self.update_lead(email, **merged)

        print(f"[SQLiteCRM] Save complete: {email}")
        return self.get_lead_by_email(email)

    def get_all_leads(self):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT *
            FROM leads
            ORDER BY created_at DESC
            """
        )

        rows = cursor.fetchall()
        conn.close()

        if Lead:
            return [Lead.from_row(row) for row in rows]

        return rows

    def get_lead_by_email(self, email):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT *
            FROM leads
            WHERE email = ?
            """,
            (email,),
        )

        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        if Lead:
            return Lead.from_row(row)

        return row

    def update_lead(self, email, **updates):
        allowed = [
            "name",
            "phone",
            "company",
            "business",
            "industry",
            "budget",
            "timeline",
            "pain_point",
            "decision_maker",
            "score",
            "priority",
            "status",
            "notes",
            "last_contacted",
        ]

        fields = []
        values = []

        for key, value in updates.items():
            if key not in allowed:
                continue

            if value in ("", None):
                continue

            fields.append(f"{key} = ?")
            values.append(value)

        if not fields:
            return False

        values.append(email)

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            f"""
            UPDATE leads
            SET {", ".join(fields)}
            WHERE email = ?
            """,
            values,
        )

        conn.commit()
        updated = cursor.rowcount > 0
        conn.close()

        return updated

    def delete_lead(self, email):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM leads
            WHERE email = ?
            """,
            (email,),
        )

        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()

        return deleted