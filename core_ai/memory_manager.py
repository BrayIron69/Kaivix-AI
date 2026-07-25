from __future__ import annotations

from core_ai.conversation_summary import ConversationSummary
from core_ai.lead_profile import LeadProfile
from core_ai.working_memory import WorkingMemory
from memory.long_term_memory import LongTermMemory
from utils.logger import Logger


class MemoryManager:
    """
    MemoryManager

    Thin coordinator for the three memory-adjacent subsystems that
    ConversationEngine previously orchestrated by hand: WorkingMemory,
    ConversationSummary, and LongTermMemory.

    This is a pure scheduling/orchestration layer (per the Kaivix AI
    Development Handoff §12, "Recommended Next Milestone: MemoryManager").
    It owns:
      - the per-conversation state dicts that used to live directly on
        ConversationEngine (_working_memories, _long_term_hydrated,
        _long_term_profiles)
      - *when* each subsystem fires (every turn for WorkingMemory, every
        N turns for ConversationSummary, once-per-conversation for
        LongTermMemory hydration, every-turn-once-known for LongTermMemory
        persistence)

    It owns none of their internal logic. Every method here is a direct,
    behavior-preserving extraction of what was previously a private method
    on ConversationEngine:

      MemoryManager method                  <- previously
      ------------------------------------------------------------------
      get_working_memory                    <- ConversationEngine._get_working_memory
      update_working_memory                 <- ConversationEngine._update_working_memory
      maybe_refresh_conversation_summary     <- ConversationEngine._maybe_refresh_conversation_summary
      hydrate_long_term_memory              <- ConversationEngine._hydrate_long_term_memory
      persist_long_term_memory              <- ConversationEngine._persist_long_term_memory
      get_long_term_profile                 <- ConversationEngine._get_long_term_profile

    All cadence rules, merge semantics, error-handling behavior, and log
    message text are preserved exactly. WorkingMemory.update() itself,
    ConversationSummary.build(), and LongTermMemory.hydrate()/remember()
    are untouched — this class only decides when to call them, matching
    the "no persistence/business logic inside the coordinator" rule
    already established for ConversationEngine.

    PlanningEngine continues to receive only a WorkingMemory instance
    (via ConversationEngine, unchanged). PromptBuilder continues to
    receive `working_memory` and `long_term_memory` as two separate
    parameters, exactly as before — this class does not bundle them
    into a combined object, so neither downstream consumer's call site
    needs to change.
    """

    _DEFAULT_SUMMARY_REFRESH_INTERVAL_TURNS = 5

    def __init__(
        self,
        conversation_summary_engine: ConversationSummary | None = None,
        long_term_memory: LongTermMemory | None = None,
        summary_refresh_interval_turns: int = _DEFAULT_SUMMARY_REFRESH_INTERVAL_TURNS,
        logger: Logger | None = None,
    ):
        self.conversation_summary_engine = conversation_summary_engine or ConversationSummary()
        self.long_term_memory = long_term_memory or LongTermMemory()
        self.logger = logger or Logger()

        self._summary_refresh_interval_turns = summary_refresh_interval_turns

        # Per-conversation WorkingMemory instances.
        self._working_memories: dict[str, WorkingMemory] = {}

        # Tracks which conversations have already attempted a long-term
        # memory hydration, so it only runs once per conversation.
        self._long_term_hydrated: set[str] = set()

        # Caches the *result* of hydration (if a matching record existed)
        # for reuse by prompt building on later turns in the same
        # conversation.
        self._long_term_profiles: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # WorkingMemory
    # ------------------------------------------------------------------

    def get_working_memory(self, conversation_id: str) -> WorkingMemory:
        """Return the active WorkingMemory for this conversation."""
        if conversation_id not in self._working_memories:
            self._working_memories[conversation_id] = WorkingMemory()
        return self._working_memories[conversation_id]

    def update_working_memory(
        self,
        conversation_id: str,
        lead: LeadProfile,
        qualification: dict,
        goal,
        history: list[dict],
    ) -> WorkingMemory:
        """
        Refresh this conversation's WorkingMemory for the current turn.

        Called once per turn, after qualification progress and the goal
        have already been computed. Errors are logged but never
        interrupt the conversation — a WorkingMemory refresh failure
        should degrade gracefully (stale conversational context) rather
        than break the turn.
        """
        working_memory = self.get_working_memory(conversation_id)

        try:
            working_memory.update(
                lead=lead,
                qualification=qualification,
                goal=goal,
                history=history,
            )
        except Exception as error:
            self.logger.error(
                f"[WorkingMemory] Failed to update working memory "
                f"(conversation_id={conversation_id}): {error}"
            )

        return working_memory

    # ------------------------------------------------------------------
    # ConversationSummary
    # ------------------------------------------------------------------

    def maybe_refresh_conversation_summary(
        self,
        conversation_id: str,
        lead: LeadProfile,
        working_memory: WorkingMemory,
        history: list[dict],
    ) -> None:
        """
        Refresh this conversation's ConversationSummary narrative every
        `summary_refresh_interval_turns` turns, using
        `working_memory.turn_count` (already incremented for this turn
        by update_working_memory() above) rather than every turn.

        The computed text is written onto `working_memory` via
        `set_conversation_summary()`, so PlanningEngine (which only
        reads WorkingMemory) and PromptBuilder pick it up automatically
        without any new parameter.

        Errors are logged but never interrupt the conversation — a
        failed refresh simply leaves the previous summary in place.
        """
        if working_memory.turn_count % self._summary_refresh_interval_turns != 0:
            return

        try:
            summary_text = self.conversation_summary_engine.build(
                lead=lead,
                working_memory=working_memory,
                history=history,
            )
            working_memory.set_conversation_summary(summary_text)
        except Exception as error:
            self.logger.error(
                f"[ConversationSummary] Failed to refresh summary "
                f"(conversation_id={conversation_id}): {error}"
            )

    # ------------------------------------------------------------------
    # LongTermMemory
    # ------------------------------------------------------------------

    def hydrate_long_term_memory(self, conversation_id: str, lead: LeadProfile) -> None:
        """
        Once per conversation, as soon as this contact's email is known,
        look up any long-term memory on record for them and merge it
        onto `lead` (only-fill-empty / only-add-new semantics — see
        LongTermMemory.apply_to_lead). Runs at most once per
        conversation; if no email is known yet, it is retried on the
        next turn instead of being skipped permanently.

        All persistence/lookup logic lives in LongTermMemory itself —
        this method only decides *when* to call it.
        """
        if conversation_id in self._long_term_hydrated:
            return

        email = getattr(lead, "email", "") or ""
        if not email:
            return

        try:
            profile = self.long_term_memory.hydrate(lead)
            if profile:
                self._long_term_profiles[conversation_id] = profile
        except Exception as error:
            self.logger.error(
                f"[LongTermMemory] Failed to hydrate lead "
                f"(conversation_id={conversation_id}): {error}"
            )
        finally:
            self._long_term_hydrated.add(conversation_id)

    def persist_long_term_memory(self, conversation_id: str, lead: LeadProfile) -> None:
        """
        Save durable fields from `lead` into long-term memory, once this
        contact's email is known. Errors are logged but never interrupt
        the conversation, matching every other persistence step in this
        pipeline.
        """
        if not lead.email or not lead.email.strip():
            return

        try:
            self.long_term_memory.remember(lead, conversation_id=conversation_id)
        except Exception as error:
            self.logger.error(
                f"[LongTermMemory] Failed to persist lead "
                f"(conversation_id={conversation_id}): {error}"
            )

    def get_long_term_profile(self, conversation_id: str) -> dict | None:
        """Return the long-term profile recalled for this conversation, if any."""
        return self._long_term_profiles.get(conversation_id)