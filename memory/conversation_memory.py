from core_ai.business_config import DEFAULT_BUSINESS_ID
from memory.conversation_store import BaseConversationStore, SQLiteConversationStore


def _default_store() -> BaseConversationStore:
    """
    Postgres when DATABASE_URL is set, SQLite otherwise.

    Deployment infrastructure rather than a per-business choice, so it
    follows the environment rather than providers.yaml -- see
    crm/lead_conversations.get_lead_conversation_links for the same
    reasoning. Resolved per construction, never cached at import, so a
    test that sets DATABASE_URL gets the backend it asked for.

    SQLite is NOT a safe default on Render: that filesystem is wiped on
    every deploy, which is how every transcript this product ever
    recorded was lost. It stays the local-dev default because local dev
    has a real disk.
    """
    from database import postgres

    if postgres.is_configured():
        from memory.postgres_conversation_store import PostgresConversationStore

        return PostgresConversationStore()

    return SQLiteConversationStore()


class ConversationMemory:
    """
    Per-business conversation storage.

    Persistence is fully delegated to a BaseConversationStore (SQLite
    by default, see memory/conversation_store.py) — no SQL or file I/O
    lives in this class or in ConversationEngine, only in the store
    implementation. No caching layer: every call reads fresh from the
    store, matching how CRM and LongTermMemory already work (simplicity
    over premature optimization at this scale).
    """

    def __init__(
        self,
        business_id: str = DEFAULT_BUSINESS_ID,
        store: BaseConversationStore | None = None,
    ):
        self.business_id = business_id
        self.store = store or _default_store()

    def add_user_message(self, conversation_id: str, message: str):
        self.store.add_message(self.business_id, conversation_id, "user", message)

    def add_assistant_message(self, conversation_id: str, message: str):
        self.store.add_message(self.business_id, conversation_id, "assistant", message)

    def get_conversation(self, conversation_id: str):
        return self.store.get_messages(self.business_id, conversation_id)

    def clear(self, conversation_id: str):
        self.store.clear(self.business_id, conversation_id)

    def link_visitor(self, conversation_id: str, visitor_id: str):
        """
        Record which visitor this conversation belongs to.

        Idempotent, so the caller may call it on every turn without
        checking whether the link already exists -- see
        BaseConversationStore.link_visitor for why a later, differing
        visitor_id is ignored rather than honoured.
        """
        self.store.link_visitor(self.business_id, conversation_id, visitor_id)

    def get_visitor_id(self, conversation_id: str):
        """Which visitor owns this conversation, or None."""
        return self.store.get_visitor_id(self.business_id, conversation_id)

    def list_conversations(self, visitor_id: str, limit: int | None = None):
        """
        This visitor's conversations within this business, most recently
        active first.

        `limit` is passed through only when given, so the store's own
        default stays the single place that number is defined.
        """
        if limit is None:
            return self.store.list_conversations(self.business_id, visitor_id)

        return self.store.list_conversations(self.business_id, visitor_id, limit)
