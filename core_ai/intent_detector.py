from core_ai.intents import Intent


class IntentDetector:
    """
    Rule-based intent detector.
    Covers all major conversation scenarios for a sales agent.
    """

    GREETING_WORDS = {
        "hi", "hello", "hey", "howdy", "greetings",
        "good morning", "good afternoon", "good evening",
        "what's up", "whats up",
    }

    PRICING_WORDS = {
        "price", "pricing", "cost", "budget", "quote",
        "how much", "charge", "fee", "rate", "package",
        "plan", "expensive", "affordable", "invest",
    }

    MEETING_WORDS = {
        "meeting", "call", "demo", "book", "schedule",
        "appointment", "calendly", "talk", "consult",
        "when can", "set up a", "hop on",
    }

    SUPPORT_WORDS = {
        "help", "support", "issue", "problem", "broken",
        "not working", "error", "fix", "trouble", "stuck",
    }

    OBJECTION_WORDS = {
        "too expensive", "can't afford", "no budget",
        "not interested", "don't need", "already have",
        "using chatgpt", "use another", "not ready",
        "maybe later", "think about it", "not sure",
        "concerned", "worried", "doubt", "skeptical",
        "sounds like a scam", "sales trap",
        "chatgpt", "chat gpt", "already use", "use another",
        "chatgpt", "already use", "use another tool",
    }

    BUYING_SIGNAL_WORDS = {
        "sounds good", "let's do it", "let us do it", "i'm in", "lets do",
        "how do we start", "next steps", "when can we start",
        "send me a proposal", "ready to move forward",
        "integrate", "implement", "get started",
        "sign up", "purchase", "buy",
    }

    GOODBYE_WORDS = {
        "bye", "goodbye", "see you", "farewell",
        "take care", "thanks bye", "that's all",
    }

    INFORMATION_WORDS = {
        "what do you", "what does", "how does",
        "tell me about", "explain", "what is",
        "how does it work", "what can", "features",
        "capabilities", "learn more",
    }

    def detect(self, message: str) -> Intent:
        lower = message.lower()

        # Objections take priority — must be caught before greeting
        for phrase in self.OBJECTION_WORDS:
            if phrase in lower:
                return Intent.OBJECTION

        # Buying signals
        for phrase in self.BUYING_SIGNAL_WORDS:
            if phrase in lower:
                return Intent.BUYING_SIGNAL

        # Pricing
        for phrase in self.PRICING_WORDS:
            if phrase in lower:
                return Intent.PRICING

        # Meeting / demo request
        for phrase in self.MEETING_WORDS:
            if phrase in lower:
                return Intent.MEETING_REQUEST

        # Support
        for phrase in self.SUPPORT_WORDS:
            if phrase in lower:
                return Intent.SUPPORT

        # Goodbye
        for phrase in self.GOODBYE_WORDS:
            if phrase in lower:
                return Intent.GOODBYE

        # Greeting
        words = set(lower.split())
        if words & self.GREETING_WORDS:
            return Intent.GREETING

        # Information request
        for phrase in self.INFORMATION_WORDS:
            if phrase in lower:
                return Intent.INFORMATION

        return Intent.UNKNOWN
