import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from knowledge.knowledge_base import KnowledgeBase

# The exact before-state set of *.md stems that lived directly in
# knowledge/ prior to this milestone (now moved to knowledge/kaivix/ via
# `git mv`, one file per stem, history preserved).
KAIVIX_DOCUMENT_STEMS = {
    "case_studies",
    "company",
    "competitors",
    "faq",
    "integrations",
    "objections",
    "pricing",
    "process",
    "services",
}


class TestKnowledgeBaseDefault(unittest.TestCase):
    """No-args construction must load exactly the same documents as
    before this milestone (now under knowledge/kaivix/), with identical
    get_relevant_context() behavior."""

    def test_default_loads_exact_prior_document_set(self):
        kb = KnowledgeBase()
        self.assertEqual(set(kb.documents.keys()), KAIVIX_DOCUMENT_STEMS)

    def test_get_relevant_context_matches_prior_behavior(self):
        # Baseline captured by running the same query directly against the
        # moved files, bypassing KnowledgeBase's namespace resolution, so
        # this doesn't just compare the method against itself.
        kaivix_dir = Path(__file__).resolve().parent.parent / "knowledge" / "kaivix"
        query = "pricing plans and cost"
        query_words = {w for w in __import__("re").findall(r"\w+", query.lower()) if len(w) > 2}

        scored = []
        for file in kaivix_dir.glob("*.md"):
            content = file.read_text(encoding="utf-8")
            content_words = set(__import__("re").findall(r"\w+", content.lower()))
            score = len(query_words.intersection(content_words))
            scored.append((score, file.stem, content))
        scored.sort(reverse=True, key=lambda item: item[0])
        expected = "\n\n".join(content for score, _, content in scored[:3] if score > 0)

        kb = KnowledgeBase()
        self.assertEqual(kb.get_relevant_context(query), expected)
        self.assertNotEqual(expected, "")


class TestKnowledgeBaseNamespaced(unittest.TestCase):
    """Proves the loaded namespace is actually driven by
    business_config.knowledge.namespace, not still hardcoded to kaivix."""

    def test_custom_namespace_loads_different_content(self):
        with tempfile.TemporaryDirectory() as tmp_namespace_dir:
            tmp_namespace_dir = Path(tmp_namespace_dir)
            (tmp_namespace_dir / "widgets.md").write_text(
                "Widgets are our flagship dummy product.", encoding="utf-8"
            )
            (tmp_namespace_dir / "gadgets.md").write_text(
                "Gadgets pair well with widgets.", encoding="utf-8"
            )

            # `Path(__file__).parent / namespace` discards the left side
            # when namespace is itself absolute (pathlib join semantics),
            # so an absolute temp-dir path works as a "namespace" here.
            business_config = SimpleNamespace(
                knowledge=SimpleNamespace(namespace=str(tmp_namespace_dir))
            )

            kb = KnowledgeBase(business_config=business_config)

            self.assertEqual(set(kb.documents.keys()), {"widgets", "gadgets"})
            self.assertNotEqual(set(kb.documents.keys()), KAIVIX_DOCUMENT_STEMS)
            self.assertIn("flagship dummy product", kb.documents["widgets"])


if __name__ == "__main__":
    unittest.main()
