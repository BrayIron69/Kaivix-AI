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
AI Employee Version 1 — BusinessConfig Refactoring Backlog

**Current Milestone**
BusinessConfig Refactoring Backlog — complete (7 of 7). Decision #014 (persona-fallback policy) resolved. Next: begin Phase 2 (Appointment Scheduling).

**Overall Progress**
🟩 7 of 7 BusinessConfig refactoring backlog items complete. This backlog was the prerequisite for the rest of AI Employee V1 (scheduling, calendar integration, deployment) — that work can now begin.

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
- ✅ Working Memory
- ✅ Conversation Memory
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

## BusinessConfig (new since last status update)
- ✅ BusinessConfig spec finalized (`docs/Business_Config.md`)
- ✅ YAML file structure: one directory per business (`config/businesses/<id>/`), split across 8 files (identity, persona, qualification, knowledge, tools, channels, guardrails, providers)
- ✅ Pydantic validation models + `BusinessConfigRepository` (`core_ai/business_config.py`)
- ✅ Kaivix's own config populated, verified byte-identical to the previously hardcoded values it replaced
- ✅ `DEFAULT_BUSINESS_ID = "kaivix"` seam adopted consistently across every refactored component

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
The BusinessConfig refactoring backlog is done (7 of 7 items complete). Decision #014 (docs/Decision_Log.md) is resolved — `persona.yaml` is now required per business, like `identity.yaml`, with no fallback to Kaivix's own persona. Current focus: begin Phase 2 of the roadmap (Appointment Scheduling).

**Current Tasks**
- Scope and begin Phase 2, Milestone: Appointment Scheduling

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
**Status:** Not Started
**Priority:** High

## Milestone: Google Calendar Integration
**Status:** Not Started
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

---

# Current Technical Debt

No significant technical debt beyond the two Known Issues above.

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
Begin Phase 2 of AI Employee Version 1 (Appointment Scheduling, Google Calendar Integration, Production Testing).

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
- Appointment scheduling
- Google Calendar integration
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

Every milestone above: proven with a dedicated test (not just "it runs"), confirmed zero blast radius outside its named files via `git diff --stat`, and committed/pushed as an individual rollback checkpoint before the next milestone began.

---

# Next Immediate Task

Begin Phase 2 of the roadmap — Appointment Scheduling, then Google Calendar Integration, then Production Testing.

---

# Notes

This document should be updated:

- At the beginning of every milestone.
- At the completion of every milestone.
- Whenever priorities change.
- Whenever blockers are discovered.

It should always represent the current state of Kaivix Core.
