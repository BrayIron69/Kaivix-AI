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


if __name__ == "__main__":
    unittest.main()
