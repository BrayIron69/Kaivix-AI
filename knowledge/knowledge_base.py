from pathlib import Path
from typing import Optional
import re

from core_ai.business_config import (
    BusinessConfig,
    BusinessConfigRepository,
    DEFAULT_BUSINESS_ID,
)

# Shared, process-lifetime repository for the default (Kaivix) BusinessConfig
# used whenever a caller doesn't pass one explicitly (same pattern as
# core_ai/prompt_builder.py and core_ai/qualification_engine.py).
_default_business_config_repository = BusinessConfigRepository()


class KnowledgeBase:
    """
    Loads and serves a business's knowledge, namespaced by
    business_config.knowledge.namespace (config/businesses/<id>/knowledge.yaml).

    Version 1:
    - Loads all markdown files from knowledge/<namespace>/.
    - Keeps them in memory.
    - Returns the most relevant document using simple keyword matching.

    Future versions can replace the search logic with embeddings/vector
    retrieval without changing the ConversationEngine.
    """

    def __init__(self, business_config: Optional[BusinessConfig] = None):
        if business_config is None:
            business_config = _default_business_config_repository.load(DEFAULT_BUSINESS_ID)

        self.business_config = business_config
        self.documents = {}
        self._load_documents()

    def _load_documents(self):
        knowledge_dir = Path(__file__).parent / self.business_config.knowledge.namespace

        for file in knowledge_dir.glob("*.md"):
            try:
                self.documents[file.stem] = file.read_text(
                    encoding="utf-8"
                )
            except Exception as e:
                print(f"Could not load {file.name}: {e}")

    def get_relevant_context(
        self,
        query: str,
        max_documents: int = 3,
    ) -> str:
        """
        Returns the most relevant knowledge for a query.

        This simple keyword search is temporary.
        Later it will be replaced with semantic retrieval.
        """

        if not self.documents:
            return ""

        query_words = {
            word
            for word in re.findall(
                r"\w+",
                query.lower(),
            )
            if len(word) > 2
        }

        scored_documents = []

        for name, content in self.documents.items():

            content_words = set(
                re.findall(
                    r"\w+",
                    content.lower(),
                )
            )

            score = len(
                query_words.intersection(content_words)
            )

            scored_documents.append(
                (
                    score,
                    name,
                    content,
                )
            )

        scored_documents.sort(
            reverse=True,
            key=lambda item: item[0],
        )

        relevant = [
            content
            for score, _, content in scored_documents[:max_documents]
            if score > 0
        ]

        if not relevant:
            return ""

        return "\n\n".join(relevant)