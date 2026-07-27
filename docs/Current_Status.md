# Kaivix Core Current Status

**Version:** 1.0
**Status:** Active Development
**Last Updated:** 2026-07-26

---

# Purpose

This document provides a real-time snapshot of the Kaivix Core project.

It answers four questions:

1. What has been completed?
2. What is currently being built?
3. What is planned next?
4. What issues or blockers currently exist?

This document should always reflect the current state of the project.

---

# Project Summary

**Project Name**
Kaivix Core

**Description**
Kaivix Core is a reusable AI Employee platform designed to allow businesses to deploy intelligent AI Employees through configuration rather than custom software development.

**Current Phase**
AI Employee Version 1 — Phase 2 (Production Hardening & Appointment Scheduling)

**Current Milestone**
Milestone 5 (Production Hardening & Appointment Scheduling) — complete. Next: a real end-to-end calendar connection + live booking verification, then continue Phase 2 (production testing, Docker deployment).

**Overall Progress**
🟩 BusinessConfig refactoring backlog complete (7/7). 🟩 Milestone 5 complete: the live pricing-leak bug is fixed, `ConversationMemory` now persists across restarts, a conversation-quality eval suite exists as a pre-deploy safety net, and the full Google Calendar scheduling feature (provider setup, real availability surfacing, real booking confirmation) is built and unit-tested end-to-end (93/93 tests passing). Not yet done: a real end-to-end booking test against a live calendar, and the remaining Phase 2 items (production testing, deployment).

---

# Completed Components

