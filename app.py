import uuid
from core_ai.conversation_engine import ConversationEngine
from utils.logger import Logger


def main():
    logger = Logger()
    logger.log_startup()

    engine = ConversationEngine()
    session_id = str(uuid.uuid4())

    print("\n" + "=" * 56)
    print("  Kaivix Labs — AI Sales Agent")
    print("  Powered by ConversationEngine v2")
    print("=" * 56)
    print("  Type 'quit' to end the session\n")

    opening = engine.process_message(session_id, "Hey, just landed on the website")
    print(f"Bray: {opening}\n")

    while True:
        user_input = input("Visitor: ").strip()

        if user_input.lower() in ["quit", "exit", "q"]:
            print("\nSession ended.")
            logger.log_shutdown("Closed by user.")
            break

        if not user_input:
            continue

        logger.log_user(user_input)
        response = engine.process_message(session_id, user_input)
        print(f"\nBray: {response}\n")
        logger.log_ai(response)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nSession ended.")
    except Exception as error:
        logger = Logger()
        logger.log_error(error)
        raise