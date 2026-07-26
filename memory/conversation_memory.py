from core_ai.business_config import DEFAULT_BUSINESS_ID
from memory.conversation_store import BaseConversationStore, SQLiteConversationStore


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
        self.store = store or SQLiteConversationStore()

    def add_user_message(self, conversation_id: str, message: str):
        self.store.add_message(self.business_id, conversation_id, "user", message)

    def add_assistant_message(self, conversation_id: str, message: str):
        self.store.add_message(self.business_id, conversation_id, "assistant", message)

    def get_conversation(self, conversation_id: str):
        return self.store.get_messages(self.business_id, conversation_id)

    def clear(self, conversation_id: str):
        self.store.clear(self.business_id, conversation_id)
