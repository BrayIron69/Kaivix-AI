import re


def _compile_phrases(phrases: set[str]) -> list[re.Pattern]:
    """
    Compile keyword phrases into whole-word regex matchers.

    Same discipline as core_ai/intent_detector.py's _compile_phrases: \b
    anchors both ends so a phrase only matches when it stands on its
    own, not as a fragment of an unrelated word. Sorted so iteration
    order is stable across runs.
    """
    return [
        re.compile(r"\b" + re.escape(phrase) + r"\b")
        for phrase in sorted(phrases)
    ]


class UnbackedActionCategory:
    """
    A request for something this system has no real, deterministic way
    to back. Values are also used as evals/run_conversation_evals.py
    scenario-adjacent identifiers and log tags, so keep them stable.
    """

    OUT_OF_CHAT_MESSAGE = "out_of_chat_message"
    ALTERNATE_BOOKING_MECHANISM = "alternate_booking_mechanism"
    HUMAN_HANDOFF = "human_handoff"


class UnbackedActionDetector:
    """
    Detects a visitor asking Bray to do something this codebase has no
    real code path for -- send anything outside this chat, confirm a
    booking through some mechanism other than the real numbered-slots
    flow, or hand the conversation to a human.

    Built after a live incident where a real visitor was told (1) to
    "check your email and select a time" to confirm a booking -- a
    mechanism that has never existed, real booking has always been
    numbered options inside the chat -- and (2) that a checklist "had
    been emailed," twice, when no email-sending code exists anywhere in
    this system. ENGINE_RULES rule 12 (core_ai/prompt_builder.py) asks
    the model never to fabricate an action, but live production testing
    found it only holds about half the time -- it is a soft instruction
    with nothing actually enforcing it.

    This is the enforcement. Matching one of these categories short-
    circuits ConversationEngine.process_message before the LLM is ever
    called (see _maybe_decline_unbacked_action) -- the same gating
    principle plan.booking_confirmation / plan.booking_failed already
    use for booking (an unset flag means the model was never told a
    booking happened), extended to cover the categories that had no
    equivalent gate at all. Rule 12 stays in ENGINE_RULES as a second
    layer for whatever this phrase list doesn't anticipate; the actual
    guarantee for these three categories no longer depends on it.

    Whole-word phrase matching, same style and the same false-positive
    discipline as core_ai/intent_detector.py: every phrase requires a
    directional verb aimed at Bray ("email me", "text me"), not the
    bare noun ("email", "text") -- a visitor giving their own email
    address, or asking what Bray's email is, must never match.
    """

    # A visitor asking Bray to send something through a channel outside
    # this chat -- email, text/SMS, WhatsApp, or a file/document. No
    # send_email/send_mail/SMS/WhatsApp code path exists anywhere in
    # this codebase (confirmed by repo-wide search during the
    # investigation this responds to).
    OUT_OF_CHAT_MESSAGE_PHRASES = {
        "email me", "e-mail me", "mail me",
        "send me an email", "send me a email", "send me an e-mail",
        "email that to me", "email it to me", "email this to me",
        "send it to my email", "send that to my email", "send this to my email",
        "text me", "send me a text", "send me an sms", "sms me",
        "text that to me", "text it to me", "text this to me",
        "whatsapp me", "send me a whatsapp",
        "send me a pdf", "send me a document", "send me a file",
        "send me a copy",
    }

    # A visitor asking Bray to confirm, share, or handle booking through
    # anything other than the real numbered-slots-in-chat flow (see
    # core_ai/conversation_engine.py's _maybe_attach_availability /
    # _maybe_resolve_booking). Checked ahead of OUT_OF_CHAT_MESSAGE so
    # phrasing that overlaps both ("email me the available times")
    # reports the more specific category.
    ALTERNATE_BOOKING_MECHANISM_PHRASES = {
        "email me a link", "email me the link", "email me a time",
        "email me the times", "email me some times", "email me times",
        "email me the available times", "email me available times",
        "email me some available times", "email me available slots",
        "email me some available slots",
        "email me a slot", "email me the slots", "email me some slots",
        "text me a time", "text me the times", "text me a link",
        "text me the available times",
        "send me a link to book", "send me a booking link",
        "send me a link to pick", "send me a link to choose",
        "send me the available times", "send me a calendar invite to pick",
    }

    # A visitor asking to be handed off to a person. BusinessConfig has
    # an escalation_triggers field, but nothing in the codebase reads
    # it -- there is no real handoff mechanism, so this is exactly the
    # same category of unbacked claim as the other two, not a solved
    # problem with an unused config knob.
    HUMAN_HANDOFF_PHRASES = {
        "talk to a human", "talk to a real person", "talk to a person",
        "speak to a human", "speak to a real person", "speak to a person",
        "speak with a person", "speak with a human",
        "talk to someone else", "talk to somebody else",
        "connect me with someone", "connect me to a person",
        "connect me with a person", "connect me to someone",
        "get me a human", "put me through to", "transfer me to",
        "can i talk to someone on your team",
        "is there a real person",
    }

    _ALTERNATE_BOOKING_PATTERNS = _compile_phrases(ALTERNATE_BOOKING_MECHANISM_PHRASES)
    _OUT_OF_CHAT_PATTERNS = _compile_phrases(OUT_OF_CHAT_MESSAGE_PHRASES)
    _HUMAN_HANDOFF_PATTERNS = _compile_phrases(HUMAN_HANDOFF_PHRASES)

    @staticmethod
    def _matches(patterns: list[re.Pattern], text: str) -> bool:
        return any(pattern.search(text) for pattern in patterns)

    def detect(self, message: str) -> str | None:
        """
        Returns the matched UnbackedActionCategory, or None when the
        message doesn't ask for anything in an unbacked category.
        """
        lower = (message or "").lower()

        if self._matches(self._ALTERNATE_BOOKING_PATTERNS, lower):
            return UnbackedActionCategory.ALTERNATE_BOOKING_MECHANISM

        if self._matches(self._OUT_OF_CHAT_PATTERNS, lower):
            return UnbackedActionCategory.OUT_OF_CHAT_MESSAGE

        if self._matches(self._HUMAN_HANDOFF_PATTERNS, lower):
            return UnbackedActionCategory.HUMAN_HANDOFF

        return None
