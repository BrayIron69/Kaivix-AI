"""
Deterministic post-processing filter that removes em dashes from a
response, replacing each one with a comma or a sentence break.

ENGINE_RULES rule #14 (core_ai/prompt_builder.py) already asks the model
not to use em dashes -- but that's a prompt instruction, and the current
model does not reliably follow it. This module is the actual guarantee,
in the same spirit as core_ai/unbacked_action_detector.py's gate for
fabricated action claims: a plain string transform run on the model's
output, after generation and before it ever reaches a visitor, that
cannot be talked out of firing the way a prompt rule can.

Scope: only the literal em dash character (U+2014, "—"). En dashes,
hyphens, and other punctuation are untouched -- widening this to other
dash-like characters was not asked for and is not done here.
"""

from __future__ import annotations

import re

_EM_DASH = "—"

# Matches one em dash plus any whitespace immediately touching it on
# either side, so replacing a match never leaves a stray double space
# or a missing one -- "word — word", "word—word", and "word --word"
# (mixed spacing) all normalize the same way.
_EM_DASH_WITH_SPACING = re.compile(r"\s*" + _EM_DASH + r"\s*")


def strip_em_dashes(text: str) -> str:
    """
    Return `text` with every em dash removed, never raising and never
    leaving one behind.

    - No em dash present: `text` is returned unchanged.
    - Exactly one em dash: split into two sentences at that point (the
      text before becomes one sentence, the text after becomes the
      next, capitalized if it starts with a letter). This is the
      "splitting into a separate sentence" case.
    - Two or more em dashes: each one becomes a comma instead. Multiple
      dashes are far more often a parenthetical or a list-like aside
      than a series of independent sentence breaks, and replacing each
      with its own sentence split tends to produce choppy, disconnected
      fragments -- a comma keeps the result as one readable sentence.

    Not a grammar checker: a single-dash split can produce a sentence
    fragment when the text after the dash isn't a complete clause on
    its own (e.g. "the team is small — always hands-on" becomes "the
    team is small. Always hands-on."). That's a deliberate trade-off --
    the invariant this function guarantees is "no em dash reaches the
    visitor," not "every split is grammatically ideal."
    """
    if not text or _EM_DASH not in text:
        return text

    if text.count(_EM_DASH) == 1:
        return _split_into_sentence(text)

    return _EM_DASH_WITH_SPACING.sub(", ", text)


def _split_into_sentence(text: str) -> str:
    match = _EM_DASH_WITH_SPACING.search(text)
    before = text[: match.start()].rstrip()
    after = text[match.end() :].lstrip()

    if after and after[0].isalpha():
        after = after[0].upper() + after[1:]

    if not before:
        return after
    if not after:
        return before + "."

    return f"{before}. {after}"
