import unittest
from pathlib import Path

from knowledge.knowledge_base import KnowledgeBase

# The definition of "which dollar figures are allowed" now lives in
# production code (core_ai/pricing_guard.py), because a real
# post-generation guard enforces it on every response Bray sends -- not
# just this test and the eval. It used to live here, with
# evals/run_conversation_evals.py importing it out of tests/, which put
# a production rule inside the test suite.
#
# Re-exported under the original private names so this module's own
# tests, and anything else that imported them from here, keep working
# against the same single definition.
from core_ai.pricing_guard import (  # noqa: F401
    ALLOWED_DOLLAR_FIGURES as _ALLOWED_DOLLAR_FIGURES,
    APPROVED_SHORTHAND_RANGE_PATTERN as _APPROVED_SHORTHAND_RANGE_PATTERN,
    DOLLAR_PATTERN as _DOLLAR_PATTERN,
    strip_approved_shorthand_range,
)


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
