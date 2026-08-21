import re
from dataclasses import replace
from typing import Optional
from urllib.parse import urlparse

from core_ai.business_config import BusinessConfigRepository, DEFAULT_BUSINESS_ID
from core_ai.conversation_plan import ConversationPlan
from core_ai.lead_profile import LeadProfile
from knowledge.knowledge_base import KnowledgeBase
from utils.llm_provider import get_llm_provider
from memory.conversation_memory import ConversationMemory

from core_ai.decision_engine import DecisionEngine
from core_ai.em_dash_filter import strip_em_dashes
from core_ai.entity_extractor import EntityExtractor
from core_ai.goal_engine import GoalEngine
from core_ai.lead_intelligence_engine import LeadIntelligenceEngine
from core_ai.memory_manager import MemoryManager
from core_ai.planning_engine import PlanningEngine
from core_ai.pricing_guard import PRICE_DEFLECTION_RESPONSE, find_unapproved_figures
from crm.lead_conversations import LeadConversationLinks
from core_ai.prompt_builder import PromptBuilder
from core_ai.qualification_engine import QualificationEngine
from core_ai.stages import ConversationStage
from core_ai.unbacked_action_detector import UnbackedActionCategory, UnbackedActionDetector
from core_ai.working_memory import WorkingMemory
from scheduling.email_provider import EmailProvider
from scheduling.google_calendar_provider import GoogleCalendarProvider
from scheduling.slot_matcher import match_offered_slot
from services.lead_service import LeadService
from utils.logger import Logger, conversation_bodies_enabled, redact_free_text


