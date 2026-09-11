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
        channel: str = "chat",
        visitor_id: str | None = None,
    ) -> str:
        """
        business_id defaults to DEFAULT_BUSINESS_ID, so the original
        two-argument call signature keeps working unchanged.

        channel defaults to "chat" for the same reason -- api/routers/
        chat.py never passes it, so the widget's traffic is byte-
        identical to before. api/routers/voice.py is the one caller that
        passes channel="voice", threaded straight through to
        ConversationEngine.process_message (see its docstring for what
        this actually changes).

        visitor_id, when the caller sends one, associates this
        conversation with the browser that started it, so the widget's
        Messages tab can list the visitor's own threads later. It is
        recorded here rather than inside ConversationEngine on purpose:
        the engine reasons about a conversation and has no concept of
        the browser behind it, and threading a visitor through it would
        mean touching all five of its memory write sites for something
        none of them use. This class is already the seam that decides
        which business a turn belongs to -- which visitor is the same
        kind of routing fact.

        It stays optional. The voice channel has no browser and sends
        nothing, older widget builds send nothing, and both keep working
        exactly as before -- they simply produce threads that no
        Messages tab lists.
        """
        engine = self.get_engine(business_id)

        if visitor_id:
            # Before the turn, so a conversation is listable even if the
            # engine raises partway through answering it -- the user's
            # message is already recorded by then.
            engine.memory.link_visitor(conversation_id, visitor_id)

        return engine.process_message(
            conversation_id=conversation_id,
            user_message=message,
            channel=channel,
        )

    def list_conversations(
        self,
        visitor_id: str,
        business_id: str = DEFAULT_BUSINESS_ID,
        limit: int | None = None,
    ) -> list[dict]:
        """
        This visitor's past threads for this business, newest first.

        Routed through the same per-business engine as chat() so the
        thread list is read from exactly the store that business's
        messages were written to.
        """
        return self.get_engine(business_id).memory.list_conversations(
            visitor_id, limit
        )

    def get_conversation(
        self,
        conversation_id: str,
        visitor_id: str,
        business_id: str = DEFAULT_BUSINESS_ID,
    ) -> list[dict] | None:
        """
        One thread's messages, oldest first, for reopening it in the
        widget -- but only for the visitor the thread belongs to.

        Returns None when this visitor does not own the conversation, or
        when nothing owns it, so the caller can answer identically in
        both cases and never reveal which conversation ids exist.

        visitor_id is required rather than optional deliberately. Making
        it optional would leave a route that returns a transcript given
        only a conversation_id, and those ids are 'session_' +
        Math.random() -- an attacker enumerating them would be reading
        strangers' conversations. The check lives here, in the one place
        both the list and detail routes pass through, rather than in the
        router where a future second caller could forget it.
        """
        memory = self.get_engine(business_id).memory

        if not visitor_id or memory.get_visitor_id(conversation_id) != visitor_id:
            return None

        return memory.get_conversation(conversation_id)
