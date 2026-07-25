from core_ai.conversation_engine import ConversationEngine


class ChatService:
    """
    Service responsible for handling chat requests
    and delegating AI reasoning to the ConversationEngine.
    """

    def __init__(self):
        self.engine = ConversationEngine()

    def chat(
        self,
        conversation_id: str,
        message: str,
    ) -> str:
        return self.engine.process_message(
            conversation_id=conversation_id,
            user_message=message,
        )