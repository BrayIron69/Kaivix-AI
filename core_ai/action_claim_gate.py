"""
Deterministic pre-delivery gate for unbacked action claims.

ENGINE_RULES rule #12 (core_ai/prompt_builder.py) tells the model not to
claim it performed an action nothing confirms -- but that's a prompt
instruction, which the model can still ignore or drift from over time.
This module is the actual guarantee: a plain string/regex check run on
the LLM's response, in code, after generation and before the response
ever reaches a visitor. It cannot be talked out of firing the way a
probabilistic prompt rule can.

Scoped to the three action categories this codebase genuinely has no
mechanism for, confirmed by inspection -- there is no email-sending
tool, no document generator, no CRM signup/account-creation tool, and
no human-handoff/escalation tool wired into ConversationEngine
anywhere:

- EMAIL: claiming an email, document, or checklist was sent.
- ALTERNATE_BOOKING_MECHANISM: claiming a booking succeeded, failed, or
  exists through something other than the one real booking path this
  codebase has (GoogleCalendarProvider, gated on
  plan.booking_confirmation / plan.booking_failed -- see
  ConversationEngine._maybe_resolve_booking). Only these two plan
  fields can make a booking claim legitimate; unset, any booking-status
  language is unbacked by definition.
- HUMAN_HANDOFF: claiming a person was notified, looped in, or will
  reach out. Nothing in this codebase notifies or hands off to a human.

Regex-based rather than a substring list because "I sent you an email"
should still be caught in the middle of a longer sentence, and simple
inflections ("send"/"sent"/"sending") shouldn't each need their own
literal entry.
"""

from __future__ import annotations

import re
from typing import Optional

# Allows a filler word ("also", "just", "already") between a subject
# ("I've") and its verb ("notified") -- real sentences say "I've also
# notified our team," not just "I've notified our team."
_INFIX = r"(?:also\s+|just\s+|already\s+)?"

_EMAIL_ACTION_PATTERN = re.compile(
    r"\b(i(?:'ve| have| just)?\s+" + _INFIX + r"(?:sent|emailed|e-mailed)\b"
    r"|sent\s+(?:you|it)\s+(?:an?\s+)?(?:email|e-mail)\b"
    r"|(?:emailed|e-mailed)\s+you\b"
    r"|check\s+your\s+(?:inbox|email)\b"
    r"|(?:on\s+its\s+way|should\s+(?:be|arrive))\s+(?:to\s+your\s+inbox|in\s+your\s+inbox|shortly)\b)",
    re.IGNORECASE,
)

_ALTERNATE_BOOKING_MECHANISM_PATTERN = re.compile(
    r"\b(you'?re\s+(?:all\s+)?booked\b"
    r"|i(?:'ve| have)?\s+" + _INFIX + r"booked\s+you\b"
    r"|booking\s+confirmed\b"
    r"|(?:your\s+)?appointment\s+is\s+confirmed\b"
    r"|i(?:'ve| have)?\s+" + _INFIX + r"scheduled\s+you(?:r)?\b"
    r"|added\s+you\s+to\s+(?:the|our)\s+calendar\b"
    r"|i(?:'ve| have)?\s+" + _INFIX + r"(?:added|registered)\s+you\b)",
    re.IGNORECASE,
)

_HUMAN_HANDOFF_PATTERN = re.compile(
    r"\b(i(?:'ve| have)?\s+" + _INFIX + r"(?:forwarded|escalated|looped\s+in|notified)\b"
    r"|(?:someone|a\s+specialist|our\s+team)\s+will\s+(?:reach\s+out|contact\s+you|be\s+in\s+touch)\b"
    r"|i(?:'ll| will)\s+have\s+someone\s+contact\s+you\b)",
    re.IGNORECASE,
)

# Order matters only for which label is reported when a response somehow
# matches more than one category -- doesn't affect whether it's caught.
_GATED_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("email", _EMAIL_ACTION_PATTERN),
    ("alternate_booking_mechanism", _ALTERNATE_BOOKING_MECHANISM_PATTERN),
    ("human_handoff", _HUMAN_HANDOFF_PATTERN),
)


def find_unbacked_action_claim(response_text: str, plan=None) -> Optional[str]:
    """
    Returns the category name ("email", "alternate_booking_mechanism",
    or "human_handoff") of the first unbacked action claim found in
    `response_text`, or None if there isn't one.

    `plan` is the turn's ConversationPlan (or any object with the same
    attributes, e.g. in tests). Only alternate_booking_mechanism is
    plan-sensitive: a real booking confirmation/failure this turn
    (plan.booking_confirmation or plan.booking_failed set) makes
    booking-status language legitimate, so it's exempted. email and
    human_handoff have no such backing mechanism regardless of plan
    state -- there is no code path in this repo that sends an email or
    notifies a human, ever.
    """
    if not response_text:
        return None

    booking_is_backed = bool(
        getattr(plan, "booking_confirmation", "") or getattr(plan, "booking_failed", False)
    )

    for category, pattern in _GATED_PATTERNS:
        if category == "alternate_booking_mechanism" and booking_is_backed:
            continue
        if pattern.search(response_text):
            return category

    return None
