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

        sections += [
            "",
            self.ENGINE_RULES.format(
                max_sentences=business_config.persona.response_style.max_sentences
            ),
        ]

        return "\n".join(sections)