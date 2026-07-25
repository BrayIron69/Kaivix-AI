from __future__ import annotations


class ConversationSummary:
    """
    ConversationSummary

    Stateless, deterministic engine that produces a richer,
    multi-sentence narrative summary of a conversation so far.

    Restored per the Kaivix AI Development Handoff (v3), §1/§3/§7:
    this file was referenced by core_ai/conversation_engine.py
    (`from core_ai.conversation_summary import ConversationSummary`)
    but was missing from the uploaded repository, which left the
    app unable to import. Reconstructed here to match the handoff's
    documented contract exactly, with no new design decisions:

      - Deterministic and template-based. Never calls the LLM.
        (Handoff §8, "NEW" rule: an LLM-authored summary would be
        the first place in the codebase where LLM output becomes a
        durable, re-consumed artifact rather than a one-shot reply.)
      - Reads WorkingMemory (facts, objective, temperature,
        outstanding qualification items, current objection, buying
        signals) plus `lead` (name, company) and `history` (only for
        turn count) — nothing else.
      - Never reads ConversationMemory for anything other than turn
        count, and never reads LongTermMemory at all (handoff §7).
      - Writes nothing itself; `build()` only returns text. The
        caller (ConversationEngine) is responsible for storing it
        onto WorkingMemory via `working_memory.set_conversation_summary()`.
    """

    def build(self, *, lead, working_memory, history: list[dict] | None = None) -> str:
        """
        Produce a narrative summary of the conversation so far.

        `history` is accepted only to report a turn count in the
        narrative; the number of turns actually processed is already
        tracked more precisely by `working_memory.turn_count`, which
        this method prefers when available.
        """
        history = history or []

        name = getattr(lead, "name", "") or "The visitor"
        company = getattr(lead, "company", "") or ""

        turn_count = getattr(working_memory, "turn_count", None)
        if turn_count is None:
            turn_count = len(history)

        objective = getattr(working_memory, "objective", "") or ""
        temperature = getattr(working_memory, "temperature", "") or "Cold"
        facts = list(getattr(working_memory, "facts", None) or [])
        outstanding = list(
            getattr(working_memory, "outstanding_qualification_items", None) or []
        )
        current_objection = getattr(working_memory, "current_objection", "") or ""
        buying_signals = list(getattr(working_memory, "buying_signals", None) or [])

        sentences: list[str] = []

        # Opening — who this is, how far in, current temperature.
        opener = f"{name}"
        if company:
            opener += f" from {company}"
        opener += f" is {turn_count} turn(s) into the conversation and is currently rated {temperature}."
        sentences.append(opener)

        # What's been established so far.
        if facts:
            sentences.append("Known so far: " + "; ".join(facts) + ".")

        # What the conversation is currently working toward.
        if objective:
            sentences.append(f"The current objective is to {objective.replace('_', ' ')}.")

        # What's still outstanding.
        if outstanding:
            sentences.append(
                "Still need to collect: " + ", ".join(outstanding) + "."
            )
        else:
            sentences.append("Qualification is complete.")

        # Objections and buying signals, if any.
        if current_objection:
            sentences.append(f"Most recent objection raised: \"{current_objection}\".")

        if buying_signals:
            sentences.append(
                "Buying signals observed: " + ", ".join(buying_signals) + "."
            )

        return " ".join(sentences)