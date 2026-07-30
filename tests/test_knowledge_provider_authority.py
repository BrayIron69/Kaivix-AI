"""
Which config field selects the knowledge backend.

`knowledge.source_type` (knowledge.yaml) and `providers.knowledge_provider`
(providers.yaml) both used to claim this decision, with nothing saying which
won -- flagged in Decision #022 and deliberately left unresolved. Decision
#025 makes `providers.knowledge_provider` authoritative and removes
`source_type`.

Neither field is read by anything yet (Decision #022 kept knowledge out of
the provider registry), so this is a declarative fix: the point of these
tests is that the ambiguity is gone, that a stale `source_type` cannot
quietly mean anything, and that Kaivix's knowledge loading is byte-for-byte
unchanged.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from core_ai.business_config import (
    CONFIG_ROOT,
    BusinessConfigRepository,
    KnowledgeConfig,
)
from knowledge.knowledge_base import KnowledgeBase

KAIVIX_CONFIG_DIR = CONFIG_ROOT / "kaivix"


class TestProvidersFieldIsAuthoritative(unittest.TestCase):
    def test_knowledge_provider_is_declared_in_providers_yaml(self):
        config = BusinessConfigRepository().load("kaivix")
        self.assertEqual(config.providers.knowledge_provider, "file")

    def test_knowledge_provider_sits_with_the_other_backend_choices(self):
        """
        The reason this field won: all four backend selections live in one
        file under one naming convention, and two of them already drive real
        registry lookups.
        """
        providers = BusinessConfigRepository().load("kaivix").providers

        for field in (
            "llm_provider",
            "crm_provider",
            "calendar_provider",
            "knowledge_provider",
        ):
            self.assertTrue(hasattr(providers, field))

    def test_providers_yaml_on_disk_declares_knowledge_provider(self):
        raw = yaml.safe_load((KAIVIX_CONFIG_DIR / "providers.yaml").read_text())
        self.assertEqual(raw["knowledge_provider"], "file")


class TestSourceTypeIsGone(unittest.TestCase):
    def test_knowledge_config_no_longer_declares_source_type(self):
        self.assertNotIn("source_type", KnowledgeConfig.model_fields)

    def test_kaivix_knowledge_yaml_no_longer_sets_source_type(self):
        """Guards against it being reintroduced and recreating the conflict."""
        raw = yaml.safe_load((KAIVIX_CONFIG_DIR / "knowledge.yaml").read_text())
        self.assertNotIn("source_type", raw)

    def test_a_stale_source_type_is_inert_not_an_error(self):
        """
        Removing the field must not break a config that still carries it --
        it becomes a no-op, not a load failure.
        """
        config = KnowledgeConfig(namespace="somewhere", source_type="s3")

        self.assertEqual(config.namespace, "somewhere")
        self.assertFalse(hasattr(config, "source_type"))

    def test_a_business_whose_knowledge_yaml_still_has_source_type_loads(self):
        """
        The same property through the real repository path, on a real config
        directory -- a copy of Kaivix's with `source_type` put back.
        """
        with tempfile.TemporaryDirectory() as tmp:
            config_root = Path(tmp)

            # The repository resolves missing optional sections against the
            # default business's own directory, so the temp root has to
            # contain one -- same layout as the real config root.
            shutil.copytree(KAIVIX_CONFIG_DIR, config_root / "kaivix")

            business_dir = config_root / "legacy-business"
            shutil.copytree(KAIVIX_CONFIG_DIR, business_dir)

            (business_dir / "knowledge.yaml").write_text(
                "namespace: kaivix\nsource_type: some_removed_backend\n",
                encoding="utf-8",
            )

            config = BusinessConfigRepository(config_root=config_root).load(
                "legacy-business"
            )

            self.assertEqual(config.knowledge.namespace, "kaivix")
            self.assertFalse(hasattr(config.knowledge, "source_type"))
            # And the authoritative field is unaffected by the stale one.
            self.assertEqual(config.providers.knowledge_provider, "file")


class TestZeroBehaviourChangeForKaivix(unittest.TestCase):
    """
    The claim that has to hold: this resolves a config ambiguity and changes
    nothing about what Kaivix actually serves.
    """

    def test_kaivix_namespace_is_unchanged(self):
        config = BusinessConfigRepository().load("kaivix")
        self.assertEqual(config.knowledge.namespace, "kaivix")

    def test_kaivix_knowledge_base_loads_the_same_documents_as_the_corpus(self):
        knowledge = KnowledgeBase()

        expected = {
            path.stem
            for path in (Path("knowledge") / "kaivix").glob("*.md")
        }

        self.assertEqual(set(knowledge.documents), expected)
        self.assertTrue(expected, "the kaivix corpus should not be empty")

    def test_kaivix_knowledge_retrieval_still_returns_content(self):
        knowledge = KnowledgeBase()
        self.assertTrue(knowledge.get_relevant_context("pricing and setup fee"))


if __name__ == "__main__":
    unittest.main()
