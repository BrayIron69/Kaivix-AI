from collections import defaultdict


class ConversationMemory:
    """
    Simple in-memory conversation storage.

    This is the first implementation. Later it can be replaced
    with Redis, SQLite, or another persistent memory backend
    without changing the ConversationEngine.
    """

    def __init__(self):
        self._conversations = defaultdict(list)

    def add_user_message(self, conversation_id: str, message: str):
        self._conversations[conversation_id].append(
            {
                "role": "user",
                "content": message,
            }
        )

    def add_assistant_message(self, conversation_id: str, message: str):
        self._conversations[conversation_id].append(
            {
                "role": "assistant",
                "content": message,
            }
        )

    def get_conversation(self, conversation_id: str):
        return self._conversations.get(conversation_id, []).copy()

    def clear(self, conversation_id: str):
        self._conversations.pop(conversation_id, None)