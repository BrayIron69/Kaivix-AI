from core_ai.business_config import DEFAULT_BUSINESS_ID
from crm.base_crm import BaseCRM
from database import postgres

try:
    from core_ai.lead_profile import LeadProfile
except ImportError:
    LeadProfile = None

try:
    from crm.lead import Lead
except ImportError:
    Lead = None


class PostgresCRM(BaseCRM):
    """
    Postgres-backed CRM persistence, so captured leads survive a deploy.

    SQLiteCRM writes crm/leads.db, which sits on Render's filesystem.
    That filesystem has no persistent disk and is wiped on every single
    deploy, so every lead Bray had ever captured was destroyed on the
    next push -- confirmed against live production, where the admin
    dashboard listed zero leads and a lead created minutes earlier had
    already gone. This is the same root cause as the calendar token
    (9ec91fd) and the email connection (ecbe506), in the place where it
    costs the most: the leads ARE the product's output.

    Behaviour is identical to SQLiteCRM by design, not by coincidence.
    tests/test_crm_contract.py runs one shared scenario suite against
    BOTH implementations, which exists because of a lesson learned
    earlier the same day: EmailProvider deliberately MIRRORED
    GoogleCalendarProvider rather than sharing code, then silently
    missed a critical fix that its twin received, and stayed broken in
    production for weeks. Two implementations of one contract need a
    test that proves they still agree, not a comment promising they do.

    Differences from SQLiteCRM are dialect only:
      - %s placeholders rather than ?
      - SERIAL rather than INTEGER PRIMARY KEY AUTOINCREMENT
      - rows arrive as dicts (see database/postgres.get_connection)
    """

    def __init__(self):
        postgres.log_backend_choice("CRM leads", using_postgres=True)
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """
        Create the leads table if it isn't there yet.

        Same create-on-connect approach every SQLite store here already
        uses, rather than a migration tool: there is one table, it is
        additive, and introducing Alembic to serve it would be a larger
        change than the thing it manages. UNIQUE(business_id, email)
        matches the SQLite schema's own constraint and is what makes
        save_lead's upsert safe against a race.
        """
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS leads (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL DEFAULT '',
                        email TEXT NOT NULL,
                        phone TEXT,
                        company TEXT,
                        business TEXT,
                        industry TEXT,
                        budget TEXT,
                        timeline TEXT,
                        pain_point TEXT,
                        decision_maker TEXT,
                        score INTEGER DEFAULT 0,
                        priority TEXT DEFAULT 'Cold',
                        status TEXT DEFAULT 'New',
                        notes TEXT DEFAULT '',
                        last_contacted TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        business_id TEXT NOT NULL DEFAULT 'kaivix',
                        conversation_id TEXT,
                        UNIQUE (business_id, email)
                    )
                    """
                )
        conn.close()

    # ------------------------------------------------------------------
    # Helpers -- identical semantics to SQLiteCRM's
    # ------------------------------------------------------------------

    def _lead_to_dict(self, lead):
        if LeadProfile and isinstance(lead, LeadProfile):
            data = lead.to_dict()
        elif Lead and isinstance(lead, Lead):
            data = lead.to_dict()
        elif isinstance(lead, dict):
            data = lead.copy()
        else:
            raise TypeError("Unsupported lead type.")

        if "company" in data and "business" not in data:
            data["business"] = data["company"]

        return data

    def _merge(self, existing, incoming):
        merged = existing.copy()
        for key, value in incoming.items():
            if value not in ("", None):
                merged[key] = value
        return merged

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_lead(self, lead, business_id=DEFAULT_BUSINESS_ID):
        lead = self._lead_to_dict(lead)

        email = lead.get("email")
        if not email:
            raise ValueError("Lead email is required.")

        existing = self.get_lead_by_email(email, business_id=business_id)

        if existing is None:
            conn = postgres.get_connection()
            with conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO leads (
                            name, email, phone, company, business, industry,
                            budget, timeline, pain_point, decision_maker,
                            score, priority, status, notes, last_contacted,
                            business_id, conversation_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (business_id, email) DO NOTHING
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
                            business_id,
                            lead.get("conversation_id") or None,
                        ),
                    )
            conn.close()
            return self.get_lead_by_email(email, business_id=business_id)

        existing = self._lead_to_dict(existing)
        merged = self._merge(existing, lead)

        # email/business_id are the lookup key, not generic SET fields.
        merged.pop("email", None)
        merged.pop("business_id", None)

        self.update_lead(email, business_id=business_id, **merged)

        return self.get_lead_by_email(email, business_id=business_id)

    def get_all_leads(self, business_id=DEFAULT_BUSINESS_ID):
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT * FROM leads
                WHERE business_id = %s
                ORDER BY created_at DESC
                """,
                (business_id,),
            )
            rows = cursor.fetchall()
        conn.close()

        if Lead:
            return [Lead.from_row(row) for row in rows]
        return rows

    def get_lead_by_email(self, email, business_id=DEFAULT_BUSINESS_ID):
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM leads WHERE email = %s AND business_id = %s",
                (email, business_id),
            )
            row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        if Lead:
            return Lead.from_row(row)
        return row

    def update_lead(self, email, business_id=DEFAULT_BUSINESS_ID, **updates):
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
            "conversation_id",
        ]

        fields = []
        values = []

        for key, value in updates.items():
            if key not in allowed:
                continue
            if value in ("", None):
                continue
            fields.append(f"{key} = %s")
            values.append(value)

        if not fields:
            return False

        values.append(email)
        values.append(business_id)

        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    UPDATE leads
                    SET {", ".join(fields)}
                    WHERE email = %s AND business_id = %s
                    """,
                    values,
                )
                updated = cursor.rowcount > 0
        conn.close()

        return updated

    def delete_lead(self, email, business_id=DEFAULT_BUSINESS_ID):
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM leads WHERE email = %s AND business_id = %s",
                    (email, business_id),
                )
                deleted = cursor.rowcount > 0
        conn.close()

        return deleted
