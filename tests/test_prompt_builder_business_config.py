import unittest

from core_ai.business_config import BusinessConfigRepository
from core_ai.prompt_builder import PromptBuilder


class TestPromptBuilderBusinessConfig(unittest.TestCase):
    """
    Proves the config-driven persona/rules split produces byte-identical
    output to the old hardcoded AGENT_IDENTITY + RULES (literal 4), both
    when build() falls back to its internal default BusinessConfig and
    when one is passed explicitly.
    """

    STAGE = "qualifying"
    INTENT = "pricing"
    GOAL = "book_demo"
    KNOWLEDGE = "Kaivix pricing starts at $499/mo."

    def _expected_output(self) -> str:
        rules = PromptBuilder.ENGINE_RULES.format(max_sentences=4)
        sections = [
            PromptBuilder.AGENT_IDENTITY,
            "",
            "=" * 50,
            f"CURRENT STAGE: {self.STAGE.upper()}",
            f"DETECTED INTENT: {self.INTENT.upper()}",
            f"CURRENT GOAL: {self.GOAL.upper()}",
            "=" * 50,
            "",
            "COMPANY KNOWLEDGE (use this to answer questions):",
            self.KNOWLEDGE,
            "",
            rules,
        ]
        return "\n".join(sections)

    def test_default_business_config_matches_hardcoded_output(self):
        builder = PromptBuilder()
        output = builder.build(
            stage=self.STAGE,
            intent=self.INTENT,
            goal=self.GOAL,
            knowledge=self.KNOWLEDGE,
        )
        self.assertEqual(output, self._expected_output())

    def test_explicit_business_config_matches_hardcoded_output(self):
        repo = BusinessConfigRepository()
        business_config = repo.load("kaivix")

        builder = PromptBuilder()
        output = builder.build(
            stage=self.STAGE,
            intent=self.INTENT,
            goal=self.GOAL,
            knowledge=self.KNOWLEDGE,
            business_config=business_config,
        )
        self.assertEqual(output, self._expected_output())


if __name__ == "__main__":
    unittest.main()
