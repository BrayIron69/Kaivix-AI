"""
Deterministic guard against Bray quoting a price it invented.

Why this exists
---------------
knowledge/kaivix/pricing.md's Pricing Conversation Policy is explicit:
"Bray must never invent a price and must never quote an exact dollar
figure to a visitor who hasn't been qualified yet." ENGINE_RULES rule #7
says the same thing to the model directly. Both are instructions the
model can decline, and a 150-run soak of the just_tell_me_the_price eval
scenario measured how often it does: 4 failures, ~2.7%, every one of
them a real fabricated price rather than a false positive. Samples:

    "a support bot might start at a few thousand dollars setup and
     $500-$800 per month"
    "usually between $5,000 and $15,000, and a monthly retainer of
     $500-$1,500"
    "the setup typically ranges from $5 k to $10 k and the monthly
     retainer from $500 to $1.5 k"

None of those numbers exist anywhere the model can read. Kaivix's real
figures live in docs/Internal_Pricing_Reference.md, which KnowledgeBase
structurally cannot reach (guarded by
tests/test_pricing_knowledge_scoping.py), so the model is not leaking
them -- it is making numbers up, and the invented ones are far from the
real ones. A visitor quoted "$5,000 to $15,000" for something that
actually costs under $2,500 has been given materially false information
by an agent speaking for the business.

This is the same shape as the fabricated-action problem (Decision #030),
and it gets the same answer: a soft prompt rule is not a guarantee, so
Python owns the outcome. The prompt rule stays as a first line of
defense -- a fabrication never generated is strictly better than one
caught afterwards -- but the guarantee no longer depends on it.

Where this runs
---------------
Post-generation, in ConversationEngine.process_message, alongside
strip_em_dashes. It cannot be a pre-LLM input gate like
UnbackedActionDetector: the offending content is in the model's OUTPUT,
and a visitor asking about price is a perfectly legitimate question that
must still be answered.

This module is the single definition of "which dollar figures are
allowed". tests/test_pricing_knowledge_scoping.py and
evals/run_conversation_evals.py import from here. Previously the
definition lived in that test file and the eval imported it from
tests/, which put production's rule inside the test suite; the direction
is now the right way round, with still exactly one copy.
"""

import re

# The only dollar figures Bray is allowed to say: the generic staff-cost
# comparison in pricing.md's policy section, approved to be spoken aloud
# once a visitor has engaged with cost/ROI. Every other dollar figure --
# Kaivix's own setup fees, retainers, founding client rate -- must be
# absent from anything KnowledgeBase can retrieve AND from anything Bray
# says.
ALLOWED_DOLLAR_FIGURES = {"$1,500", "$3,000"}

DOLLAR_PATTERN = re.compile(r"\$[\d,]*\d")

# The LLM sometimes paraphrases the approved comparison as an abbreviated
# range ("$1.5-3 K", "$1.5-$3K") instead of the exact figures above.
# DOLLAR_PATTERN can't match a decimal or a "K" magnitude suffix at all
# (it only matches digits/commas), so "$1.5-3 K" makes it find a bare
# "$1" -- not in ALLOWED_DOLLAR_FIGURES, so it would be misreported as a
# leaked figure. Scoped tightly to the literal 1.5/3 values of this one
# approved comparison, not a general decimal-K pattern, so a genuinely
# different figure (e.g. "$2.5K", "$4-5 K") is never matched here and
# still reaches DOLLAR_PATTERN as an unapproved figure. Covers common
# dash variants (hyphen, non-breaking hyphen, en/em dash) since LLM
# output favors non-ASCII punctuation.
APPROVED_SHORTHAND_RANGE_PATTERN = re.compile(
    r"\$1\.5\s*[-‐‑‒–—]\s*\$?3(?:,000)?\s*[kK]\b"
)


def strip_approved_shorthand_range(text: str) -> str:
    """
    Remove any occurrence of the approved staff-cost comparison written
    as an abbreviated range, before scanning for dollar figures -- so a
    DOLLAR_PATTERN scan never sees the "$1" fragment inside "$1.5-3 K"
    and misreports it as an unapproved figure. Does not affect the exact
    "$1,500"/"$3,000" phrasing, which ALLOWED_DOLLAR_FIGURES already
    handles.
    """
    return APPROVED_SHORTHAND_RANGE_PATTERN.sub("", text)


