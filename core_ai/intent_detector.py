import re

from core_ai.intents import Intent


def _compile_phrases(phrases: set[str]) -> list[re.Pattern]:
    """
    Compile keyword phrases into whole-word regex matchers.

    Previously every category was matched with a bare `phrase in lower`
    substring test, which fires on any incidental occurrence inside a
    longer word: "call" matched "too many missed calls" and classified a
    pain point as a MEETING_REQUEST, so Bray offered booking slots before
    qualification was complete. \b anchors both ends of each phrase so a
    keyword only matches when it stands on its own.

    Sorted so iteration order is stable across runs (a plain set of
    strings iterates in an order that varies with PYTHONHASHSEED).
    """
    return [
        re.compile(r"\b" + re.escape(phrase) + r"\b")
        for phrase in sorted(phrases)
    ]


class IntentDetector:
    """
    Rule-based intent detector.
    Covers all major conversation scenarios for a sales agent.

    Matching is whole-word (see _compile_phrases). Because whole-word
    matching no longer picks up inflected forms for free the way
    substring matching did, the plural/gerund variants that actually
    carry the same intent are listed explicitly below ("booking",
    "scheduling", "costs", ...). The variants deliberately left out are
    the ones that changed the meaning -- most importantly "calls", which
    is nearly always describing call volume rather than requesting one.
    """

    GREETING_WORDS = {
        "hi", "hello", "hey", "howdy", "greetings",
        "good morning", "good afternoon", "good evening",
        "what's up", "whats up",
    }

    PRICING_WORDS = {
        "price", "prices", "pricing", "cost", "costs", "quote", "quotes",
        "budget", "how much", "charge", "charges", "fee", "fees",
        "rate", "rates", "package", "packages", "plan", "plans",
        "expensive", "affordable", "invest", "investment",
    }

    MEETING_WORDS = {
        "meeting", "meetings", "call", "demo", "demos",
        "book", "booking", "schedule", "scheduling",
        "appointment", "appointments", "calendly",
        "talk", "consult", "consultation",
        "when can", "set up a", "hop on",
    }

    # Phrases where a MEETING_WORDS keyword is describing a pain point or
    # a volume of inbound calls rather than requesting one. These are
    # removed from the message before meeting matching runs (and only
    # then), so a message that mentions both -- "we miss a lot of calls,
    # can we book a call?" -- still matches on the real request.
    #
    # Only singular forms are needed: whole-word matching already stops
    # "call" from matching "calls", so the plural phrasings never reach
    # this list.
    MEETING_FALSE_POSITIVE_PHRASES = {
        "missed call",
        "call center", "call centre", "call volume",
        "call log", "call handling", "call routing",
        "cold call", "cold calling",
        "sales call", "support call",
        "after hours call", "after-hours call",
    }

    SUPPORT_WORDS = {
        "help", "support", "issue", "issues", "problem", "problems",
        "broken", "not working", "error", "errors",
        "fix", "trouble", "stuck",
    }

    OBJECTION_WORDS = {
        "too expensive", "can't afford", "no budget",
        "not interested", "don't need", "already have",
        "chatgpt", "chat gpt", "using chatgpt",
        "already use", "use another", "use another tool",
        "not ready", "maybe later", "think about it", "not sure",
        "concerned", "worried", "doubt", "skeptical",
        "sounds like a scam", "sales trap",
    }

    BUYING_SIGNAL_WORDS = {
        "sounds good", "let's do it", "let us do it", "i'm in", "lets do",
        "how do we start", "next steps", "when can we start",
        "send me a proposal", "ready to move forward",
        "integrate", "integration", "implement", "implementation",
        "get started", "sign up", "purchase", "buy",
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

    _GREETING_PATTERNS = _compile_phrases(GREETING_WORDS)
    _PRICING_PATTERNS = _compile_phrases(PRICING_WORDS)
    _MEETING_PATTERNS = _compile_phrases(MEETING_WORDS)
    _SUPPORT_PATTERNS = _compile_phrases(SUPPORT_WORDS)
    _OBJECTION_PATTERNS = _compile_phrases(OBJECTION_WORDS)
    _BUYING_SIGNAL_PATTERNS = _compile_phrases(BUYING_SIGNAL_WORDS)
    _GOODBYE_PATTERNS = _compile_phrases(GOODBYE_WORDS)
    _INFORMATION_PATTERNS = _compile_phrases(INFORMATION_WORDS)

    @staticmethod
    def _matches(patterns: list[re.Pattern], text: str) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    @classmethod
    def _strip_meeting_false_positives(cls, text: str) -> str:
        """
        Blank out known non-request uses of meeting keywords so they
        can't trigger MEETING_REQUEST, while leaving the rest of the
        message intact for any genuine request it also contains.
        """
        for phrase in sorted(cls.MEETING_FALSE_POSITIVE_PHRASES):
            text = text.replace(phrase, " ")
        return text

    def detect(self, message: str) -> Intent:
        lower = message.lower()

        # Objections take priority — must be caught before greeting
        if self._matches(self._OBJECTION_PATTERNS, lower):
            return Intent.OBJECTION

        # Buying signals
        if self._matches(self._BUYING_SIGNAL_PATTERNS, lower):
            return Intent.BUYING_SIGNAL

        # Pricing
        if self._matches(self._PRICING_PATTERNS, lower):
            return Intent.PRICING

        # Meeting / demo request
        if self._matches(
            self._MEETING_PATTERNS,
            self._strip_meeting_false_positives(lower),
        ):
            return Intent.MEETING_REQUEST

        # Support
        if self._matches(self._SUPPORT_PATTERNS, lower):
            return Intent.SUPPORT

        # Goodbye
        if self._matches(self._GOODBYE_PATTERNS, lower):
            return Intent.GOODBYE

        # Greeting. Phrase-matched like every other category so the
        # multi-word entries ("good morning") can match at all -- the
        # previous set(lower.split()) check compared whole words against
        # a set containing two-word phrases, which could never match.
        if self._matches(self._GREETING_PATTERNS, lower):
            return Intent.GREETING

        # Information request
        if self._matches(self._INFORMATION_PATTERNS, lower):
            return Intent.INFORMATION

        return Intent.UNKNOWN
