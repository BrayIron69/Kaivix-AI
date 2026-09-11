import json

from database import postgres
from scheduling.offered_slot_store import BaseOfferedSlotStore


class PostgresOfferedSlotStore(BaseOfferedSlotStore):
    """
    Postgres backing for the times most recently offered to a visitor,
    so a booking survives the restart that used to lose it. See
    BaseOfferedSlotStore for why these are stored rather than recomputed.
    """

    def __init__(self):
        postgres.log_backend_choice("Offered slots", using_postgres=True)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS offered_slots (
                        business_id TEXT NOT NULL,
                        conversation_id TEXT NOT NULL,
                        slots JSONB NOT NULL,
                        offered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (business_id, conversation_id)
                    )
                    """
                )
        conn.close()

    def save(self, business_id: str, conversation_id: str, slots: list[dict]) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO offered_slots (business_id, conversation_id, slots)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (business_id, conversation_id) DO UPDATE SET
                        slots = EXCLUDED.slots,
                        offered_at = CURRENT_TIMESTAMP
                    """,
                    (business_id, conversation_id, json.dumps(slots)),
                )
        conn.close()

    def load(self, business_id: str, conversation_id: str) -> list[dict]:
        conn = postgres.get_connection()
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT slots FROM offered_slots
                WHERE business_id = %s AND conversation_id = %s
                """,
                (business_id, conversation_id),
            )
            row = cursor.fetchone()
        conn.close()

        if row is None:
            return []

        # JSONB comes back already decoded; a TEXT column or an older
        # row would arrive as a string, so handle both rather than
        # assume the column type never changed.
        slots = row["slots"]
        if isinstance(slots, str):
            try:
                slots = json.loads(slots)
            except (TypeError, ValueError):
                return []

        return slots if isinstance(slots, list) else []

    def clear(self, business_id: str, conversation_id: str) -> None:
        conn = postgres.get_connection()
        with conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM offered_slots
                    WHERE business_id = %s AND conversation_id = %s
                    """,
                    (business_id, conversation_id),
                )
        conn.close()
