import re

"""
Detects two specific fabrications about scheduling, both observed in a
real test conversation:

  1. Stating specific available times that no calendar ever returned.
     The visitor asked to book a particular time; Bray "offered three
     alternative time slots" that were invented, because the calendar
     was disconnected at the time (the wipe-on-deploy bug fixed in
     9ec91fd) and the plan therefore carried no real availability.

  2. Claiming a booking succeeded when nothing was booked. Bray said
     "Fantastic, your demo is set", then immediately admitted it cannot
     book anything and handed over the generic Calendly link.

ENGINE_RULES rule 11 already forbids both, in as many words, and both
happened anyway. That is the same result this codebase has measured for
every other "never do X" prompt rule: ~2.7% invented prices despite rule
7 (core_ai/pricing_guard.py), rule 12's fabricated-action ban holding
about half the time (core_ai/unbacked_action_detector.py). So the same
answer applies -- Python owns the outcome.

Pure detection, no I/O and no policy: ConversationEngine decides what to
do with a positive, exactly as it does with core_ai/pricing_guard.py's
find_unapproved_figures.
"""

# A clock time: "2pm", "2 PM", "9:00 AM", "14:30".
_CLOCK_TIME_PATTERN = re.compile(
    r"\b(?:\d{1,2}:\d{2}\s*(?:am|pm)?|\d{1,2}\s*(?:am|pm))\b",
    re.IGNORECASE,
)

# What turns a bare clock time into an OFFER of a meeting slot. A clock
# time alone is not enough and must never be: "our AI answers at 3am
# while your team is asleep" is a correct, on-topic sales line, and this
# product's entire pitch is round-the-clock coverage. Requiring a day
# anchor, a list marker, or availability language is what separates
# "here are times you can book" from "we work nights".
_SLOT_OFFER_CONTEXT_PATTERN = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"tomorrow|today|this\s+(?:week|afternoon|morning)|next\s+week|"
    r"available|availability|free|open|slot|works\s+for\s+you|"
    r"does\s+that\s+work|how\s+about|option)\b",
    re.IGNORECASE,
)

# "1. " / "2)" at the start of a line -- the numbered-slot presentation
# PromptBuilder asks for when real availability exists.
_NUMBERED_LIST_PATTERN = re.compile(r"(?:^|\n)\s*\d\s*[.)]\s+", re.MULTILINE)

# Asserting a booking now exists. Deliberately excludes anything
# conditional or interrogative ("shall I book", "would you like me to
# schedule") -- offering to book is honest, claiming to have booked is
# not.
_BOOKING_CLAIM_PATTERNS = [
    re.compile(
        r"\b(?:you(?:'re| are)|we(?:'re| are))\s+(?:all\s+)?(?:set|booked|confirmed|"
        r"scheduled|locked\s+in)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\byour\s+(?:demo|call|meeting|appointment|slot|time)\s+(?:is|has\s+been)\s+"
        r"(?:set|booked|confirmed|scheduled|locked\s+in|on\s+the\s+calendar)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bi(?:'ve| have)\s+(?:just\s+)?(?:booked|scheduled|set\s+up|confirmed|"
        r"reserved|put\s+you\s+down|got\s+you\s+down|added\s+you)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:that(?:'s| is)|it(?:'s| is))\s+(?:now\s+)?(?:booked|confirmed|scheduled|"
        r"on\s+the\s+calendar)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:booking|appointment|demo)\s+(?:is\s+)?confirmed\b",
        re.IGNORECASE,
    ),
]


def states_specific_availability(response: str) -> bool:
    """
    True when `response` reads as an offer of specific meeting times.

    Requires a clock time AND slot-offer context (a day anchor,
    availability language, or a numbered list), so ordinary
    round-the-clock sales talk does not match. See
    _SLOT_OFFER_CONTEXT_PATTERN.
    """
    text = response or ""

    if not _CLOCK_TIME_PATTERN.search(text):
        return False

    return bool(
        _SLOT_OFFER_CONTEXT_PATTERN.search(text) or _NUMBERED_LIST_PATTERN.search(text)
    )


def claims_a_booking_happened(response: str) -> bool:
    """
    True when `response` asserts that a booking now exists.

    Offering to book, or asking which time to book, is honest and must
    not match -- only the assertion does.
    """
    text = response or ""
    return any(pattern.search(text) for pattern in _BOOKING_CLAIM_PATTERNS)