class ConversationEngine:
    """
    ConversationEngine v2.3

    Central orchestration layer for the Kaivix AI Platform.
    It coordinates memory, lead state, knowledge retrieval,
    intent detection, qualification, prompt construction,
    CRM persistence, and LLM response generation.

    As of this milestone, all WorkingMemory / ConversationSummary /
    LongTermMemory scheduling has been extracted into a dedicated
    MemoryManager (see core_ai/memory_manager.py). This is a pure
    refactor: every cadence rule, merge semantic, error-handling
    behavior, and log message is unchanged — only *where* the
    scheduling logic and its per-conversation state dicts live has
    moved. ConversationEngine still decides *when* in the pipeline
    each memory call happens (the call sites below are in the exact
    same order as before); MemoryManager still contains none of their
    internal business logic.
    """

    # Intents that force a specific conversation stage, regardless of
    # qualification progress.
    _OBJECTION_HANDLING_INTENTS = {"objection", "support", "pricing"}
    _CLOSING_INTENTS = {"meeting_request", "buying_signal"}

    # Thresholds used by stage detection.
    _GREETING_HISTORY_LIMIT = 2
    _PRESENTATION_COMPLETION_THRESHOLD = 60
    _PRESENTATION_HISTORY_LIMIT = 8

    # How often (in turns) the richer ConversationSummary narrative is
    # refreshed. Unlike WorkingMemory.summary (refreshed every turn),
    # this is intentionally periodic. Configurable per-instance via the
    # constructor for callers that want a different cadence. Passed
    # straight through to MemoryManager, which owns the actual cadence
    # check.
    _SUMMARY_REFRESH_INTERVAL_TURNS = 5

    # Name in BusinessConfig.tools.enabled_tools that gates the calendar
    # scheduling feature. Until now enabled_tools was loaded and then
    # ignored: booking was gated only by whether a Google Calendar
    # happened to be OAuth-connected, so a business could not turn the
    # feature off without disconnecting the calendar entirely.
    _CALENDAR_BOOKING_TOOL = "calendar_booking"

    # Fixed, honest responses for each UnbackedActionCategory -- see
    # _maybe_decline_unbacked_action. Python owns this text completely;
    # the LLM never generates or rephrases it.
    #
    # Deliberately WITHOUT the trailing "here's my calendar: {link}"
    # clause each of these used to end with -- that ending is now built
    # per-channel in _maybe_decline_unbacked_action (the raw
    # booking_link for chat, _voice_booking_alternative's spoken-safe
    # text for voice), from the same shared prefix, so chat output stays
    # byte-identical while voice never states a URL. See
    # docs/Decision_Log.md's voice-integration entry for why a caller on
    # a phone cannot act on a link the way a chat visitor can.
    _UNBACKED_ACTION_TEMPLATES = {
        UnbackedActionCategory.OUT_OF_CHAT_MESSAGE: (
            "I don't have a way to send anything outside this chat -- no "
            "email, text, or file delivery from here. I'm happy to go "
            "through it with you right now, or you're welcome to grab a "
            "time on the calendar and we can cover it live"
        ),
        UnbackedActionCategory.ALTERNATE_BOOKING_MECHANISM: (
            "The only way I can actually book with you is right here in "
            "this chat -- I don't have a way to send booking links, "
            "times, or confirmations by email or text. If real times are "
            "available I'll list them right here as numbered options. In "
            "the meantime, here's my calendar directly"
        ),
        UnbackedActionCategory.HUMAN_HANDOFF: (
            "I don't have a way to transfer you to someone else from "
            "this chat right now. If you'd like to talk to a real person "
            "on the team, the fastest way is booking time directly"
        ),
    }

    # The one, deterministic fallback sentence for when NEITHER a real
    # booking link NOR a real email send is honestly offerable on a
    # voice call -- EmailProvider isn't connected at all. Reused by
    # _voice_booking_alternative and directly by
    # _handle_conversation_summary_email_request's voice failure branch
    # (which must not retry a send that just failed in the same turn).
    #
    # Deliberately not "I'll have someone call you back" or "I'll text
    # you the link": neither is backed by a real code path (no callback
    # queue exists, and no SMS provider exists -- OUT_OF_CHAT_MESSAGE
    # already treats "text me" as something Bray has no way to do). A
    # passive promise about a future human action with nothing in code
    # guaranteeing it is exactly the shape of claim
    # UnbackedActionDetector exists to prevent (see its docstring on the
    # live incident this whole gate responds to); "you're welcome to
    # call back" makes no promise at all, and is true regardless of any
    # backend state.
    _VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE = (
        "I'm not able to get that over to you electronically right now, "
        "but you're welcome to call back and we can go through "
        "everything you need live."
    )

    def __init__(
        self,
        summary_refresh_interval_turns: int = _SUMMARY_REFRESH_INTERVAL_TURNS,
        business_id: str = DEFAULT_BUSINESS_ID,
        business_config_repository: Optional[BusinessConfigRepository] = None,
    ):
        # Resolved once, at construction, into a cached BusinessConfig —
        # not threaded through process_message per-message. See
        # docs/Decision_Log.md #011: ChatService holds one long-lived
        # ConversationEngine instance and V1 is one deployment per
        # customer, so business_id cannot legitimately vary between
        # messages within a running process.
        business_config_repository = business_config_repository or BusinessConfigRepository()
        self.business_id = business_id
        self.business_config = business_config_repository.load(business_id)

        self.memory = ConversationMemory(business_id=self.business_id)
        self.knowledge = KnowledgeBase(business_config=self.business_config)

        # providers.yaml is now read rather than merely validated. Both
        # fields resolve through a registry, so adding a provider never
        # touches this file -- see utils/llm_provider.py and crm/registry.py.
        # An unrecognised name raises here, at construction, instead of
        # silently serving Groq/SQLite under a different name in config.
        self.llm = get_llm_provider(self.business_config.providers.llm_provider)
        self.logger = Logger()

        self.decision_engine = DecisionEngine()
        self.goal_engine = GoalEngine()
        self.entity_extractor = EntityExtractor()
        self.lead_intelligence_engine = LeadIntelligenceEngine()
        self.planning_engine = PlanningEngine(business_config=self.business_config)
        self.qualification_engine = QualificationEngine(business_config=self.business_config)
        self.unbacked_action_detector = UnbackedActionDetector()
        self.prompt_builder = PromptBuilder()
        self.lead_service = LeadService(
            crm_provider=self.business_config.providers.crm_provider
        )
        # Full lead-to-conversations history, alongside the single
        # latest conversation leads.conversation_id holds -- see
        # crm/lead_conversations.py.
        self.lead_conversation_links = LeadConversationLinks()
        self.calendar_provider = GoogleCalendarProvider()
        # Reuses the same Google connection calendar_provider does --
        # see scheduling/email_provider.py's docstring. Not gated by
        # _CALENDAR_BOOKING_TOOL: whether email-sending is usable is
        # entirely determined by EmailProvider.is_connected() (real
        # scope check) at the point of use, same as calendar_provider.
        self.email_provider = EmailProvider()

        # Coordinates WorkingMemory (every turn), ConversationSummary
        # (every `summary_refresh_interval_turns` turns), and
        # LongTermMemory (hydrate once per conversation, persist every
        # turn once email is known). See core_ai/memory_manager.py.
        self.memory_manager = MemoryManager(
            summary_refresh_interval_turns=summary_refresh_interval_turns,
            logger=self.logger,
        )

        # How many turns to wait between ConversationSummary refreshes.
        # Kept here too (in addition to living on memory_manager) since
        # it was previously a public-ish instance attribute; preserved
        # for backward compatibility with anything reading it directly.
        self._summary_refresh_interval_turns = summary_refresh_interval_turns

        # Persistent lead state per conversation.
        self._lead_profiles: dict[str, LeadProfile] = {}

        # Structured (start, end) datetime pairs behind the display
        # strings most recently offered to each conversation (see
        # _maybe_attach_availability), keyed by conversation_id. Kept
        # separately from WorkingMemory.offered_slots (which only ever
        # holds the display strings -- see its docstring) so
        # _maybe_resolve_booking can book the exact real time window that
        # was actually shown to the visitor, without re-parsing display
        # text back into a date -- inherently ambiguous once more than a
        # few days have passed (which Tuesday?).
        self._offered_slot_windows: dict[str, list[tuple]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_message(
        self, conversation_id: str, user_message: str, channel: str = "chat"
    ) -> str:
        """
        Main entry point for all incoming customer messages.

        Pipeline (unchanged from the previous milestone):
        1. Record the user's message and load history.
        2. Update the lead profile and sync it to the CRM.
        3. Classify intent, stage, and goal.
        4. Assess qualification progress once, then build a deterministic
           conversation plan from stage/intent/goal/lead/qualification.
        5. Gather knowledge context.
        6. Build the prompt and generate the assistant response.
        7. Record the response and log the outcome.

        `channel` is "chat" (default) or "voice" -- explicit, passed
        through by the caller (services/chat_service.py) the same way
        business_id already flows through, never inferred from the
        message content or anything else about this turn. It currently
        affects exactly one thing: what a response says instead of a
        raw booking-link URL when the normal booking flow can't be
        offered (a phone caller cannot click a link) -- see
        _maybe_decline_unbacked_action, PromptBuilder.build's BOOKING
        SYSTEM ERROR section, and _guard_against_spoken_url below.
        """

        history = self._record_user_message(conversation_id, user_message)
        lead = self._update_lead_profile(conversation_id, user_message)

        # Deterministic gate, checked before any classification or LLM
        # work happens: if the visitor is asking for something this
        # system has no real backing for (see
        # _maybe_decline_unbacked_action), Python owns the entire
        # response and the model never gets a turn. Placed right after
        # lead/CRM state is updated (so any info given alongside the
        # request is still captured) and before everything else, since
        # nothing downstream is relevant to a response the model never
        # generates.
        unbacked_action_response = self._maybe_decline_unbacked_action(
            conversation_id, user_message, lead, channel
        )
        if unbacked_action_response is not None:
            # Belt-and-braces, not the primary defense here: every
            # _UNBACKED_ACTION_TEMPLATES ending and
            # _handle_conversation_summary_email_request's branches are
            # already channel-correct at the source (see their own
            # docstrings). Routed through the same guard the generated
            # path below uses anyway, so "no voice response ever
            # contains a URL" is enforced in exactly one place, not
            # separately trusted at every call site that produces
            # Python-owned text.
            unbacked_action_response = self._guard_against_spoken_url(
                conversation_id, unbacked_action_response, channel, lead
            )
            self.memory.add_assistant_message(conversation_id, unbacked_action_response)
            self.logger.info(
                f"[UnbackedActionDetector] Deterministic decline used "
                f"(conversation_id={conversation_id}, business_id={self.business_id!r})"
            )
            return unbacked_action_response

        intent = self.decision_engine.detect_intent(user_message)

        # Computed once per turn and reused by stage detection, the
        # planner, and the prompt builder below — no duplicate
        # qualification calculation.
        qualification = self._assess_qualification(lead)

        stage = self._detect_stage(history, intent, qualification["progress"])
        goal = self.goal_engine.determine_goal(stage=stage, intent=intent, lead=lead)

        # Refreshed once per turn, after qualification/goal are known and
        # before planning, so PlanningEngine can consume it. Delegated to
        # MemoryManager; every value WorkingMemory stores is still copied
        # from something computed above — it recalculates nothing itself.
        working_memory = self.memory_manager.update_working_memory(
            conversation_id=conversation_id,
            lead=lead,
            qualification=qualification["progress"],
            goal=goal,
            history=history,
        )

        # Resolves a visitor's reply (e.g. "2", "the second one") into a
        # real calendar booking, when a previous turn offered real
        # available time slots (working_memory.offered_slots). Placed
        # right after working_memory is refreshed, independent of
        # intent/stage/goal -- it only needs working_memory, lead, and
        # this turn's raw user_message. Returns None when there is
        # nothing to resolve this turn (no offered slots, or no clear
        # match), in which case working_memory.offered_slots is left
        # untouched so a later turn can still match it.
        booking_result = self._maybe_resolve_booking(
            conversation_id, user_message, lead, working_memory
        )

        # Refreshed only every `_summary_refresh_interval_turns` turns
        # (not every turn like working_memory above). The result is
        # stored directly onto `working_memory` by MemoryManager, so
        # PlanningEngine and PromptBuilder pick it up automatically
        # without any new parameter — PlanningEngine continues to read
        # WorkingMemory only, and never touches ConversationSummary
        # directly.
        self.memory_manager.maybe_refresh_conversation_summary(
            conversation_id=conversation_id,
            lead=lead,
            working_memory=working_memory,
            history=history,
        )

        plan = self.planning_engine.plan(
            stage=stage,
            intent=intent,
            goal=goal,
            lead=lead,
            qualification=qualification["progress"],
            history=history,
            working_memory=working_memory,
        )

        if booking_result is not None:
            # A booking was just confirmed or failed this turn --
            # PlanningEngine itself never sets these fields (it performs
            # no I/O; see its docstring). Skip _maybe_attach_availability
            # below: a booking resolution and a brand-new availability
            # offer should never both fire in the same turn.
            plan = replace(
                plan,
                booking_confirmation=booking_result["confirmation"],
                booking_failed=booking_result["failed"],
            )
        else:
            # Read-only: attaches real calendar availability to the plan
            # when PlanningEngine has already decided to drive toward
            # booking and this business has a connected calendar.
            # PlanningEngine itself performs no I/O (see its docstring)
            # -- this lookup belongs here, one step after the plan is
            # produced, not inside PlanningEngine.
            plan = self._maybe_attach_availability(conversation_id, plan, working_memory)

        knowledge = self._gather_knowledge(conversation_id, user_message)

        long_term_profile = self.memory_manager.get_long_term_profile(conversation_id)

        system_prompt = self.prompt_builder.build(
            stage=stage.value,
            intent=intent.value,
            goal=goal.value,
            knowledge=knowledge,
            missing_fields=qualification["missing"],
            extracted_entities=lead.to_dict(),
            plan=plan,
            working_memory=working_memory,
            long_term_memory=long_term_profile,
            business_config=self.business_config,
            channel=channel,
        )

        messages = self._build_messages(system_prompt, history)
        response = self._generate_response(conversation_id, messages)
        # Deterministic backstop for ENGINE_RULES rule #14 (avoid em
        # dashes) -- a prompt instruction the current model does not
        # reliably follow. Applied here, before the response is stored
        # or returned, so neither the visitor nor conversation history
        # ever sees one. See core_ai/em_dash_filter.py.
        response = strip_em_dashes(response)

        # Deterministic backstop for ENGINE_RULES rule #7 / pricing.md's
        # "never invent a price". Same reasoning as the em-dash filter
        # above and as Decision #030's action gate: the prompt rule is an
        # instruction the model can decline, and a 150-run soak measured
        # it declining ~2.7% of the time by quoting figures that exist
        # nowhere in the knowledge base ("$5,000 and $15,000", "$500-$800
        # per month"). Applied before the response is stored or returned,
        # so neither the visitor nor the conversation history ever
        # contains an invented price. See core_ai/pricing_guard.py.
        response = self._guard_against_invented_price(conversation_id, response)

        # Deterministic backstop for the BOOKING SYSTEM ERROR prompt
        # section's channel-aware instruction (core_ai/prompt_builder.py)
        # -- same reasoning as the two guards immediately above: a
        # prompt instruction alone is not trusted as a guarantee
        # anywhere else in this pipeline, and there is no reason a
        # "never say a URL out loud" instruction would be more reliable
        # than "never invent a price" turned out to be. Applied on every
        # turn, not only when a booking just failed: a no-op when the
        # response is already clean (the overwhelming majority of
        # turns), and a real backstop against ANY generative source of a
        # spoken URL, not only the one prompt section this build's task
        # named -- including ENGINE_RULES rules #11/#12's own "offer the
        # Calendly link" fallback guidance and the raw link baked into
        # every prompt's context, neither of which needed to be touched
        # to be covered. See _guard_against_spoken_url's docstring.
        response = self._guard_against_spoken_url(conversation_id, response, channel, lead)

        self.memory.add_assistant_message(conversation_id, response)

        self._log_turn(
            conversation_id=conversation_id,
            stage=stage,
            intent=intent,
            goal=goal,
            qualification=qualification,
            working_memory=working_memory,
            long_term_memory=long_term_profile,
        )

        return response

    # ------------------------------------------------------------------
    # Lead state
    # ------------------------------------------------------------------

    def _get_lead(self, conversation_id: str) -> LeadProfile:
        """Return the active lead profile for this conversation."""
        if conversation_id not in self._lead_profiles:
            self._lead_profiles[conversation_id] = LeadProfile()
        return self._lead_profiles[conversation_id]

    def _get_working_memory(self, conversation_id: str) -> WorkingMemory:
        """
        Return the active WorkingMemory for this conversation.

        Delegates to MemoryManager, which now owns the per-conversation
        WorkingMemory dict. Kept as a method on ConversationEngine for
        backward compatibility with any existing caller (including the
        test harness used to verify this milestone).
        """
        return self.memory_manager.get_working_memory(conversation_id)

    def _update_lead_profile(self, conversation_id: str, user_message: str) -> LeadProfile:
        """
        Load the lead profile for this conversation, merge any newly
        extracted entities into it, hydrate it with any long-term
        memory on record for this contact, compute lead intelligence,
        and sync the result to the CRM and to long-term memory.
        """
        lead = self._get_lead(conversation_id)

        try:
            self.entity_extractor.extract(user_message, lead)
        except Exception as error:
            self.logger.error(
                f"[EntityExtractor] Failed to extract entities "
                f"(conversation_id={conversation_id}): {error}"
            )

        # Long-term memory hydration/persistence scheduling now lives on
        # MemoryManager; call sites and ordering relative to lead
        # intelligence / CRM sync below are unchanged.
        self.memory_manager.hydrate_long_term_memory(
            conversation_id, lead, business_id=self.business_id
        )

        self._apply_lead_intelligence(conversation_id, lead)

        self._sync_lead_to_crm(conversation_id, lead)

        self.memory_manager.persist_long_term_memory(
            conversation_id, lead, business_id=self.business_id
        )

        return lead

    def _apply_lead_intelligence(self, conversation_id: str, lead: LeadProfile) -> None:
        """
        Run deterministic lead-scoring analysis exactly once per turn and
        store the results directly on the CustomerState/LeadProfile object
        (temperature, confidence, score, score_reasons, recommended_action,
        summary). This is the single source of truth read afterward by
        GoalEngine, PromptBuilder, and CRM persistence — no other step
        recomputes it.
        """
        try:
            self.lead_intelligence_engine.apply(lead)
        except Exception as error:
            self.logger.error(
                f"[LeadIntelligenceEngine] Failed to analyze lead "
                f"(conversation_id={conversation_id}): {error}"
            )

    def _sync_lead_to_crm(self, conversation_id: str, lead: LeadProfile) -> None:
        """
        Save the lead to the CRM when we have enough information
        to identify it uniquely. CRM failures are logged but never
        interrupt the conversation.

        The conversation_id is recorded on the lead row so the admin
        dashboard can show the real transcript behind the extracted
        fields. It is attached to a plain dict copy rather than set on
        the LeadProfile itself: LeadProfile describes the *person*
        (CustomerState fields, hydrated from long-term memory across
        sessions), while the conversation is a property of this one
        session, and putting it on the profile would mean it flowed into
        long-term memory hydration too.
        """
        if not lead.email or not lead.email.strip():
            return

        payload = lead.to_dict()
        payload["conversation_id"] = conversation_id

        # Record this conversation in the lead's full history as well as
        # in leads.conversation_id (which only ever holds the latest).
        # Kept in its own try so a link failure cannot stop the lead
        # itself being saved -- the lead is the more important record,
        # and the link is recoverable on the next turn.
        try:
            self.lead_conversation_links.link(
                lead.email, conversation_id, business_id=self.business_id
            )
        except Exception as error:
            self.logger.error(
                f"[LeadConversationLinks] Failed to link conversation to lead "
                f"(conversation_id={conversation_id}): {error}"
            )

        try:
            self.lead_service.save(payload, business_id=self.business_id)
        except Exception as error:
            self.logger.error(
                f"[LeadService] Failed to save lead "
                f"(conversation_id={conversation_id}): {error}"
            )

    # ------------------------------------------------------------------
    # Invented pricing
    # ------------------------------------------------------------------

    def _guard_against_invented_price(self, conversation_id: str, response: str) -> str:
        """
        Replace any response quoting a dollar figure Bray is not allowed
        to say, and log loudly that it happened.

        Returns `response` unchanged when it is clean -- which is the
        overwhelmingly common case, so a normal pricing conversation
        (shape, not numbers, per pricing.md's policy) is untouched.

        The whole response is replaced rather than the figures redacted:
        removing the numbers leaves the sentence around them still
        asserting that a specific price exists, which is the same false
        claim with the digits filed off.

        Logged at error level with the offending figures because this
        firing means the model attempted to quote an invented price to a
        real visitor. It is caught, but it is not routine, and it is the
        only signal that would show the rate moving.
        """
        unapproved = find_unapproved_figures(response)
        if not unapproved:
            return response

        self.logger.error(
            f"[PricingGuard] Blocked an invented price before it reached the "
            f"visitor (conversation_id={conversation_id}, "
            f"business_id={self.business_id!r}): figures={unapproved}"
        )
        return PRICE_DEFLECTION_RESPONSE

    def _guard_against_spoken_url(
        self, conversation_id: str, response: str, channel: str, lead: LeadProfile
    ) -> str:
        """
        Voice-only deterministic backstop: replace a response containing
        a URL with a spoken-safe alternative, and log loudly that it
        happened.

        A no-op for chat (returns `response` unchanged, immediately) and
        a no-op for a clean voice response -- which is the overwhelming
        majority of turns. This exists for the same reason
        _guard_against_invented_price does: PromptBuilder's BOOKING
        SYSTEM ERROR section (and ENGINE_RULES rules #11/#12's own
        "offer the Calendly link" fallback guidance, present on every
        turn) are instructions the model can decline, not guarantees,
        and this pipeline has already measured -- today, on pricing --
        that "never do X" is not reliably followed just because it is
        asked nicely. There is no reason to trust "never say a URL out
        loud" any more than "never invent a price" turned out to
        deserve.

        Matches ANY http(s)/www URL, plus this specific business's own
        configured booking_link even without a scheme (a model that
        drops the instruction might also paraphrase the link without
        "https://") -- not only the one prompt section this guard was
        built for. It runs on every voice response regardless of why a
        URL appears in it, so it also covers ENGINE_RULES' own baked-in
        Calendly reference and fallback guidance without needing to
        rewrite ENGINE_RULES itself.

        The whole response is replaced, same reasoning as
        _guard_against_invented_price: redacting just the URL would
        leave the surrounding sentence still telling the caller to go
        look at a link they cannot see. Reuses
        _voice_booking_alternative -- the same honest, real-capability
        substitute the fixed decline templates use -- so a caller who
        hits this guard gets something actually useful, not a bare
        refusal.
        """
        if channel != "voice":
            return response

        if not self._response_contains_a_url(response):
            return response

        self.logger.error(
            f"[VoiceURLGuard] Blocked a spoken URL before it reached the "
            f"caller (conversation_id={conversation_id}, "
            f"business_id={self.business_id!r}): response={response!r}"
        )
        return self._voice_booking_alternative(conversation_id, lead)

    # Matches any well-formed http(s)/www URL, regardless of domain --
    # broader than just this business's own booking_link, since the
    # guarantee needs to hold even if a future response mentions some
    # other link entirely (a case study, a competitor's site quoted back,
    # anything).
    _URL_PATTERN = re.compile(r"(?:https?://|www\.)\S+", re.IGNORECASE)

    def _response_contains_a_url(self, response: str) -> bool:
        """
        True if `response` contains anything a caller could not act on
        by ear -- a scheme-having URL, or this business's own configured
        booking_link even quoted without a scheme (host name alone,
        e.g. "calendly.com/...", is not naturally speakable either).
        """
        if self._URL_PATTERN.search(response):
            return True

        booking_link = self.business_config.persona.booking_link or ""
        if not booking_link:
            return False

        if booking_link in response:
            return True

        host = urlparse(booking_link).netloc
        return bool(host) and host in response

    # ------------------------------------------------------------------
    # Unbacked action requests
    # ------------------------------------------------------------------

    def _voice_booking_alternative(self, conversation_id: str, lead: LeadProfile) -> str:
        """
        What to say instead of a raw booking-link URL, on a voice call.

        A visitor on a phone call cannot click a link, and reading one
        aloud is not something anyone can act on. The only honest
        alternative is EmailProvider -- a real, already-built capability
        (see scheduling/email_provider.py), not a new promise: if the
        caller's email is already known and EmailProvider is genuinely
        connected, the booking link is emailed right now and the caller
        is told truthfully that it was. Otherwise, the caller is asked
        for their email -- mirroring exactly the same "ask, never
        invent" pattern _handle_conversation_summary_email_request
        already uses when lead.email is unmet -- which is a real next
        step, not a guess about what will happen.

        Deliberately NOT "I'll text you the link": no SMS provider
        exists anywhere in this codebase --
        core_ai/unbacked_action_detector.py's own OUT_OF_CHAT_MESSAGE_
        PHRASES already treats "text me" as something Bray has no way to
        do, so claiming it here for voice would be the exact class of
        fabricated capability this whole gate exists to prevent.
        Deliberately NOT "I'll have someone call you back" either: no
        callback mechanism exists in code (no queue, no notification to
        the founder) -- a passive promise about a future human action
        with nothing guaranteeing it is exactly the shape of claim that
        produced the live incident UnbackedActionDetector's own
        docstring records. Reused as-is by _guard_against_spoken_url as
        the deterministic backstop's replacement text too, so there is
        exactly one definition of "the honest voice alternative", not
        one per call site.

        Used from three call sites: each of the three fixed decline
        templates below (via _maybe_decline_unbacked_action), and
        _guard_against_spoken_url when the model generates a URL despite
        being told not to. NOT used by
        _handle_conversation_summary_email_request's own failure branch,
        which is already mid-send-attempt when it would fire --
        re-entering here would silently retry the same send that just
        failed, in the same turn, to the same address. That branch uses
        _VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE directly instead.
        """
        if not self.email_provider.is_connected(self.business_id):
            return self._VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE

        if not lead.email:
            return (
                "What's the best email address? I'll get the booking "
                "link right over to you."
            )

        booking_link = self.business_config.persona.booking_link or ""
        business_name = self.business_config.identity.business_name

        result = self.email_provider.send_email(
            self.business_id,
            to=lead.email,
            subject=f"Book a time with {business_name}",
            body_text=f"Here's the link to grab a time that works: {booking_link}",
        )

        if result.get("success"):
            return (
                f"I've just emailed the booking link to {lead.email} so "
                f"you can grab a time that works."
            )

        self.logger.error(
            f"[VoiceBookingAlternative] Failed to email booking link "
            f"(conversation_id={conversation_id}, business_id={self.business_id!r}): "
            f"{result.get('error')}"
        )
        return (
            "What's the best email address? I'll get the booking link "
            "right over to you."
        )

    def _maybe_decline_unbacked_action(
        self, conversation_id: str, user_message: str, lead: LeadProfile, channel: str
    ) -> Optional[str]:
        """
        Deterministic gate for a visitor asking Bray to do something this
        system has no real code path for -- see
        core_ai/unbacked_action_detector.py's docstring for the incident
        this responds to and the full reasoning.

        Returns Python-owned response text when user_message matches one
        of UnbackedActionDetector's categories, or None when it doesn't
        (the normal pipeline runs as before, LLM included). Never
        raises: the detector itself is pure regex matching with no I/O,
        and the one category with real I/O
        (CONVERSATION_SUMMARY_EMAIL, delegated to
        _handle_conversation_summary_email_request) reports its own
        failures in-band rather than raising, the same contract
        EmailProvider.send_email and GoogleCalendarProvider.create_event
        already use for real, external, side-effecting calls.
        """
        category = self.unbacked_action_detector.detect(user_message)
        if category is None:
            return None

        if category == UnbackedActionCategory.CONVERSATION_SUMMARY_EMAIL:
            return self._handle_conversation_summary_email_request(
                conversation_id, lead, channel
            )

        prefix = self._UNBACKED_ACTION_TEMPLATES[category]
        if channel == "voice":
            return f"{prefix}. {self._voice_booking_alternative(conversation_id, lead)}"

        booking_link = self.business_config.persona.booking_link or ""
        return f"{prefix}: {booking_link}"

    def _handle_conversation_summary_email_request(
        self, conversation_id: str, lead: LeadProfile, channel: str
    ) -> str:
        """
        Handle a CONVERSATION_SUMMARY_EMAIL match: send a real email when
        it's actually deliverable, otherwise decline exactly as honestly
        as the other unbacked categories -- never claim a send that
        didn't happen.

        Three real, checkable conditions gate an actual send attempt,
        each with its own honest response when unmet:
          1. EmailProvider.is_connected() -- gmail.send actually granted
             for this business_id (see EmailProvider.is_connected's
             docstring on why a stored row alone isn't enough). Unmet:
             same fixed decline as OUT_OF_CHAT_MESSAGE -- from the
             visitor's side this is indistinguishable from "no way to
             send anything," which is still true until the founder
             reconnects.
          2. lead.email is known. Unmet: ask for it -- never invent an
             address, never silently drop the request.
          3. The real EmailProvider.send_email() call itself succeeds.
             Unmet: apologize and fall back to a real next step -- the
             booking link for chat, or (voice) the same honest
             electronic-delivery-unavailable line _voice_booking_
             alternative falls back to when EmailProvider isn't
             connected, WITHOUT re-attempting the send that just failed
             (see _voice_booking_alternative's docstring on why it is
             not reused for this specific branch).
        """
        if not self.email_provider.is_connected(self.business_id):
            if channel == "voice":
                return (
                    f"{self._UNBACKED_ACTION_TEMPLATES[UnbackedActionCategory.OUT_OF_CHAT_MESSAGE]}. "
                    f"{self._VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE}"
                )
            booking_link = self.business_config.persona.booking_link or ""
            return (
                f"{self._UNBACKED_ACTION_TEMPLATES[UnbackedActionCategory.OUT_OF_CHAT_MESSAGE]}: "
                f"{booking_link}"
            )

        if not lead.email:
            return (
                "I can send that over. What's the best email address "
                "to send the summary to?"
            )

        working_memory = self.memory_manager.get_working_memory(conversation_id)
        subject, body = self._compose_conversation_summary_email(lead, working_memory)

        result = self.email_provider.send_email(
            self.business_id, to=lead.email, subject=subject, body_text=body
        )

        if result.get("success"):
            return f"Done -- I've sent a summary of our conversation to {lead.email}."

        self.logger.error(
            f"[EmailProvider] Failed to send conversation summary email "
            f"(conversation_id={conversation_id}, business_id={self.business_id!r}): "
            f"{result.get('error')}"
        )

        if channel == "voice":
            return (
                "I tried to send that summary just now but hit a technical "
                f"issue on my end. {self._VOICE_ELECTRONIC_DELIVERY_UNAVAILABLE}"
            )

        booking_link = self.business_config.persona.booking_link or ""
        return (
            "I tried to send that summary just now but hit a technical "
            f"issue on my end. In the meantime, here's my calendar so we "
            f"don't lose the thread: {booking_link}"
        )

    def _compose_conversation_summary_email(
        self, lead: LeadProfile, working_memory: WorkingMemory
    ) -> tuple[str, str]:
        """
        Build (subject, body) from data this conversation has already
        genuinely collected -- WorkingMemory's summary/conversation_summary
        and LeadProfile's fields -- never invented content. Returns plain
        text; EmailProvider.send_email sends it as-is via MIMEText.
        """
        business_name = self.business_config.identity.business_name
        subject = f"Your conversation summary from {business_name}"

        lines = [f"Hi {lead.name}," if lead.name else "Hi,", ""]

        # working_memory.summary is deliberately excluded as a fallback
        # here -- it is the compact, internal state string built for the
        # LLM's own system prompt (see WorkingMemory's docstring), not
        # customer-facing text, and a real send confirmed it reads like
        # debug output ("Turn 2 | objective=qualification | ...") when
        # used as an email body. conversation_summary is the only field
        # meant for a human reader; when it hasn't been produced yet
        # (set_conversation_summary() runs periodically, not every turn)
        # the narrative paragraph is simply omitted -- the "What we
        # covered" bullets and booking link below still make the email
        # worth sending.
        narrative = working_memory.conversation_summary
        if narrative:
            lines.append(narrative)
            lines.append("")

        covered = []
        if lead.company:
            covered.append(f"Company: {lead.company}")
        if lead.pain_points:
            covered.append("Pain points: " + ", ".join(lead.pain_points))
        if lead.goals:
            covered.append("Goals: " + ", ".join(lead.goals))
        if lead.budget:
            covered.append(f"Budget: {lead.budget}")
        if lead.timeline:
            covered.append(f"Timeline: {lead.timeline}")
        if covered:
            lines.append("What we covered:")
            lines.extend(covered)
            lines.append("")

        booking_link = self.business_config.persona.booking_link or ""
        if booking_link:
            lines.append(f"Book a time to continue: {booking_link}")

        return subject, "\n".join(lines)

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _detect_stage(
        self,
        history: list[dict],
        intent,
        progress: dict,
    ) -> ConversationStage:
        """
        Stage detection based on conversation history,
        lead completeness, and intent.

        `progress` is the qualification progress dict already computed
        once for this turn (see process_message) — it is not
        recalculated here.
        """
        history_len = len(history)

        if history_len <= self._GREETING_HISTORY_LIMIT:
            return ConversationStage.GREETING

        if intent.value in self._OBJECTION_HANDLING_INTENTS:
            return ConversationStage.OBJECTION_HANDLING

        if intent.value in self._CLOSING_INTENTS:
            return ConversationStage.CLOSING

        if not progress["qualified"]:
            if progress["completion_percentage"] >= self._PRESENTATION_COMPLETION_THRESHOLD:
                return ConversationStage.PRESENTATION
            return ConversationStage.QUALIFICATION

        if history_len < self._PRESENTATION_HISTORY_LIMIT:
            return ConversationStage.PRESENTATION

        return ConversationStage.CLOSING

    # ------------------------------------------------------------------
    # Scheduling / Calendar
    # ------------------------------------------------------------------

    def _calendar_booking_enabled(self) -> bool:
        """
        Whether this business has the calendar_booking tool switched on
        in BusinessConfig.tools.enabled_tools.

        Fails closed: a config with no tools section, or an empty
        enabled_tools, means the feature is off. Read fresh from the
        cached BusinessConfig rather than snapshotted at construction,
        so it stays consistent with how every other config value is
        consumed.
        """
        tools = getattr(self.business_config, "tools", None)
        enabled_tools = getattr(tools, "enabled_tools", None) or []
        return self._CALENDAR_BOOKING_TOOL in enabled_tools

    def _maybe_attach_availability(
        self,
        conversation_id: str,
        plan: ConversationPlan,
        working_memory: WorkingMemory,
    ) -> ConversationPlan:
        """
        When PlanningEngine has decided to drive toward booking
        (plan.strategy == "drive_to_booking") and this business has a
        connected Google Calendar, attach real available time windows to
        the plan so PromptBuilder can have Bray offer them naturally
        instead of a vague "let's book a call." Read-only -- never
        creates or modifies an event.

        Also remembers what was offered: the display strings are written
        onto `working_memory` (set_offered_slots) and the underlying
        structured (start, end) datetimes are cached in
        self._offered_slot_windows, keyed by conversation_id, so a later
        turn's numeric reply can be resolved back into a real booking by
        _maybe_resolve_booking without ever re-parsing display text.

        Mirrors _sync_lead_to_crm's error-handling contract: calendar
        failures are logged and the original plan is returned unchanged,
        never interrupting the conversation. Returns a new plan via
        dataclasses.replace rather than mutating the one PlanningEngine
        returned.
        """
        try:
            if plan.strategy != "drive_to_booking":
                return plan

            # Config gate first -- cheapest check, and no reason to touch
            # the calendar at all for a business with booking switched off.
            if not self._calendar_booking_enabled():
                return plan

            if not self.calendar_provider.is_connected(self.business_id):
                # WARNING, not INFO: by this point _calendar_booking_enabled()
                # has already confirmed this business explicitly turned
                # calendar_booking on, and PlanningEngine has decided this
                # conversation should drive toward booking -- so a missing
                # connection here isn't "hasn't set up a calendar yet," it's
                # a real visitor mid-booking-flow getting no real slots,
                # invisibly, for a feature that's supposed to be live. This
                # was the unlogged root cause of the false-booking-
                # confirmation gap found during the live incident
                # investigation.
                self.logger.warning(
                    f"[GoogleCalendarProvider] Calendar not connected "
                    f"(business_id={self.business_id!r}, "
                    f"conversation_id={conversation_id}) -- calendar_booking "
                    f"is enabled but no availability can be offered this turn."
                )
                return plan

            windows = self.calendar_provider.get_free_busy_windows(self.business_id)
            slots = [self.calendar_provider.format_slot(start, end) for start, end in windows]

            self._offered_slot_windows[conversation_id] = windows
            working_memory.set_offered_slots(slots)

            return replace(plan, available_slots=slots)
        except Exception as error:
            self.logger.error(
                f"[GoogleCalendarProvider] Failed to fetch availability "
                f"(conversation_id={conversation_id}): {error}"
            )
            return plan

    def _maybe_resolve_booking(
        self,
        conversation_id: str,
        user_message: str,
        lead: LeadProfile,
        working_memory: WorkingMemory,
    ) -> Optional[dict]:
        """
        Attempt to resolve a visitor's reply into a real calendar
        booking, when a previous turn offered real available time slots
        (working_memory.offered_slots, set by _maybe_attach_availability
        above).

        Returns None when there is nothing to resolve this turn (no
        offered slots, or the message doesn't clearly match one of them)
        -- working_memory.offered_slots is left untouched in that case,
        so a later turn can still match it. Otherwise returns
        {"confirmation": str, "failed": bool} describing the outcome,
        for process_message to attach to this turn's ConversationPlan.

        This is the one place in the pipeline with a real, external,
        hard-to-undo side effect (creating an actual calendar event) --
        mirrors _sync_lead_to_crm's error-handling contract regardless:
        failures are logged and never raise past this method, degrading
        to "nothing resolved" rather than breaking the turn.
        """
        try:
            # Same gate as _maybe_attach_availability. Checked here too
            # rather than relying on "nothing was ever offered": slots
            # could have been offered before the tool was switched off,
            # and creating a real calendar event is exactly the side
            # effect a disabled tool must not produce.
            if not self._calendar_booking_enabled():
                return None

            offered_slots = list(working_memory.offered_slots or [])
            if not offered_slots:
                return None

            matched_index = match_offered_slot(user_message, offered_slots)
            if matched_index is None:
                return None

            matched_slot_text = offered_slots[matched_index]
            windows = self._offered_slot_windows.get(conversation_id) or []

            if matched_index >= len(windows):
                # Matched a display string but have no structured
                # start/end to actually book (e.g. stale/desynced cache)
                # -- fail safely rather than guess a time.
                self.logger.error(
                    f"[GoogleCalendarProvider] Matched offered slot "
                    f"{matched_index} but no cached start/end window "
                    f"available (conversation_id={conversation_id})"
                )
                working_memory.set_offered_slots([])
                self._offered_slot_windows.pop(conversation_id, None)
                return {"confirmation": "", "failed": True}

            start_time, end_time = windows[matched_index]

            result = self.calendar_provider.create_event(
                self.business_id,
                summary=f"Kaivix Demo Call - {lead.name or lead.email}",
                start_time=start_time,
                end_time=end_time,
                attendee_email=lead.email,
            )

            working_memory.set_offered_slots([])
            self._offered_slot_windows.pop(conversation_id, None)

            if result.get("success"):
                return {"confirmation": matched_slot_text, "failed": False}

            self.logger.error(
                f"[GoogleCalendarProvider] Booking attempt failed "
                f"(conversation_id={conversation_id}): {result.get('error')}"
            )
            return {"confirmation": "", "failed": True}

        except Exception as error:
            self.logger.error(
                f"[GoogleCalendarProvider] Failed to resolve booking "
                f"(conversation_id={conversation_id}): {error}"
            )
            return None

    # ------------------------------------------------------------------
    # Knowledge & qualification
    # ------------------------------------------------------------------

    def _gather_knowledge(self, conversation_id: str, user_message: str) -> str:
        """Retrieve relevant company knowledge for the current message."""
        try:
            return self.knowledge.get_relevant_context(user_message)
        except Exception as error:
            self.logger.error(
                f"[KnowledgeBase] Failed to retrieve context "
                f"(conversation_id={conversation_id}): {error}"
            )
            return ""

    def _assess_qualification(self, lead: LeadProfile) -> dict:
        """Return the lead's qualification progress, including missing fields."""
        progress = self.qualification_engine.qualification_progress(lead)
        return {
            "missing": progress["missing"],
            "progress": progress,
        }

    # ------------------------------------------------------------------
    # Prompt / LLM
    # ------------------------------------------------------------------

    def _build_messages(self, system_prompt: str, history: list[dict]) -> list[dict]:
        """
        Build a standard chat message list for the LLM.
        The system prompt defines behavior; history provides context.
        """
        return [{"role": "system", "content": system_prompt}, *history]

    def _generate_response(self, conversation_id: str, messages: list[dict]) -> str:
        """
        Call the LLM to generate the assistant's reply.

        Errors are logged with conversation context before being
        re-raised, since callers rely on this exception to signal
        a failed turn.
        """
        try:
            return self.llm.generate(messages)
        except Exception as error:
            self.logger.error(
                f"[LLM] Failed to generate response "
                f"(conversation_id={conversation_id}): {error}"
            )
            raise

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def _record_user_message(self, conversation_id: str, user_message: str) -> list[dict]:
        """Save the user's latest message and return the updated history."""
        self.memory.add_user_message(conversation_id, user_message)
        return self.memory.get_conversation(conversation_id)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log_turn(
        self,
        conversation_id: str,
        stage: ConversationStage,
        intent,
        goal,
        qualification: dict,
        working_memory: WorkingMemory = None,
        long_term_memory: dict = None,
    ) -> None:
        """
        Lightweight debugging output to help future tuning.

        Unlike `Logger.log_user`/`log_ai`, this runs on the FastAPI serving
        path -- every `/chat/{business_id}` request reaches it -- so it is the
        turn-logging that actually matters for a deployed business.

        The structured fields below are kept in full: a stage, an intent, a
        goal, a completion percentage and a list of missing field *names*
        describe the conversation without describing the person having it.
        That is the same line Decision #026 drew for `log_lead`.

        The two narrative fields are the problem. `working_memory.summary`
        embeds the visitor's most recent objection verbatim, and
        `conversation_summary` is a generated paragraph that opens with the
        lead's name and then lists their known facts -- which is how addresses
        reached `logs/app.log` from here. So the summary is swept, and the
        narrative is withheld by default on the same switch as conversation
        bodies, because a name in prose is not something a sweep can find.

        Both the printed block and the log line are built from the same
        redacted list. Stdout is not a safer destination than the log file --
        under a container runtime it is collected the same way.
        """
        progress = qualification["progress"]

        summary_lines = [
            f"Conversation ID: {conversation_id}",
            f"Stage: {stage.value}",
            f"Intent: {intent.value}",
            f"Goal: {goal.value}",
            f"Qualified: {progress['qualified']}",
            f"Completion: {progress['completion_percentage']}%",
            f"Missing fields: {qualification['missing']}",
        ]

        if working_memory is not None:
            summary_lines.append(
                f"Working memory: {redact_free_text(working_memory.summary)}"
            )
            if working_memory.conversation_summary:
                turn = working_memory.summary_last_updated_turn

                if conversation_bodies_enabled():
                    narrative = redact_free_text(working_memory.conversation_summary)
                else:
                    narrative = (
                        f"<{len(working_memory.conversation_summary)} chars withheld>"
                    )

                summary_lines.append(f"Conversation summary (turn {turn}): {narrative}")

        if long_term_memory:
            previous_count = len(long_term_memory.get("previous_conversations") or [])
            summary_lines.append(
                f"Long-term memory: returning contact, {previous_count} previous conversation(s) on record"
            )

        print("\n" + "=" * 72)
        for line in summary_lines:
            print(line)
        print("=" * 72 + "\n")

        self.logger.info(" | ".join(summary_lines))