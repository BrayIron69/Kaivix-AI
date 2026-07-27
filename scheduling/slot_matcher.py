import re
from typing import Optional

# Case-insensitive ordinal words, in 0-based-index order (i.e.
# _ORDINAL_WORDS[0] == "first" -> index 0). Only the ordinals that could
# plausibly apply to _MAX_RETURNED_SLOTS (3) worth of offered slots --
# there is never a 4th slot offered today, so no "fourth" etc.
_ORDINAL_WORDS = ["first", "second", "third"]

# A standalone digit used as a position selector -- not part of a larger
# number (so "10" doesn't accidentally match as "1"), and not part of a
# time-like token (so "2pm" / "2:00" -- the visitor echoing back a
# slot's own displayed time -- is never misread as "pick option 2").
_DIGIT_PATTERN = re.compile(
    r"(?<!\d)([1-9])(?!\d)(?!:)(?!\s?[ap]\.?m\.?\b)", re.IGNORECASE
)


def match_offered_slot(user_message: str, offered_slots: list[str]) -> Optional[int]:
    """
    Resolve a visitor's reply to one of the slots most recently offered
    to them, by 0-based index into `offered_slots`.

    Matches ONLY:
      - a standalone digit that is a valid 1-based position (e.g. "2" or
        "option 2" when there are at least 2 offered_slots), or
      - an ordinal word (first/second/third), case-insensitive.

    Deliberately does NOT attempt fuzzy date/time text matching (e.g.
    trying to match "Tuesday" or "2pm" against the slot text itself) --
    ambiguity must return None, never a guess, since a wrong match here
    means booking the wrong real calendar event. Returns None if
    `offered_slots` is empty, or nothing in `user_message` is a clear,
    unambiguous match.
    """
    if not offered_slots or not user_message:
        return None

    message = user_message.strip().lower()

    for index, word in enumerate(_ORDINAL_WORDS):
        if index >= len(offered_slots):
            break
        if re.search(rf"\b{word}\b", message):
            return index

    digit_match = _DIGIT_PATTERN.search(message)
    if digit_match:
        position = int(digit_match.group(1))
        if 1 <= position <= len(offered_slots):
            return position - 1

    return None
