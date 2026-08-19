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


def find_unapproved_figures(text: str) -> list[str]:
    """
    Every dollar figure in `text` that Bray is not allowed to say.

    Empty list means the text is clean. This is the one place the
    "allowed?" question is answered, so the production guard, the unit
    test that scans the knowledge base, and the eval's no_price_leak
    check can never disagree about it.
    """
    scrubbed = strip_approved_shorthand_range(text or "")
    return [
        figure
        for figure in DOLLAR_PATTERN.findall(scrubbed)
        if figure not in ALLOWED_DOLLAR_FIGURES
    ]


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
