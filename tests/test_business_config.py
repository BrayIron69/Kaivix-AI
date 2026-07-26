import unittest

from core_ai.business_config import BusinessConfigRepository
from core_ai.prompt_builder import PromptBuilder


class TestBusinessConfigKaivix(unittest.TestCase):
    def test_kaivix_identity_statement_matches_agent_identity(self):
        repo = BusinessConfigRepository()
        config = repo.load("kaivix")

        self.assertEqual(
            config.persona.identity_statement.strip(),
            PromptBuilder.AGENT_IDENTITY.strip(),
        )


if __name__ == "__main__":
    unittest.main()