## Core Engine
- ✅ Conversation Engine — now resolves a `BusinessConfig` once at construction and threads it into every sub-component (backlog item #6, backlog complete 7/7)
- ✅ Intent Detection
- ✅ Goal Engine
- ✅ Planning Engine
- ✅ Prompt Builder — now config-driven (persona identity + response length read from BusinessConfig, universal rules stay in engine code)
- ✅ Entity Extraction

## Memory
- ✅ Memory Manager
- ✅ Working Memory — now also tracks `offered_slots` (real calendar times most recently offered to a visitor), same explicit-setter pattern as `conversation_summary`
- ✅ Conversation Memory — now persisted to SQLite (`memory/conversation_memory.db`), tenant-scoped from day one; survives a process restart (previously an in-memory `defaultdict`)
- ✅ Conversation Summary
- ✅ Long-Term Memory — now tenant-scoped: composite `(business_id, email)` key plus a real `business_id` column
- ✅ Customer State

## Knowledge
- ✅ Knowledge Base — now tenant-namespaced (`knowledge/<namespace>/*.md`, scoped by BusinessConfig)

## Lead Qualification
- ✅ Qualification Engine — required fields now schema-driven from BusinessConfig, no longer hardcoded

## CRM
- ✅ SQLite CRM — now tenant-scoped: `business_id` column, composite `UNIQUE(business_id, email)` constraint (previously unique on email alone, a real cross-tenant correctness bug)
- ✅ Lead Storage

## BusinessConfig
- ✅ BusinessConfig spec finalized (`docs/Business_Config.md`)
- ✅ YAML file structure: one directory per business (`config/businesses/<id>/`), split across 8 files (identity, persona, qualification, knowledge, tools, channels, guardrails, providers)
- ✅ Pydantic validation models + `BusinessConfigRepository` (`core_ai/business_config.py`)
- ✅ Kaivix's own config populated, verified byte-identical to the previously hardcoded values it replaced
- ✅ `DEFAULT_BUSINESS_ID = "kaivix"` seam adopted consistently across every refactored component

## Conversation-Quality Eval Suite (new since last status update)
- ✅ `evals/run_conversation_evals.py` — standalone, manually-run pre-deploy tool (deliberately not part of `python -m unittest discover -s tests`), runs scripted adversarial conversations against the real Groq LLM and checks for known-bad patterns (price leaks, bot admissions, crashes)

## Google Calendar Integration (new since last status update)
- ✅ Provider interface + tenant-scoped OAuth token storage (`scheduling/base_calendar_provider.py`, `scheduling/google_calendar_provider.py`, `scheduling/calendar_token_store.py`), one connection per business, shared app-level OAuth credentials
- ✅ FastAPI OAuth router (`api/routers/calendar_oauth.py`), OAuth setup itself verified with a real browser consent flow
- ✅ Real availability surfacing — `ConversationPlan.available_slots`, a read-only free/busy lookup triggered by PlanningEngine's existing `drive_to_booking` signal, surfaced in Bray's prompt
- ✅ Real booking confirmation — numbered-slot matching (`scheduling/slot_matcher.py`, strict digit/ordinal only, never fuzzy) and real calendar event creation, with a Calendly-link fallback on no-match or API failure
- ⬜ Real end-to-end booking test against a live calendar not yet performed (see Known Issues)

## Backend
- ✅ FastAPI API
- ✅ Repository Structure

## Infrastructure
- ✅ Git Repository
- ✅ GitHub Integration
- ✅ Environment Configuration

---

# Currently In Progress

**Current Focus**
Milestone 5 (Production Hardening & Appointment Scheduling — docs/Milestone_Log.md) is complete: the live pricing-leak bug is fixed, `ConversationMemory` persists across restarts, a conversation-quality eval suite exists as a pre-deploy safety net, and the full Google Calendar scheduling feature is built and unit-tested end-to-end. Immediate focus: a real end-to-end calendar connection and live booking verification, before this feature reaches real site visitors. After that: continue Phase 2 (production testing, Docker deployment), or address the newly logged `BusinessConfig.tools.enabled_tools` gap.

**Current Tasks**
- Real end-to-end calendar connection + live booking verification (`/oauth/google/connect`, a real conversation through to a real booked event, confirm and clean up)
- Continue Phase 2: production testing, then Docker deployment
- Address `BusinessConfig.tools.enabled_tools` gap (gate booking by config, not only by OAuth connection status)

---

# Next Milestones

## Milestone: BusinessConfig Refactoring Backlog (complete)
**Status:** 7 of 7 items complete
**Priority:** High

Items:
1. ✅ LongTermMemory composite key fix (correctness bug)
2. ✅ PromptBuilder config-driven split
3. ✅ QualificationEngine schema-driven fields
4. ✅ KnowledgeBase tenant-namespaced
5. ✅ CRM + LongTermMemory schema (`business_id` column, composite uniqueness)
6. ✅ ConversationEngine wiring
7. ✅ Dead-file cleanup (turned out to be a no-op — target files didn't exist)

## Milestone: Appointment Scheduling
**Status:** Built and unit-tested (Milestone 5) — real availability surfacing + numbered-slot booking confirmation
**Priority:** High

## Milestone: Google Calendar Integration
**Status:** Built and unit-tested (Milestone 5) — provider, tenant-scoped OAuth token storage, OAuth router; real end-to-end live-calendar verification still pending
**Priority:** High

## Milestone: Production Testing
**Status:** Not Started
**Priority:** High

## Milestone: AI Employee V1 Release
**Status:** Planned
**Priority:** Critical

## Milestone: Cold Outreach
**Status:** Planned
**Priority:** Critical

---

# Known Issues

## Issue: PlanningEngine field-hint duplication
**Status:** Open, flagged not fixed
**Owner:** Planning Engine
**Priority:** Low

`PlanningEngine._FIELD_QUESTIONS` hardcodes the same field-hint text now living in each business's `qualification.yaml` (`prompt_hint` per field). These are two independently maintained copies of the same content today. Harmless while only one business exists; will drift once a second business has a different qualification schema. Deliberately deferred rather than fixed opportunistically — needs its own scoped milestone, likely folded into or immediately after item #6.

## Issue: CRM `delete_lead` not yet business_id-scoped
**Status:** Open, flagged not fixed
**Owner:** CRM
**Priority:** Low

Backlog item #5 scoped `save_lead`, `get_lead_by_email`, `get_all_leads`, and `update_lead` to `business_id`, but `delete_lead` was explicitly left out of scope. Deleting by email alone could theoretically affect the wrong tenant's record once a second business exists. No impact today (single-business deployment).

## Issue: BusinessConfig.tools.enabled_tools unused — calendar booking gated only by OAuth connection status
**Status:** Open, flagged not fixed
**Owner:** BusinessConfig / Scheduling
**Priority:** Low

`GoogleCalendarProvider.is_connected(business_id)` is the only gate on whether availability/booking is offered — `BusinessConfig.tools.enabled_tools` exists in the schema but nothing reads it to decide whether calendar booking should be available for a given business at all. No impact today (Kaivix is the only business and has calendar booking enabled by design); will matter once a business without calendar access exists.

## Issue: Real end-to-end booking test against the live calendar not yet performed
**Status:** Open, flagged not fixed
**Owner:** Scheduling
**Priority:** High — recommended before real site visitors reach this feature

Every calendar/booking behavior is proven with mocked unit tests (Google API and LLM calls fully mocked, 93/93 passing); the OAuth setup itself was separately verified with a real browser consent flow (confirmed real calendars listed). A full, deliberate end-to-end run — connect a real calendar via `/oauth/google/connect`, complete a real conversation through to a real booked event on `brayiron@kaivixlab.com`'s calendar, confirm and clean up — has not yet been performed.

---

# Current Technical Debt

No significant technical debt beyond the four Known Issues above.

---

# Active Branch

Main

---

# Current Technology Stack

**Backend**
- Python
- FastAPI

**Database**
- SQLite (two separate databases: `crm/leads.db`, `memory/long_term_memory.db` — intentionally not merged)

**Version Control**
- Git
- GitHub

**Deployment**
- Frontend: Vercel
- Backend: To Be Determined

**LLM**
- Groq

**Future**
- Provider Abstraction (interface exists in `providers.yaml`/`BusinessConfig`, not yet wired to actual provider switching)

---

# Project Goals

**Immediate Goal**
Perform a real end-to-end calendar connection and live booking verification, then finish Phase 2 of AI Employee Version 1 (Production Testing, Docker Deployment).

**Short-Term Goal**
Begin customer outreach and secure the first paying client.

**Medium-Term Goal**
Convert Kaivix Core into a configurable AI Employee platform. (BusinessConfig refactoring backlog complete — 7 of 7 items.)

**Long-Term Goal**
Develop Kaivix into a multi-tenant enterprise AI platform, growing toward a full software-house-scale operation.

---

# Definition of AI Employee V1

Version 1 is considered complete when the following are operational:

- Natural conversations
- Memory
- Knowledge retrieval
- Lead qualification
- CRM integration
- Business configuration — backlog complete (7/7); Decision #014 (persona-fallback policy) resolved — `persona.yaml` required per business
- Appointment scheduling — built and unit-tested (Milestone 5); live end-to-end verification pending
- Google Calendar integration — built and unit-tested (Milestone 5); live end-to-end verification pending
- Production testing
- Stable deployment

Only after these requirements are satisfied should Version 1 be considered complete.

---

# Recent Progress

**2026-07-25 to 2026-07-26 — BusinessConfig Refactoring Backlog**

- Backlog item #7 (dead-file cleanup): confirmed no-op, target files did not exist.
- Backlog item #1: `LongTermMemory` fixed from an email-only key to a composite `(business_id, email)` key. Cross-business isolation proven with a dedicated test. Correctness bug, not a refactor.
- Backlog item #2: `PromptBuilder` split into a universal `ENGINE_RULES` block (Python constant) and a config-driven persona block (`identity_statement`, `response_style.max_sentences` read from `BusinessConfig`). Byte-identical output proven for both the default path and an explicit-config path.
- Backlog item #3: `QualificationEngine.required_fields` now derived from `BusinessConfig.qualification.fields`, filtered by `required`. Proven schema-driven with a second, distinct schema in tests, not just relabeled.
- Backlog item #4: `KnowledgeBase` made tenant-namespaced. All 9 existing `.md` files moved via `git mv` (history preserved) into `knowledge/kaivix/`. Retrieval logic itself untouched — only the source directory changed.
- Backlog item #5: `crm/leads.db`'s `leads` table changed from `email UNIQUE` to `business_id` column + composite `UNIQUE(business_id, email)` — the same class of correctness bug as item #1, fixed at the relational-schema level this time. `LongTermMemory` also gained a real, queryable `business_id` column in addition to its existing composite key. `Lead.from_row`'s positional tuple-fallback parsing was specifically tested against the new column to rule out silent index corruption.
- Backlog item #6: `ConversationEngine` wired to actually consume `BusinessConfig` — the last component that still silently defaulted to Kaivix. Resolves `business_id`/`BusinessConfig` once at construction (Decision #011), threads it into `QualificationEngine`, `KnowledgeBase`, `PromptBuilder`, `LeadService`, and `LongTermMemory` call sites. Zero behavior change proven for Kaivix's own default path; a distinct second business proven to actually change persona/qualification/knowledge/CRM behavior end-to-end. **This closes the BusinessConfig refactoring backlog: 7 of 7 items complete.**
- Building item #6's cross-business test surfaced a real bug: `BusinessConfigRepository._get_default_sections()` crashed with an unhandled `pydantic.ValidationError` instead of a `BusinessConfigError` when Kaivix's own reference config was incomplete. Fixed as Decision #013. Also surfaced an open product question: whether a business with no `persona.yaml` should really inherit Bray's identity via fallback (Decision #014).
- Decision #014 resolved: `persona.yaml` is now required per business, exactly like `identity.yaml` — no fallback to Kaivix's own persona exists anymore. `BusinessConfigRepository` fails loudly with a `BusinessConfigError` if a business's `persona.yaml` is missing. `_get_default_sections()` no longer builds a persona default at all.

**2026-07-26 — Milestone 5: Production Hardening & Appointment Scheduling**

- Production bug fix: real pricing figures removed from every document Bray can retrieve (`knowledge/kaivix/pricing.md` AND `knowledge/kaivix/objections.md` — the second found independently mid-fix). Real numbers moved to `docs/Internal_Pricing_Reference.md`, structurally unreachable by `KnowledgeBase`. Decision #016.
- `ConversationMemory` made persistent: SQLite-backed (`memory/conversation_memory.db`), tenant-scoped from day one, replacing the in-memory `defaultdict` that lost all state on restart. Decision #015.
- Conversation-quality eval suite added (`evals/run_conversation_evals.py`) — a standalone pre-deploy tool, deliberately kept out of the automated test suite, that runs scripted adversarial conversations against the real LLM and checks for known-bad patterns. Decision #017.
- Google Calendar integration built in three stages: provider interface + tenant-scoped OAuth token storage (Decision #018), real read-only availability surfacing on top of PlanningEngine's existing `drive_to_booking` signal, and real booking confirmation via strict numbered-slot matching (Decision #019) and actual calendar event creation, with a Calendly-link fallback on no-match or API failure. `core_ai/planning_engine.py` was never touched across any of this (Decision #020, verified via empty git diff at every stage).
- Suite grew from 33 to 93 tests across this milestone, all passing, zero real external calls in any automated test. OAuth setup itself was separately verified with a real browser consent flow (confirmed real calendars listed).

Every milestone above: proven with a dedicated test (not just "it runs"), confirmed zero blast radius outside its named files via `git diff --stat`, and committed/pushed as an individual rollback checkpoint before the next milestone began.

---

# Next Immediate Task

Perform a real end-to-end calendar connection and live booking verification: connect via `/oauth/google/connect`, complete a real conversation through to a real booked event on `brayiron@kaivixlab.com`'s calendar, confirm and clean up. This is recommended before the scheduling feature reaches real site visitors.

After that: continue Phase 2 of the roadmap — production testing, then Docker deployment — or address the newly logged `BusinessConfig.tools.enabled_tools` gap.

---

# Notes

This document should be updated:

- At the beginning of every milestone.
- At the completion of every milestone.
- Whenever priorities change.
- Whenever blockers are discovered.

It should always represent the current state of Kaivix Core.
