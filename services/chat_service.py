from typing import Callable, Optional

from core_ai.business_config import DEFAULT_BUSINESS_ID
from core_ai.conversation_engine import ConversationEngine


class ChatService:
    """
    Service responsible for handling chat requests
    and delegating AI reasoning to the ConversationEngine.

    Holds one ConversationEngine per business_id, built on first use and
    reused afterwards. Previously this held exactly one engine, so a single
    running process could only ever serve one business.

    Nothing about isolation lives here. ConversationEngine already resolves
    its own BusinessConfig at construction, and every component below it
    (QualificationEngine, KnowledgeBase, CRM, LongTermMemory,
    ConversationMemory, calendar tokens) is already business_id-scoped --
    see docs/Decision_Log.md #011. This class only decides *which* engine a
    request reaches.
    """

    def __init__(
        self,
        engine_factory: Optional[Callable[..., ConversationEngine]] = None,
    ):
        """
        Parameters
        ----------
        engine_factory : callable, optional
            Builds an engine given business_id=... Defaults to
            ConversationEngine. Injectable so tests can supply doubles
            without constructing the real thing.
        """
        self._engines: dict[str, ConversationEngine] = {}
        self._engine_factory = engine_factory or ConversationEngine

    def get_engine(self, business_id: str = DEFAULT_BUSINESS_ID) -> ConversationEngine:
        """
        Return this business's engine, constructing it on first request.

        Lazy on purpose: a business nobody has messaged costs nothing, and
        loading every configured business's knowledge base at startup would
        make process boot scale with the customer list.

        This does move config-error detection from import time to first
        request for a given business -- which also means one business's
        broken config can no longer stop the process serving everyone else.
        """
        engine = self._engines.get(business_id)

        if engine is None:
            engine = self._engine_factory(business_id=business_id)
            self._engines[business_id] = engine

        return engine

    @property
    def engine(self) -> ConversationEngine:
        """
        The default business's engine.

        Kept because this attribute was the entire public surface of this
        class before the cache existed, and callers/tests reach for it. It
        resolves to exactly what `self.engine` used to be.
        """
        return self.get_engine(DEFAULT_BUSINESS_ID)

    @property
    def cached_business_ids(self) -> list[str]:
        """Which businesses have an engine built, for tests and debugging."""
        return sorted(self._engines)

    def chat(
        self,
        conversation_id: str,
        message: str,
        business_id: str = DEFAULT_BUSINESS_ID,
    ) -> str:
        """
        business_id defaults to DEFAULT_BUSINESS_ID, so the original
        two-argument call signature keeps working unchanged.
        """
        return self.get_engine(business_id).process_message(
            conversation_id=conversation_id,
            user_message=message,
        )