def find_unapproved_figures(text: str, visitor_stated=None) -> list[str]:
    """
    Every dollar figure in `text` that Bray is not allowed to say.

    Empty list means the text is clean. This is the one place the
    "allowed?" question is answered, so the production guard, the unit
    test that scans the knowledge base, and the eval's no_price_leak
    check can never disagree about it.

    `visitor_stated` is the set of money AMOUNTS (as numbers) the
    VISITOR themselves used in this conversation. Repeating a number
    back to the person who just said it is not inventing a price -- it
    is the most basic form of listening, and blocking it made Bray
    unable to acknowledge a stated budget. Measured, not theorised: a
    visitor saying "our budget is 20000 dollars" had the whole reply
    replaced by the deflection, twice in one test conversation, because
    Bray echoed their own number back.

    Compared by VALUE rather than spelling, which a live conversation
    forced: the visitor typed "15k", Bray repeated it as "$15,000", and
    an earlier exact-string version of this allowance missed it and
    replaced the reply anyway.

    This does NOT widen what Bray may claim about KAIVIX's pricing. The
    allowance is per-conversation and derived only from what the visitor
    actually typed, so it can never introduce a figure nobody mentioned,
    and rule 7 plus the knowledge base still govern quoting a real
    price. Defaults to nothing allowed, so every existing caller --
    including the knowledge-base scan, which has no conversation and
    must stay absolute -- is completely unaffected.
    """
    scrubbed = strip_approved_shorthand_range(text or "")
    stated_amounts = set(visitor_stated or ())

    unapproved = []
    for figure in DOLLAR_PATTERN.findall(scrubbed):
        if figure in ALLOWED_DOLLAR_FIGURES:
            continue
        # Compared by VALUE, not spelling: the visitor types "15k" and
        # the model repeats it as "$15,000".
        amount = amount_of(figure)
        if amount is not None and amount in stated_amounts:
            continue
        unapproved.append(figure)

    return unapproved


# A money amount as a person actually types one: "$15,000", "$15k",
# "15k", "20000 dollars", or a bare "15000".
#
# Comparing SPELLINGS was not enough, which a live conversation showed
# immediately: the visitor typed "15k", Bray repeated it back as
# "$15,000", and an exact-match allowance missed it and replaced the
# whole reply anyway. People state budgets in whatever form they like
# and the model normalises them, so the comparison has to be on VALUE.
_MONEY_PATTERN = re.compile(
    r"(?:\$\s*(?P<dollar>[\d,]*\d)(?P<dollar_suffix>\s*[km])?)"
    r"|(?:\b(?P<suffixed>[\d,]*\d)\s*(?P<suffix>[km])\b)"
    r"|(?:\b(?P<worded>[\d,]*\d)\s*(?:dollars|usd)\b)"
    r"|(?:\b(?P<bare>\d{4,})\b)",
    re.IGNORECASE,
)

_MULTIPLIERS = {"k": 1_000, "m": 1_000_000}


def _to_amount(digits: str, suffix: str | None) -> int | None:
    """"15,000" + "k" -> 15000000. None when there is no number at all."""
    cleaned = (digits or "").replace(",", "").strip()
    if not cleaned.isdigit():
        return None

    amount = int(cleaned)
    key = (suffix or "").strip().lower()
    return amount * _MULTIPLIERS.get(key, 1)


def amount_of(figure: str) -> int | None:
    """The numeric value of a `$...` figure, for comparison by value."""
    return _to_amount(re.sub(r"[^\d,]", "", figure or ""), None)


def amounts_stated_by(messages) -> set:
    """
    Money amounts the visitor has actually used, as numbers, gathered
    from their own turns.

    Takes the same {"role", "content"} history ConversationEngine
    already holds, and reads ONLY role="user" entries -- gathering from
    the assistant's turns too would let one invented figure launder
    itself into being permanently allowed for the rest of the
    conversation.

    A bare number needs four digits or more to count, so picking slot
    "2" never quietly authorises Bray to say "$2", while a real budget
    written plainly as "15000" still does.
    """
    stated = set()

    for message in messages or []:
        if (message or {}).get("role") != "user":
            continue

        for match in _MONEY_PATTERN.finditer(message.get("content") or ""):
            groups = match.groupdict()
            amount = (
                _to_amount(groups["dollar"], groups["dollar_suffix"])
                if groups["dollar"]
                else _to_amount(groups["suffixed"], groups["suffix"])
                if groups["suffixed"]
                else _to_amount(groups["worded"], None)
                if groups["worded"]
                else _to_amount(groups["bare"], None)
            )
            if amount is not None:
                stated.add(amount)

    return stated


def contains_unapproved_price(text: str) -> bool:
    """Whether `text` quotes any dollar figure Bray must not say."""
    return bool(find_unapproved_figures(text))


# Deterministic stand-in used when the model quotes an invented price.
#
# Replaces the WHOLE response rather than redacting the offending
# figures: a redaction leaves the surrounding sentence asserting that a
# specific price exists ("the setup typically ranges from ___ to ___"),
# which is still the same false claim with the numbers filed off. Python
# owning the entire response is the same stance
# ConversationEngine._maybe_decline_unbacked_action already takes.
#
# The wording follows pricing.md's Pricing Conversation Policy directly:
# give the shape rather than a number, say what the retainer covers, and
# offer a real discovery call. It also keeps the conversation moving by
# asking what they need automated, so the guard firing does not stall
# qualification.
PRICE_DEFLECTION_RESPONSE = (
    "Pricing depends on what you're automating and how complex the build "
    "is, so I don't want to throw out a number that turns out to be wrong. "
    "The shape is a one-time setup fee scoped to the build, plus a small "
    "monthly retainer covering hosting, monitoring, updates and support. "
    "What are you looking to automate -- support, lead qualification, "
    "voice, or something custom? Once I know that, we can get you a firm "
    "quote on a quick discovery call."
)
