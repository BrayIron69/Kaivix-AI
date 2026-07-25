from abc import ABC, abstractmethod
import json
import sqlite3
from datetime import datetime, timezone


class BaseLongTermMemoryStore(ABC):
    """
    Storage-backend contract for LongTermMemory.

    Mirrors the existing crm/base_crm.py + crm/sqlite_crm.py split: the
    LongTermMemory component (below) owns all business/merge logic and
    is backend-agnostic; a BaseLongTermMemoryStore implementation owns
    nothing but "get a profile dict by key" / "save a profile dict by
    key". Swapping SQLite for another backend later means writing a new
    subclass of this class — LongTermMemory itself does not change.
    """

    @abstractmethod
    def get(self, key: str) -> dict | None:
        """Return the stored profile dict for `key`, or None if absent."""
        raise NotImplementedError

    @abstractmethod
    def save(self, key: str, profile: dict) -> None:
        """Persist `profile` (a full profile dict) under `key`."""
        raise NotImplementedError


class SQLiteLongTermMemoryStore(BaseLongTermMemoryStore):
    """
    Default SQLite-backed implementation of BaseLongTermMemoryStore.

    Uses its own database file, separate from crm/leads.db — the CRM
    table is a narrow sales-pipeline record (crm/database.py's `leads`
    table); this table is the broader cross-session memory described in
    this milestone (pain points, objections, buying signals, previous
    conversations, preferences, notes, etc.), and the two are
    intentionally not merged into one schema.

    List-valued fields (pain_points, objections, buying_signals,
    products_of_interest, preferences, previous_conversations) are
    stored as JSON text, since SQLite has no native list type.
    """

    DB_PATH = "memory/long_term_memory.db"

    _LIST_FIELDS = (
        "products_of_interest",
        "pain_points",
        "objections",
        "buying_signals",
        "preferences",
        "previous_conversations",
    )

    _SCALAR_FIELDS = (
        "name",
        "company",
        "email",
        "industry",
        "budget",
        "timeline",
        "important_notes",
    )

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or self.DB_PATH
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Connection / schema
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        conn = self._get_connection()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS long_term_memory (
                key TEXT PRIMARY KEY,

                name TEXT DEFAULT '',
                company TEXT DEFAULT '',
                email TEXT DEFAULT '',
                industry TEXT DEFAULT '',
                budget TEXT DEFAULT '',
                timeline TEXT DEFAULT '',
                important_notes TEXT DEFAULT '',

                products_of_interest TEXT DEFAULT '[]',
                pain_points TEXT DEFAULT '[]',
                objections TEXT DEFAULT '[]',
                buying_signals TEXT DEFAULT '[]',
                preferences TEXT DEFAULT '[]',
                previous_conversations TEXT DEFAULT '[]',

                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str) -> dict | None:
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM long_term_memory WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()
        conn.close()

        if row is None:
            return None

        return self._row_to_profile(row)

    def save(self, key: str, profile: dict) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get(key)

        row_values = {field: profile.get(field, "") for field in self._SCALAR_FIELDS}
        for list_field in self._LIST_FIELDS:
            row_values[list_field] = json.dumps(profile.get(list_field) or [])

        conn = self._get_connection()
        cursor = conn.cursor()

        if existing is None:
            cursor.execute(
                """
                INSERT INTO long_term_memory (
                    key, name, company, email, industry, budget, timeline,
                    important_notes, products_of_interest, pain_points,
                    objections, buying_signals, preferences,
                    previous_conversations, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    row_values["name"],
                    row_values["company"],
                    row_values["email"],
                    row_values["industry"],
                    row_values["budget"],
                    row_values["timeline"],
                    row_values["important_notes"],
                    row_values["products_of_interest"],
                    row_values["pain_points"],
                    row_values["objections"],
                    row_values["buying_signals"],
                    row_values["preferences"],
                    row_values["previous_conversations"],
                    now,
                    now,
                ),
            )
        else:
            cursor.execute(
                """
                UPDATE long_term_memory
                SET name = ?, company = ?, email = ?, industry = ?, budget = ?,
                    timeline = ?, important_notes = ?, products_of_interest = ?,
                    pain_points = ?, objections = ?, buying_signals = ?,
                    preferences = ?, previous_conversations = ?, updated_at = ?
                WHERE key = ?
                """,
                (
                    row_values["name"],
                    row_values["company"],
                    row_values["email"],
                    row_values["industry"],
                    row_values["budget"],
                    row_values["timeline"],
                    row_values["important_notes"],
                    row_values["products_of_interest"],
                    row_values["pain_points"],
                    row_values["objections"],
                    row_values["buying_signals"],
                    row_values["preferences"],
                    row_values["previous_conversations"],
                    now,
                    key,
                ),
            )

        conn.commit()
        conn.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _row_to_profile(self, row: sqlite3.Row) -> dict:
        profile = {field: row[field] for field in self._SCALAR_FIELDS}
        profile["key"] = row["key"]
        profile["created_at"] = row["created_at"]
        profile["updated_at"] = row["updated_at"]
        for list_field in self._LIST_FIELDS:
            try:
                profile[list_field] = json.loads(row[list_field] or "[]")
            except (TypeError, ValueError):
                profile[list_field] = []
        return profile


class LongTermMemory:
    """
    LongTermMemory

    Dedicated component responsible for remembering a contact (keyed by
    email) across multiple conversations. This is durable, cross-session
    memory — distinct from both:
      - WorkingMemory, which represents only the current conversation
        and is discarded with it, and
      - ConversationSummary, which narrates only the current
        conversation.
    Neither of those is touched or duplicated by this class; this class
    only reads/writes CustomerState/LeadProfile fields that are already
    the single source of truth for that data (EntityExtractor,
    LeadIntelligenceEngine, etc. still own producing them — this class
    never re-derives or re-scores anything, it only remembers and
    recalls it across sessions).

    Fields tracked, and where they come from when persisted:
      - name, company, email, industry, budget, timeline  <- lead attrs
      - important_notes                                    <- lead.notes
      - pain_points, objections, buying_signals            <- lead attrs
                                                                (merged/
                                                                accumulated
                                                                across
                                                                conversations,
                                                                not
                                                                overwritten)
      - previous_conversations                             <- conversation_ids
                                                                seen for this
                                                                contact
      - products_of_interest, preferences                  <- reserved for
                                                                future engines;
                                                                nothing in the
                                                                current pipeline
                                                                populates these
                                                                yet, so they are
                                                                simply carried
                                                                forward unchanged
                                                                (see handoff-style
                                                                note in the
                                                                milestone report)

    Persistence is fully delegated to a BaseLongTermMemoryStore (SQLite
    by default). No SQL or file I/O lives in this class or in
    ConversationEngine — only in the store implementation.
    """

    _SCALAR_LEAD_FIELDS = ("name", "company", "industry", "budget", "timeline")
    _LIST_LEAD_FIELDS = ("pain_points", "objections", "buying_signals")

    def __init__(self, store: BaseLongTermMemoryStore | None = None):
        self.store = store or SQLiteLongTermMemoryStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recall(self, key: str) -> dict | None:
        """Return the stored long-term profile for `key` (e.g. an email), or None."""
        if not key:
            return None
        return self.store.get(key)

    def apply_to_lead(self, profile: dict, lead) -> bool:
        """
        Merge a previously recalled `profile` onto `lead`, filling in
        only fields `lead` doesn't already have a value for (scalars)
        or adding only new items (lists) — this never overwrites
        anything the current conversation has already established.

        Returns True if anything on `lead` was changed.
        """
        if not profile:
            return False

        changed = False

        for field_name in self._SCALAR_LEAD_FIELDS:
            current = getattr(lead, field_name, "") or ""
            remembered = profile.get(field_name, "") or ""
            if not current and remembered:
                setattr(lead, field_name, remembered)
                changed = True

        current_notes = getattr(lead, "notes", "") or ""
        remembered_notes = profile.get("important_notes", "") or ""
        if not current_notes and remembered_notes:
            lead.notes = remembered_notes
            changed = True

        for field_name in self._LIST_LEAD_FIELDS:
            current_list = getattr(lead, field_name, None) or []
            remembered_list = profile.get(field_name) or []
            merged = self._merge_lists(current_list, remembered_list)
            if merged != current_list:
                setattr(lead, field_name, merged)
                changed = True

        return changed

    def hydrate(self, lead) -> dict | None:
        """
        Convenience combining recall() + apply_to_lead(): looks up a
        long-term profile using `lead.email` and, if found, merges it
        onto `lead` (only-fill-empty, only-add-new-items semantics —
        see apply_to_lead). Returns the recalled profile (or None if no
        record exists yet for this contact) so a caller can also use it
        for display/prompt purposes without a second store read.
        """
        email = getattr(lead, "email", "") or ""
        if not email:
            return None

        profile = self.recall(email)
        if profile:
            self.apply_to_lead(profile, lead)
        return profile

    def remember(self, lead, conversation_id: str | None = None) -> bool:
        """
        Persist durable fields from `lead` into long-term storage,
        keyed by `lead.email`. Scalars are updated to the latest
        non-empty value; list fields (pain_points, objections,
        buying_signals) are accumulated across conversations rather
        than overwritten, since the whole point of long-term memory is
        not to lose what was learned in a previous session.

        Returns True if a profile was written, False if `lead` has no
        email yet (nothing to key the memory on).
        """
        email = getattr(lead, "email", "") or ""
        if not email:
            return False

        existing = self.store.get(email) or self._blank_profile(email)
        merged = dict(existing)
        merged["key"] = email
        merged["email"] = email

        for field_name in self._SCALAR_LEAD_FIELDS:
            incoming = getattr(lead, field_name, "") or ""
            if incoming:
                merged[field_name] = incoming

        notes = getattr(lead, "notes", "") or ""
        if notes:
            merged["important_notes"] = notes

        for field_name in self._LIST_LEAD_FIELDS:
            incoming_list = getattr(lead, field_name, None) or []
            merged[field_name] = self._merge_lists(
                merged.get(field_name) or [], incoming_list
            )

        if conversation_id:
            previous_conversations = list(merged.get("previous_conversations") or [])
            if conversation_id not in previous_conversations:
                previous_conversations.append(conversation_id)
            merged["previous_conversations"] = previous_conversations

        # Reserved for future engines (see class docstring) — carried
        # forward unchanged since nothing currently populates them.
        merged["products_of_interest"] = existing.get("products_of_interest") or []
        merged["preferences"] = existing.get("preferences") or []

        self.store.save(email, merged)
        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _merge_lists(current: list, incoming: list) -> list:
        merged = list(current)
        for item in incoming:
            if item and item not in merged:
                merged.append(item)
        return merged

    @staticmethod
    def _blank_profile(key: str) -> dict:
        return {
            "key": key,
            "name": "",
            "company": "",
            "email": key,
            "industry": "",
            "budget": "",
            "timeline": "",
            "important_notes": "",
            "products_of_interest": [],
            "pain_points": [],
            "objections": [],
            "buying_signals": [],
            "preferences": [],
            "previous_conversations": [],
        }