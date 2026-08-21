from typing import Optional

from core_ai.business_config import (
    BusinessConfig,
    BusinessConfigRepository,
    DEFAULT_BUSINESS_ID,
)

# Shared, process-lifetime repository for the default (Kaivix) BusinessConfig
# used by build() whenever a caller doesn't pass one explicitly. Reused
# across calls so the config is read from disk once, not every turn.
_default_business_config_repository = BusinessConfigRepository()


class PromptBuilder:
    """
    Builds the system prompt for the AI.

    Responsible for defining how Alex should behave,
    given the current stage, intent, goal, knowledge,
    and known customer state.
    """

    # Historical reference constant — the original hardcoded identity
    # block. No longer used by build() (which now reads
    # business_config.persona.identity_statement, a lossless extraction
    # of this exact text — see config/businesses/kaivix/persona.yaml),
    # kept for backward-compatible reference (e.g. tests/test_business_config.py's
    # equivalence check).
    AGENT_IDENTITY = """
You are Bray, a friendly and confident sales agent for Kaivix Labs.
You are NOT a bot. You are a real human sales rep having a genuine business conversation.

Kaivix Labs builds custom AI employees for US businesses — intelligent agents that handle
customer support, lead qualification, scheduling, and workflow automation 24/7 without
salaries, sick days, or turnover.

Your job is to:
1. Understand what the visitor's business needs
2. Qualify them as a potential client
3. Handle objections confidently without being pushy
4. Guide them toward booking a free 30-minute demo call

Calendly demo link: https://calendly.com/brayiron-kaivixlab/30min
""".strip()

    # Universal engine rules — apply to every business, not config-driven.
    # Rule 3 is the one business-tunable knob (response length), filled in
    # from business_config.persona.response_style.max_sentences at build time.
    ENGINE_RULES = """
RULES:
1. Sound human and conversational — never robotic or scripted
2. Ask only ONE question per message
3. Keep responses under {max_sentences} sentences
4. Answer their question first, then ask your question
5. Never repeat a question the visitor already answered
6. Never invent company information not in the knowledge base
7. If asked about pricing, follow the pricing-conversation guidance in the knowledge base; never state a number that isn't present in it
8. If they show buying signals, move toward booking a demo call
9. If they object, acknowledge it and reframe once — never fold immediately
10. Never be pushy — be confident and helpful
11. Never claim a booking succeeded, failed, or exists unless a dedicated section below explicitly confirms the booking or reports a booking system failure — if no such section is present this turn, do not state or imply any booking status; instead offer the Calendly link or ask a clarifying question
12. Never claim to have performed, sent, set up, created, confirmed, or completed any action — an email, a document, a checklist, an account, an integration, a follow-up, anything — unless a dedicated section of this prompt explicitly confirms it already happened. If no such section confirms it, say honestly that you can't do that from here or don't have a way to confirm it, and offer a real next step instead, such as the Calendly link. Never invent a plausible-sounding process, tool, or system to explain how something supposedly happened.
13. Directly answer what the visitor actually asked, using the specific facts, names, and numbers in the knowledge base rather than general statements. When a concrete answer is possible, give it instead of padding the response with vague reassurance language like "we'll take great care of you" or "you're in good hands."
14. Do not use em dashes in your responses. Use a comma or a separate sentence instead.
""".strip()

    def build(
        self,
        stage: str,
        intent: str,
        goal: str,
        knowledge: str,
        missing_fields=None,
        extracted_entities=None,
        plan=None,
        working_memory=None,
        long_term_memory=None,
        business_config: Optional[BusinessConfig] = None,
        channel: str = "chat",
    ) -> str:
        # `plan` (a ConversationPlan) carries the deterministic decisions
        # already made by PlanningEngine. `working_memory` carries the
        # conversation's rolling context (facts learned, questions asked,
        # current objective/objection/temperature), plus a periodically
        # refreshed `conversation_summary` narrative (produced by the
        # separate ConversationSummary engine and stored onto
        # working_memory by ConversationEngine). `long_term_memory` is an
        # optional dict recalled from a previous conversation with this
        # same contact (produced by the separate LongTermMemory
        # component). This method only formats those into prompt text —
        # it does not decide or compute anything itself.
        #
        # `channel` is "chat" (default, unchanged behaviour, matches
        # every existing caller and test) or "voice" -- explicit, passed
        # by ConversationEngine.process_message the same way business_id
        # already flows through the pipeline, never inferred from stage/
        # intent/goal. Currently the ONE thing it changes is the BOOKING
        # SYSTEM ERROR section below, which offers a raw URL for chat and
        # must never do that for voice (a phone caller cannot click a
        # link). See ConversationEngine._guard_against_spoken_url for the
        # deterministic backstop this instruction alone is not relied on
        # to be -- the same "prompt rule is the first line of defense,
        # not the guarantee" stance as pricing_guard.py.

        if missing_fields is None:
            missing_fields = []

        if extracted_entities is None:
            extracted_entities = {}

        if business_config is None:
            business_config = _default_business_config_repository.load(DEFAULT_BUSINESS_ID)

        # Filter out empty entities for cleaner context
        clean_entities = {
            k: v for k, v in extracted_entities.items()
            if v not in ("", None, [], {}, 0, 0.0, "Cold", "New",
                        "greeting", "unknown", False)
        }

        sections = [
            business_config.persona.identity_statement,
            "",
            "=" * 50,
            f"CURRENT STAGE: {stage.upper()}",
            f"DETECTED INTENT: {intent.upper()}",
            f"CURRENT GOAL: {goal.upper()}",
            "=" * 50,
        ]

        if clean_entities:
            sections += [
                "",
                "WHAT WE KNOW ABOUT THIS VISITOR:",
                str(clean_entities),
            ]

        if long_term_memory:
            ltm_previous = list(long_term_memory.get("previous_conversations") or [])
            ltm_pain_points = list(long_term_memory.get("pain_points") or [])
            ltm_objections = list(long_term_memory.get("objections") or [])
            ltm_buying_signals = list(long_term_memory.get("buying_signals") or [])
            ltm_notes = long_term_memory.get("important_notes") or ""

            if ltm_previous or ltm_pain_points or ltm_objections or ltm_buying_signals or ltm_notes:
                sections += [
                    "",
                    "LONG-TERM MEMORY (from previous conversations with this contact):",
                    f"Previous conversations on record: {len(ltm_previous)}",
                ]
                if ltm_pain_points:
                    sections.append("Previously mentioned pain points: " + ", ".join(ltm_pain_points))
                if ltm_objections:
                    sections.append("Previously raised objections: " + ", ".join(ltm_objections))
                if ltm_buying_signals:
                    sections.append("Previously observed buying signals: " + ", ".join(ltm_buying_signals))
                if ltm_notes:
                    sections.append(f"Notes: {ltm_notes}")

        if missing_fields:
            sections += [
                "",
                f"STILL NEED TO COLLECT: {', '.join(missing_fields)}",
                "Naturally work these into the conversation — one at a time.",
            ]

        if knowledge:
            sections += [
                "",
                "COMPANY KNOWLEDGE (use this to answer questions):",
                knowledge,
            ]

        if working_memory is not None:
            wm_summary = getattr(working_memory, "summary", "") or ""
            wm_facts = getattr(working_memory, "facts", None) or []
            wm_questions_asked = getattr(working_memory, "questions_asked", None) or []

            if wm_summary or wm_facts or wm_questions_asked:
                sections += ["", "WORKING MEMORY (this conversation so far):"]
                if wm_summary:
                    sections.append(wm_summary)
                if wm_facts:
                    sections.append("Facts learned: " + ", ".join(wm_facts))
                if wm_questions_asked:
                    sections.append(
                        "Already asked — do not repeat if it was answered: "
                        + " / ".join(wm_questions_asked[-3:])
                    )

            wm_conversation_summary = getattr(working_memory, "conversation_summary", "") or ""
            if wm_conversation_summary:
                sections += [
                    "",
                    "CONVERSATION SUMMARY:",
                    wm_conversation_summary,
                ]

        if plan is not None:
            plan_strategy = getattr(plan, "strategy", "") or ""
            plan_next_question = getattr(plan, "next_question", "") or ""
            plan_avoid_topics = getattr(plan, "avoid_topics", None) or []

            if plan_strategy or plan_next_question:
                sections += ["", "CONVERSATION PLAN FOR THIS TURN:"]
                if plan_strategy:
                    sections.append(f"Strategy: {plan_strategy}")
                if plan_next_question:
                    sections.append(f"Suggested next question focus: {plan_next_question}")

            if plan_avoid_topics:
                sections += [
                    "",
                    f"AVOID bringing up unprompted: {', '.join(plan_avoid_topics)}.",
                    "(Still answer directly if the visitor asks about it themselves.)",
                ]

            plan_available_slots = getattr(plan, "available_slots", None) or []
            if plan_available_slots:
                sections += [
                    "",
                    "REAL AVAILABLE TIMES (offer these instead of a vague booking ask):",
                    *[
                        f"{index}. {slot}"
                        for index, slot in enumerate(plan_available_slots, start=1)
                    ],
                    "Present these to the visitor as a numbered list, in this exact "
                    "order, and ask them to reply with the number of whichever time "
                    "works for them. This is the only question to ask in this "
                    "message — do not ask anything else alongside it.",
                ]

            plan_booking_confirmation = getattr(plan, "booking_confirmation", "") or ""
            if plan_booking_confirmation:
                sections += [
                    "",
                    "BOOKING CONFIRMED:",
                    f"Confirmed time: {plan_booking_confirmation}",
                    "Tell the visitor their booking is confirmed, in your own natural, "
                    "friendly words — the way a real person would say it, not a system "
                    "message. You must state the confirmed time correctly and exactly as "
                    "given above, but do not copy this label format or this instruction's "
                    "sentence structure into your reply. Mention that a calendar invite/"
                    "confirmation will be sent to their email.",
                ]

            plan_booking_failed = bool(getattr(plan, "booking_failed", False))
            if plan_booking_failed:
                if channel == "voice":
                    # A caller on a phone cannot see or click a link, and
                    # reading a URL aloud is not something anyone can act
                    # on. This is the first line of defense only -- an
                    # instruction the model can decline, same as any
                    # other ENGINE_RULES rule -- not the guarantee.
                    # ConversationEngine._guard_against_spoken_url is the
                    # deterministic backstop that holds regardless of
                    # what the model does with this instruction; see its
                    # docstring for why a prompt instruction alone is
                    # not treated as sufficient anywhere else in this
                    # codebase either (pricing_guard.py, em_dash_filter.py).
                    sections += [
                        "",
                        "BOOKING SYSTEM ERROR:",
                        "The calendar booking attempt just failed. Apologize briefly for "
                        "the technical issue, in your own natural words. This is a phone "
                        "call: the caller cannot see or click anything, so you must NEVER "
                        "say a web address, link, or URL out loud -- not this business's "
                        "booking link, not any other. Instead, offer to get them a real "
                        "booking link by email: if you already know their email address, "
                        "say you will get it sent over; if you do not, ask for the best "
                        "email address to send it to.",
                    ]
                else:
                    booking_link = business_config.persona.booking_link or ""
                    sections += [
                        "",
                        "BOOKING SYSTEM ERROR:",
                        "The calendar booking attempt just failed. Apologize briefly for the "
                        "technical issue, then offer this booking link as a fallback instead: "
                        f"{booking_link}",
                    ]

        sections += [
            "",
            self.ENGINE_RULES.format(
                max_sentences=business_config.persona.response_style.max_sentences
            ),
        ]

        return "\n".join(sections)