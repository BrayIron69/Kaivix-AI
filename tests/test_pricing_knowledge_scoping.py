import re
import unittest
from pathlib import Path

from knowledge.knowledge_base import KnowledgeBase

# The only dollar figures Bray is allowed to have access to: the generic
# staff-cost comparison in pricing.md's policy section (explicitly approved
# to be spoken aloud, once a visitor has engaged with cost/ROI). Every other
# dollar figure (Kaivix's own setup fees, retainers, founding client rate)
# must be structurally absent from anything KnowledgeBase can retrieve.
_ALLOWED_DOLLAR_FIGURES = {"$1,500", "$3,000"}

_DOLLAR_PATTERN = re.compile(r"\$[\d,]*\d")

# The LLM sometimes paraphrases the approved comparison as an abbreviated
# range ("$1.5-3 K", "$1.5‑$3K") instead of the exact figures above.
# _DOLLAR_PATTERN can't match a decimal or a "K" magnitude suffix at all
# (it only matches digits/commas), so "$1.5-3 K" makes it find a bare
# "$1" -- not in _ALLOWED_DOLLAR_FIGURES, so it gets misreported as a
# leaked figure. Scoped tightly to the literal 1.5/3 values of this one
# approved comparison, not a general decimal-K pattern, so a genuinely
# different figure (e.g. "$2.5K", "$4-5 K") is never matched here and
# still reaches _DOLLAR_PATTERN as an unapproved figure. Covers common
# dash variants (hyphen, non-breaking hyphen, en/em dash) since LLM
# output favors non-ASCII punctuation.
_APPROVED_SHORTHAND_RANGE_PATTERN = re.compile(
    r"\$1\.5\s*[-‐‑‒–—]\s*\$?3(?:,000)?\s*[kK]\b"
)


def strip_approved_shorthand_range(text: str) -> str:
    """
    Remove any occurrence of the approved staff-cost comparison written
    as an abbreviated range, before scanning for dollar figures -- so a
    caller's _DOLLAR_PATTERN scan never sees the "$1" fragment inside
    "$1.5-3 K" and misreports it as an unapproved figure. Does not
    affect the exact "$1,500"/"$3,000" phrasing, which was already
    handled correctly by _ALLOWED_DOLLAR_FIGURES.
    """
    return _APPROVED_SHORTHAND_RANGE_PATTERN.sub("", text)


class TestPricingKnowledgeScoping(unittest.TestCase):
    def setUp(self):
        self.kb = KnowledgeBase()

    def test_no_unapproved_dollar_figures_in_loaded_documents(self):
        for name, content in self.kb.documents.items():
            found = _DOLLAR_PATTERN.findall(content)
            unapproved = [figure for figure in found if figure not in _ALLOWED_DOLLAR_FIGURES]
            self.assertEqual(
                unapproved,
                [],
                f"Document {name!r} contains dollar figures Bray should not "
                f"have access to: {unapproved}",
            )

    def test_internal_pricing_reference_not_loaded(self):
        self.assertNotIn("Internal_Pricing_Reference", self.kb.documents)

        for content in self.kb.documents.values():
            self.assertNotIn("997", content)
            self.assertNotIn("1,497", content)
            self.assertNotIn("2,497", content)
            self.assertNotIn("1,997", content)

    def test_internal_pricing_reference_file_exists_outside_knowledge(self):
        internal_ref = Path(__file__).resolve().parent.parent / "docs" / "Internal_Pricing_Reference.md"
        self.assertTrue(internal_ref.is_file())

        knowledge_dir = Path(__file__).resolve().parent.parent / "knowledge" / "kaivix"
        self.assertNotIn(knowledge_dir, internal_ref.parents)

        # Sanity: the real numbers do live here, just not anywhere
        # KnowledgeBase can reach.
        content = internal_ref.read_text(encoding="utf-8")
        self.assertIn("$997", content)


class TestApprovedShorthandRangeStripping(unittest.TestCase):
    """
    Guards strip_approved_shorthand_range(): must recognize the approved
    $1,500/$3,000 comparison in abbreviated form, and must NOT widen the
    check to let a genuinely different figure through unnoticed.
    """

    def _unapproved_after_stripping(self, text: str) -> list[str]:
        scrubbed = strip_approved_shorthand_range(text)
        found = _DOLLAR_PATTERN.findall(scrubbed)
        return [figure for figure in found if figure not in _ALLOWED_DOLLAR_FIGURES]

    def test_hyphen_shorthand_is_recognized(self):
        text = "a part-time employee costs $1.5-3 K per month"
        self.assertEqual(self._unapproved_after_stripping(text), [])

    def test_non_breaking_hyphen_shorthand_is_recognized(self):
        # The actual character observed from live LLM output (U+2011).
        text = "a part‑time staff member ($1.5‑3 K per month)"
        self.assertEqual(self._unapproved_after_stripping(text), [])

    def test_dollar_sign_before_both_numbers_is_recognized(self):
        text = "a part-time employee typically costs $1.5‑$3 K per month"
        self.assertEqual(self._unapproved_after_stripping(text), [])

    def test_em_dash_and_no_space_before_k_is_recognized(self):
        text = "costs roughly $1.5—$3K per month"
        self.assertEqual(self._unapproved_after_stripping(text), [])

    def test_exact_phrasing_is_still_unaffected(self):
        text = "a part-time employee costs $1,500-$3,000 per month"
        self.assertEqual(self._unapproved_after_stripping(text), [])

    def test_a_genuinely_different_shorthand_figure_still_flagged(self):
        """
        The safety boundary: a different range in the same shorthand
        style must NOT be swallowed by the new pattern.
        """
        text = "our premium plan runs $4.5-6 K per month"
        self.assertEqual(self._unapproved_after_stripping(text), ["$4"])

    def test_a_genuinely_different_plain_figure_still_flagged(self):
        text = "the setup fee is $2,497 for that package"
        self.assertEqual(self._unapproved_after_stripping(text), ["$2,497"])

    def test_only_half_the_approved_range_does_not_match(self):
        """
        Half of the shorthand pattern alone (e.g. a genuine, unrelated
        "$1.5K" mention with no paired "3") must not be silently
        stripped -- the pattern requires the full paired range.
        """
        text = "we saved about $1.5K last quarter"
        self.assertEqual(self._unapproved_after_stripping(text), ["$1"])


if __name__ == "__main__":
    unittest.main()
