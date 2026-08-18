\# Kaivix Core Milestone Log



\*\*Version:\*\* 1.0

\*\*Status:\*\* Active

\*\*Last Updated:\*\* 2026-07-31



\---



\# Purpose



This document records every completed milestone in the development of Kaivix Core.



Each milestone should summarize:



\- What was built

\- Why it was built

\- Key architectural decisions

\- Lessons learned

\- Next milestone



This document serves as the historical development record of the project.



\---



\# Milestone Template



\---



\## Milestone #



\### Name



Status



Completed



Completion Date



YYYY-MM-DD



\---



\### Objective



What was the goal of this milestone?



\---



\### Work Completed



\-



\-



\-



\---



\### Files Modified



\-



\-



\-



\---



\### Architecture Impact



Describe any architectural changes.



If none:



None.



\---



\### Decisions Made



Reference Decision Log entries.



Example



Decision #008



BusinessConfig introduced.



\---



\### Testing



Describe testing completed.



Examples



\- Unit Testing

\- Manual Testing

\- Integration Testing

\- Edge Case Testing



\---



\### Lessons Learned



What was learned?



What could be improved?



\---



\### Remaining Work



\-



\-



\-



\---



\### Next Milestone



Name of the next milestone.



\---



\---



\# Completed Milestones



\---



\# Milestone 1



\## Core AI Employee Foundation



Status



Completed



Completion Date



2026-07-25



\---



\### Objective



Create the foundational architecture for Kaivix Core.



\---



\### Work Completed



\- Conversation Engine

\- Memory Architecture

\- Goal Engine

\- Planning Engine

\- Qualification Engine

\- Prompt Builder

\- Knowledge Base

\- SQLite CRM

\- FastAPI Backend



\---



\### Files Modified



Multiple project modules.



\---



\### Architecture Impact



Established the core architecture used by all future development.



\---



\### Decisions Made



Decision #001



Python owns business logic.



Decision #002



LLM generates language only.



Decision #003



Configuration over customization.



Decision #004



Modular architecture.



Decision #005



Conversation Engine as orchestrator.



Decision #006



MemoryManager as memory coordinator.



Decision #007



Planning before response generation.



Decision #008



BusinessConfig planned for customer customization.



\---



\### Testing



Core functionality tested during implementation.



\---



\### Lessons Learned



A modular architecture significantly improves maintainability.



Future development should continue separating responsibilities.



\---



\### Remaining Work



\- BusinessConfig

\- Appointment Scheduling

\- Google Calendar Integration

\- Production Testing



\---



\### Next Milestone



Documentation Foundation



\---



\# Milestone 2



\## Documentation Foundation



Status



In Progress



Completion Date



Pending



\---



\### Objective



Create permanent project documentation for architecture, development rules, roadmap, status, and decision tracking.



\---



\### Work Completed



\- Architecture.md

\- Development\_Rules.md

\- Decision\_Log.md

\- Current\_Status.md

\- Roadmap.md

\- Milestone\_Log.md



\---



\### Files Modified



docs/



\---



\### Architecture Impact



No architecture changes.



Documentation only.



\---



\### Decisions Made



Documentation becomes the permanent source of truth for future development.



\---



\### Testing



Documentation reviewed for completeness.



\---



\### Lessons Learned



A structured documentation system reduces reliance on long AI conversations and improves collaboration.



\---



\### Remaining Work



\- Business Vision

\- Feature Backlog



\---



\### Next Milestone



BusinessConfig Refactoring Backlog (Milestone 3)



\---

# Milestone 3

## BusinessConfig Refactoring Backlog (Items 1–5 of 7)

**Status**

In Progress (5 of 7 items complete)

**Completion Date**

Pending (item #6 in progress, item #7 confirmed complete as a no-op)

---

### Objective

Wire every hardcoded, Kaivix-specific value in the engine (persona identity, qualification fields, knowledge documents, CRM/memory tenant scoping) to the previously-scaffolded BusinessConfig system, one component at a time, with zero behavior change to Kaivix's own running system at every intermediate step.

---

### Work Completed

- Item #7: Confirmed dead-file cleanup (`core_ai/qualification_fields.py`, `core_ai/extracted_entities.py`) was a no-op — target files did not exist in the repository.
- Item #1: `LongTermMemory` fixed from an email-only key to a composite `(business_id, email)` key. This was a correctness bug, not a refactor — two businesses' customers sharing an email would previously have had their records silently merged.
- Item #2: `PromptBuilder.AGENT_IDENTITY` (hardcoded persona text) replaced by `BusinessConfig.persona.identity_statement`, verified byte-identical to the original hardcoded string. `RULES` split into a universal `ENGINE_RULES` Python constant plus one config-driven value (`max_sentences`).
- Item #3: `QualificationEngine.required_fields` now derived from `BusinessConfig.qualification.fields`, filtered by `required`, preserving schema order.
- Item #4: `KnowledgeBase` made tenant-namespaced; all 9 `.md` knowledge files moved via `git mv` into `knowledge/kaivix/` with git history preserved.
- Item #5: CRM `leads` table changed from `email UNIQUE` to a `business_id` column with composite `UNIQUE(business_id, email)`. `LongTermMemory` gained a real, queryable `business_id` column alongside its existing composite key.

---

### Files Modified

- `core_ai/business_config.py` (new)
- `core_ai/prompt_builder.py`
- `core_ai/qualification_engine.py`
- `knowledge/knowledge_base.py`
- `knowledge/*.md` → `knowledge/kaivix/*.md` (moved)
- `memory/long_term_memory.py`
- `crm/database.py`, `crm/base_crm.py`, `crm/sqlite_crm.py`, `crm/lead.py`
- `services/lead_service.py`
- `config/businesses/kaivix/*.yaml` (new, 8 files)
- `tests/test_business_config.py`, `tests/test_prompt_builder_business_config.py`, `tests/test_qualification_engine_business_config.py`, `tests/test_knowledge_base_business_config.py`, `tests/test_long_term_memory_business_scoping.py`, `tests/test_crm_business_scoping.py` (all new)

---

### Architecture Impact

No change to pipeline order, component responsibilities, or any engine's internal decision logic. Every component gained an optional `business_config`/`business_id` parameter defaulting to Kaivix's own configuration — this is a seam, not a rewrite. See Decision Log #009–#012.

---

### Decisions Made

Decision #009 — Config-driven refactor delivered incrementally, not as a big-bang rewrite.
Decision #010 — Tenant scoping implementation differs by storage backend, same correctness guarantee.
Decision #011 — `business_id` will be bound once at `ConversationEngine` construction, not per-message (applies to item #6).
Decision #012 — Real data-loss risk confirmed before every disposable-data database reset.

---

### Testing

Every item above shipped with a dedicated, purpose-built test — not just "the code runs":

- Item #1: cross-business isolation proven (a lead saved under one `business_id` is invisible under another).
- Item #2: byte-identical prompt output proven for both the default path and an explicit-config path.
- Item #3: schema-driven behavior proven with a second, distinct qualification schema, not just the default relabeled.
- Item #4: identical document set and retrieval output proven pre/post file move; namespace scoping proven with a distinct temp-directory namespace.
- Item #5: same-email-different-business isolation proven for the CRM; `Lead.from_row`'s positional tuple-fallback parsing specifically tested against the new column to rule out silent index corruption.

Full suite as of item #5: 19/19 passing.

---

### Lessons Learned

- Grounding every design decision in the actual current source file (not memory of an earlier read) caught a real mistake early (an incomplete/incorrectly-escaped `persona.yaml` identity statement) before it shipped.
- Asking explicitly whether a database's contents were disposable, per database and per milestone, avoided any risk of destroying real data during schema changes.
- Scoping each milestone to name its exact files upfront, and requiring the implementing session to prove (not assert) that everything else was untouched, kept blast radius verifiably small across five milestones.
- A documentation gap emerged during this work: this Milestone Log and the Decision Log were not updated in real time as each backlog item completed — they were reconciled after the fact. This entry itself is that reconciliation. Future milestones should update these documents at completion, not in a batch afterward.

---

### Remaining Work

- Item #6: `ConversationEngine` wiring — the step that makes every seam above actually load-bearing.
- Known issue, deliberately deferred: `PlanningEngine._FIELD_QUESTIONS` duplicates content now living in `qualification.yaml`.
- Known issue, deliberately deferred: CRM `delete_lead` was not scoped to `business_id` in item #5 (out of that milestone's stated scope).

---

### Next Milestone

ConversationEngine Wiring (backlog item #6)

---

# Milestone 4

## ConversationEngine Wiring — Backlog Item #6 (Backlog Complete, 7/7)

**Status**

Completed

**Completion Date**

2026-07-26

---

### Objective

Wire `ConversationEngine` — the only remaining component that didn't accept `BusinessConfig` — so every seam built in items #1–#5 becomes load-bearing end-to-end, not just accepted-and-ignored.

---

### Work Completed

- `business_id` and an optional `business_config_repository` added to `ConversationEngine.__init__`, resolving a cached `BusinessConfig` once at construction (not per-message — see Decision #011).
- `QualificationEngine` and `KnowledgeBase` now constructed with `business_config=self.business_config`.
- `hydrate_long_term_memory`, `persist_long_term_memory`, and `lead_service.save` call sites now pass `business_id=self.business_id`.
- `prompt_builder.build(...)` call site now passes `business_config=self.business_config`.
- No change to pipeline order, `services/chat_service.py`, any API router, or any other engine file.

This closes the BusinessConfig refactoring backlog: **7 of 7 items complete.**

---

### Files Modified

- `core_ai/conversation_engine.py`
- `tests/test_conversation_engine_business_config.py` (new)

---

### Architecture Impact

None beyond what items #1–#5 already established. This milestone activates those seams; it introduces no new architectural pattern.

---

### Decisions Made

Decision #011 (already logged, implemented here) — `business_id` bound once at construction, not per-message.
Decision #013 (new) — `BusinessConfigRepository` now fails loudly instead of crashing opaquely when its own default reference is incomplete; found and fixed as a direct result of this milestone's cross-business test.
Decision #014 (new, flagged open) — whether a business with no `persona.yaml` should really inherit Bray's identity via fallback. Not resolved; needs a product decision before onboarding a real second business.

---

### Testing

- Default-path regression: `ConversationEngine()` with no args proven identical to pre-milestone behavior for a full turn.
- Real cross-business proof: a distinct `business_config` (different persona name, different qualification fields, different knowledge namespace) actually produces a different assembled system prompt end-to-end — not just accepted as a parameter.
- Cross-business CRM/LTM isolation confirmed at the `ConversationEngine` level (reusing the isolation pattern from item #5).

Full suite: 26/26 passing (22 pre-existing + 4 new).

---

### Lessons Learned

- Building the cross-business test (not just the default-path regression) is what surfaced Decision #013's real bug. A milestone that only re-confirms the default path can pass cleanly while the actual multi-tenant capability underneath is broken — the harder test was the valuable one.
- `BusinessConfigRepository`'s fallback design has a genuine open product question (Decision #014) that only became visible once someone tried to actually construct a second business's config, even a test stand-in for one.

---

### Remaining Work

- Decision #014: resolve the persona-fallback question before onboarding a real second business.
- Previously flagged, still open: `PlanningEngine._FIELD_QUESTIONS` duplication; CRM `delete_lead` not `business_id`-scoped.
- Phase 2 of the broader roadmap (appointment scheduling, Google Calendar integration, production testing) has not started.

---

### Next Milestone

Resolve Decision #014, then begin Phase 2 (Appointment Scheduling).

---

# Milestone 5

## Production Hardening & Appointment Scheduling (Post-Backlog)

**Status**

Completed

**Completion Date**

2026-07-26

---

### Objective

With the BusinessConfig backlog closed, address the highest-priority gaps identified in a full roadmap review (a live production bug, a missing safety net, and the next planned feature), then build the first real end-to-end feature on top of the now-complete tenant-scoped architecture: appointment scheduling with real Google Calendar booking.

---

### Work Completed

- **Production bug fix**: real pricing figures removed from every document Bray can retrieve (knowledge/kaivix/pricing.md AND knowledge/kaivix/objections.md — the second found independently mid-fix, via the new test's own results). Real numbers moved to docs/Internal_Pricing_Reference.md, structurally unreachable by KnowledgeBase. PromptBuilder's pricing rule reworded to be business-agnostic.
- **ConversationMemory persistence**: SQLite-backed, tenant-scoped from day one (memory/conversation_memory.db), replacing the in-memory defaultdict that lost all state on restart.
- **Conversation-quality eval suite**: evals/run_conversation_evals.py, a standalone pre-deploy tool (not part of CI) that runs scripted adversarial conversations against the real LLM and checks for known-bad patterns (price leaks, bot admissions, crashes).
- **Google Calendar integration, built in three stages**:
  - Provider interface + tenant-scoped OAuth token storage (scheduling/base_calendar_provider.py, scheduling/google_calendar_provider.py, scheduling/calendar_token_store.py), plus a FastAPI OAuth router (api/routers/calendar_oauth.py).
  - Real availability surfacing: PlanningEngine's existing "drive_to_booking" signal now triggers a real free/busy lookup, attached to the conversation plan and surfaced in Bray's prompt — read-only, no booking yet.
  - Real booking confirmation: numbered-slot presentation, strict digit/ordinal matching (scheduling/slot_matcher.py), and actual calendar event creation on an unambiguous match, with a safe fallback (Calendly link) on no-match or API failure.

---

### Files Modified/Created

core_ai/prompt_builder.py, knowledge/kaivix/pricing.md, knowledge/kaivix/objections.md, docs/Internal_Pricing_Reference.md (new), memory/conversation_memory.py, memory/conversation_store.py (new), core_ai/conversation_engine.py, core_ai/conversation_plan.py, core_ai/working_memory.py, evals/ (new directory), scheduling/ (new directory: base_calendar_provider.py, google_calendar_provider.py, calendar_token_store.py, slot_matcher.py), api/routers/calendar_oauth.py (new), api/main.py, scripts/verify_google_calendar.py (new, throwaway verification tool, left in place).

---

### Architecture Impact

core_ai/planning_engine.py was never touched across any part of this milestone (verified via empty git diff at every stage) — the calendar feature is entirely additive at the ConversationEngine orchestration layer, preserving PlanningEngine's I/O-free boundary. Two new fields were added to ConversationPlan (available_slots, booking_confirmation, booking_failed), all purely additive with safe defaults, each proven byte-identical to prior prompt output when unset.

---

### Decisions Made

Decision #015 — ConversationMemory persistence, SQLite, tenant-scoped from day one.
Decision #016 — Pricing numbers removed structurally, not just by instruction.
Decision #017 — Conversation-quality eval suite kept separate from CI.
Decision #018 — Calendar OAuth: tenant-scoped tokens, shared app-level credentials.
Decision #019 — Booking confirmation uses numbered-slot matching, not fuzzy parsing.
Decision #020 — PlanningEngine stays I/O-free; calendar operations live in ConversationEngine.

---

### Testing

Every sub-feature shipped with dedicated tests, growing the suite from 33 to 93 tests across this milestone, all passing, zero real external calls in any automated test (Google API and LLM calls are fully mocked; the eval suite that does call the real LLM is deliberately excluded from the automated suite). A real end-to-end run was performed for both the pricing fix (verified via the eval suite against the live LLM) and the Google Calendar OAuth setup (verified via a real browser consent flow, confirmed real calendars listed).

---

### Lessons Learned

- Scoping a "fix pricing.md" task narrowly still surfaced a second, independent instance of the same bug in objections.md — worth grepping broadly for a pattern class before assuming a single-file fix is complete.
- A coincidental false-positive ("2pm works" matching slot "#2") was caught during test-writing, not after — evidence that thorough test-first thinking on the highest-stakes feature paid off directly.
- Real, deployed integrations (Google Calendar) have real-world setup friction (Workspace org policies, OAuth field validation errors) that no amount of code planning anticipates — these got resolved interactively as they came up, not pre-solved.

---

### Remaining Work

- Known issue, still open: PlanningEngine._FIELD_QUESTIONS duplication.
- Known issue, still open: CRM delete_lead not business_id-scoped.
- New, not yet addressed: BusinessConfig.tools.enabled_tools remains unused — calendar booking is gated only by OAuth connection status, not by this config list.
- A real, deliberate end-to-end booking test against the live brayiron@kaivixlab.com calendar (connect via /oauth/google/connect, complete a real conversation through to a real booked event, confirm and clean up) has not yet been performed — recommended before this is exposed to real site visitors.

---

### Next Milestone

Real end-to-end calendar connection + live booking verification, then continue Phase 2 (remaining: production testing, Docker deployment) or address the newly logged tools.yaml gap.

---

# Unlogged Work Since Milestone 5

**Status**

⚠️ Not a milestone entry. This section exists so this log does not imply Milestone 5 is the current state of the project.

Substantial work landed between 2026-07-27 and 2026-07-31 carrying Decisions #021–#027, and no milestone entry was written for any of it. Whether it constitutes one milestone, two (hardening, then business auth), or work not yet at a milestone boundary has not been decided — so no entry has been invented here. See Open Questions in `docs/Current_Status.md`.

All of it is now on `main` at `a19e76a` and pushed to `origin`. Suite grew 93 → 261 → 342 → **384 tests**, all passing.

What landed, for the record:

**Hardening and provider work** (Decisions #021–#023, suite 93 → 261):
- Scheduling fixes: OAuth `code_verifier` persistence, numbered-slot presentation, appointment-length slot chunking, booking confirmation no longer reading as a leaked system instruction, `redirect_uri` from `PUBLIC_BASE_URL`.
- Admin CRM dashboard behind Basic Auth, plus a `WWW-Authenticate` header fix.
- Bug-fix sweep (`31cdebd`) closing three of Milestone 5's four open Known Issues: `delete_lead` scoping, `enabled_tools` gating, and the `_FIELD_QUESTIONS` duplication. Also intent misclassification, calendar token expiry, and CORS restriction including the `www` variant.
- Decision #021 — LLM failures become a 503, not an unhandled 500. Fixed a real live outage where `/chat` returned 500 to every visitor while `/health` stayed 200.
- Decision #022 — `providers.yaml` drives real LLM and CRM selection; `BaseCRM` completed from one abstract method to five as a precondition.
- Decision #023 — multi-business serving via per-business engines in `ChatService`; Decision #011 validated rather than superseded. Message length capped.

**Business authentication and privacy** (Decisions #024–#027, suite 261 → 384):
- Decision #024 — per-business API keys on `POST /chat/{business_id}`, closing the authorization gap #023 recorded as an explicit trade-off. SHA-256 hash storage, `secrets.compare_digest` verification, enforced ahead of config loading, and no enumeration oracle on unknown `business_id`.
- Decision #025 — `providers.knowledge_provider` made authoritative; `knowledge.source_type` removed. Resolves the ambiguity #022 deliberately left open.
- Decision #026 — lead PII masked in `Logger.log_lead` (a latent exposure, no callers, not a breach).
- Eval harness rate-limit pacing, `--runs N`, and measured token-budget documentation in `evals/README.md`.
- Decision #027 — conversation turns withheld from logs by default, closing the trade-off #026 explicitly left open. Checking the live log before starting corrected #026's premise: three of four leaked lines came from `ConversationEngine._log_turn` on the FastAPI serving path, not from the CLI-only `log_user`/`log_ai` calls #026 had scoped to. The generated `conversation_summary` narrative concentrates exactly the identifying fields #026 masked elsewhere, and is prose rather than fields, so it's withheld wholesale rather than field-masked; structured turn metadata (stage, intent, goal, completion, missing field names) is kept in full. `KAIVIX_LOG_CONVERSATION_BODIES=1` re-enables bodies for debugging without disabling the address sweep or length bound.

This work lived on two branches, both merged to `main` on 2026-07-31 and both deleted afterward, neither having existed on `origin` before its own merge: `phase-5-business-auth-and-hardening` (Decisions #024–#026) was fast-forward merged first (`724c161..057b635`), then a second branch carrying Decision #027 was fast-forward merged on top (`057b635..a19e76a`). Until each merge landed, its decisions existed only on one local machine — worth noting as a lesson about where unpushed work is and is not backed up.

Also open: the conversation-quality eval suite cannot complete a pass on Groq's free tier (~62,000 tokens per pass against a 100,000 token-per-day cap). Details in `docs/Current_Status.md`.

---

# Milestone 6

## Live Outage Fix, Real Provider Interfaces, Security Review, and Phase 5 Authentication

**Status**
Completed

**Completion Date**
2026-07-31

---

### Objective

Fix a confirmed live production outage, turn provider abstraction from decorative scaffolding into something real, run an actual security review rather than a checklist exercise, close the authentication gap flagged when minimal multi-business serving first shipped, and protect real customer data across both structured and unstructured logging paths.

---

### Work Completed

- **Live outage fix (Decision, commit 912bb65)**: `/chat` was returning unhandled 500s whenever the Groq API failed, with `/health` staying green throughout — no alerting existed for the one failure mode that mattered. Added a provider-agnostic `LLMUnavailableError`, a graceful 503 fallback with a real user-facing message, and verified against the actual Groq API with a deliberately invalid key, confirming no secret ever reaches the log.
- **`tzdata` dependency (ed43488)**: found to be a latent production risk, not just a test-environment gap — `scheduling/google_calendar_provider.py` calls `ZoneInfo()` on every availability lookup, and Windows/some containers ship no IANA database at all without it.
- **Provider interfaces made real (977d403, Decision #022)**: `providers.yaml` was validated but never read. LLM and CRM provider selection now genuinely work, proven by a test that registers a distinct stub provider and confirms selection — not just field-reading. Found and fixed a real latent bug in the process: `BaseCRM` declared only one method while `LeadService` called five; a second provider could have satisfied the interface and crashed on first use.
- **Minimal Phase 5 (5853a54, Decision #023)**: one process serving multiple businesses, proven with zero changes to any engine-level file — direct validation that Decision #011's original design (bind `business_id` once at construction) held up under real multi-tenant use. Message-length cap (2000 chars) added in the same pass.
- **Security review (057b635, Decisions #024-025)**: AST-based SQL injection audit (27 `execute()` sites checked, 3 f-string cases individually verified safe), secrets-in-logs audit (clean), `pip-audit` run, HTTPS/HSTS posture reviewed and documented as a deliberate deferral, not an oversight.
- **`business_id` authentication (057b635, Decision #024)**: closed the exact gap flagged when minimal Phase 5 first shipped — `POST /chat/{business_id}` now requires a per-business API key (SHA-256 hashed, `secrets.compare_digest` verification), and unauthenticated requests are uniformly rejected (401) whether the business exists or not, closing the enumeration gap directly. Plain `POST /chat` proven byte-identical and unaffected.
- **Knowledge provider conflict resolved (057b635, Decision #025)**: `knowledge.source_type` and `providers.knowledge_provider` had silently competed for the same decision since the original provider work. `providers.knowledge_provider` now wins; the other field is an inert no-op. Zero behavior change confirmed for Kaivix.
- **PII redaction, round one (057b635, Decision #026)**: `Logger.log_lead` masked (email/name), though found to have no active callers — a closed gun, not an active breach.
- **PII redaction, round two (a19e76a, Decision #027)**: a materially more serious, *active* leak found on the live serving path — `_log_turn` was logging an LLM-generated conversation summary that embedded the visitor's email and name verbatim, at INFO level, on every real turn. Fixed with body-withholding by default (opt-in via `KAIVIX_LOG_CONVERSATION_BODIES`) and free-text email/name redaction swept across both the structured and narrative paths. A failing test caught a real flaw in the first implementation — the original 60-char truncate cut summaries before the redaction could ever fire, making the original "fix" accidental rather than real.
- **Eval suite root cause finally diagnosed**: Decision #021's own security fix (suppressing `str(error)` so a Groq `AuthenticationError` can't leak part of a key) had the side effect of hiding whether a 429 was a recoverable per-minute limit or a hard daily cap. The suite now paces requests and fails fast on a confirmed daily block rather than retrying into a dead end. `no_price_leak` and `no_bot_admission` confirmed passing on real runs; `booking_confirmation_phrasing` still has zero real coverage — the one thing this milestone did not close.

---

### Files Modified

`utils/llm.py`, `utils/llm_provider.py` (new), `utils/exceptions.py` (new), `utils/logger.py`, `crm/base_crm.py`, `crm/registry.py` (new), `services/chat_service.py`, `services/lead_service.py`, `core_ai/conversation_engine.py`, `api/routers/chat.py`, `api/handlers/exceptions.py`, `auth/api_key_store.py` (new), `scripts/issue_api_key.py` (new), `config/businesses/kaivix/knowledge.yaml`, `config/businesses/kaivix/providers.yaml`, `requirements.txt`, `evals/run_conversation_evals.py`, `evals/README.md`, plus new test files: `tests/test_provider_selection.py`, `tests/test_multi_business_serving.py`, `tests/test_conversation_turn_redaction.py`, and extensions to existing suites.

---

### Architecture Impact

`core_ai/planning_engine.py` and every other pure-decision engine file remained untouched throughout — every change this milestone made was additive at the orchestration layer (`ConversationEngine`, `ChatService`, the API routers) or in new, isolated modules. This is the second consecutive milestone that validates the original Phase 1 boundary between "decide" (engine files, I/O-free) and "act" (orchestration, I/O-heavy) without needing to bend it.

---

### Decisions Made

Decision #021 — graceful 503 fallback for LLM failures (the live outage fix).
Decision #022 — LLM and CRM provider selection made real; Knowledge deliberately left unabstracted pending #025.
Decision #023 — minimal multi-business serving; `business_id` authentication flagged as a prerequisite before third-party use.
Decision #024 — `business_id` authentication shipped, closing #023's flagged gap; unauthenticated requests uniformly 401 regardless of whether the business exists.
Decision #025 — `providers.knowledge_provider` resolved as authoritative over `knowledge.source_type`.
Decision #026 — `Logger.log_lead` PII masking.
Decision #027 — conversation turns withheld from logs by default; the more serious, active serving-path leak.

---

### Testing

Suite grew from 261 (pre-milestone baseline) to 384, entirely additive, run and verified at every commit boundary — including several points today where test counts were independently re-verified by direct execution rather than trusted from a commit message, after real discrepancies surfaced between reported and actual state.

---

### Lessons Learned

**Technical**: the most valuable single finding this milestone was procedural, not architectural — Decision #021's error-suppression fix (correct and necessary for its stated purpose) had an unintended side effect that made a real production problem (the Groq daily cap) indistinguishable from a transient blip for days. A security fix and an observability need were in tension, and the fix shipped without that tension being noticed. Worth remembering generally: hardening one property of a system can silently degrade another.

**Process**: this milestone also produced a serious, repeated coordination failure — multiple concurrent Claude Code sessions operating on this same backend repo without mutual awareness, at times producing near-misses (two branches diverging with neither containing the other's fix; a merge task given false premises by a stale worktree). No data was lost, and every near-miss was caught by a session verifying real git state before acting rather than trusting a prior report — but the recovery cost real time and required unusual vigilance. Standing rule going forward: one active backend session at a time, and every session checks `git status`/`git log` against reality before trusting any inherited instruction or premise, including instructions from a peer session.

---

### Remaining Work

- `booking_confirmation_phrasing` eval check: zero real coverage, needs one clean run once Groq quota allows.
- Groq billing: root cause of the outage and the reason full eval coverage remains blocked; being addressed independently on a business timeline, not an engineering one.
- Deliberately deferred, logged not forgotten: HSTS/app-level HTTPS enforcement, unbounded engine cache (no eviction policy), no key rotation or self-service issuance for the new per-business API keys.

---

### Next Milestone

Phase 4 — first real client onboarding. At this point the roadmap's remaining work is substantially a Growth & Operations question, not an engineering one.

---

# Milestone 7

## Model Migration, the Fabricated-Action-Claims Investigation, Real Gmail Sending, and a Knowledge Base Rewrite

**Status**
Completed

**Completion Date**
2026-08-18

---

### Objective

Migrate off a model Groq was decommissioning, close a confirmed live-production gap where Bray fabricated claims about actions it never performed, add real Gmail-sending capability for the one case that has genuine content behind it, and replace thin/generic knowledge base sections with real, founder-provided content.

---

### Work Completed

- **Booking-hallucination gap closed (60b3e81)**: a real visitor was told to "check your email and select a time" to confirm a booking — a mechanism that has never existed; real booking has always been numbered options inside the chat. Fixed with an explicit ENGINE_RULES rule against fabricated booking claims, loud logging on calendar API failures, and `is_connected()` checking expiry rather than just row existence. This was the first half of what later turned out to be a broader pattern (see below).
- **`/leads` router authenticated (7d7edd6, Decision #028 — already on record)**: flagged during the booking-hallucination investigation as a live, unauthenticated exposure of every captured lead's PII and write access. Closed by reusing `admin.py`'s existing `require_admin` dependency rather than a second credential scheme.
- **Calendar-not-connected warning (e17095d)**: logs a warning when `calendar_booking` is enabled but no calendar is actually connected, so this state is visible rather than silently offering no availability.
- **Chat widget URL linkification (f765fc0)**: URLs in chat messages are now rendered as clickable links, XSS-safe.
- **LLM migration to `openai/gpt-oss-120b` (e64bdcd)**: `llama-3.3-70b-versatile` was being decommissioned by Groq, making this a forced migration rather than an open bake-off between model options. `MAX_TOKENS` raised for the new reasoning-style model, and `no_price_leak`'s shorthand-range recognition fixed to match the new model's phrasing (e.g. "$1.5-3K" instead of the exact "$1,500"/"$3,000" wording). See Decision #029 for the full reasoning and an explicit correction of a premise in this milestone's own instructions.
- **Fabricated-action-claims investigation, round one — the prompt rule (3b207dc)**: the second half of the pattern 60b3e81 only partially closed. A visitor was told a checklist "had been emailed" — twice — when no email-sending code exists anywhere in this system. ENGINE_RULES rule #11 only covered booking status, so a new, general rule #12 was added: never claim to have performed, sent, set up, or completed any action unless a dedicated prompt section confirms it. Rules #13 (specificity) and #14 (avoid em dashes, calibrated for the new model) added in the same pass, along with a knowledge-base specificity audit and a new eval scenario reproducing the exact incident wording.
- **Fabricated-action-claims investigation, round two — the deterministic gate (6339e1c / 7351e55 / 61032b2 / f900423)**: rule #12 was confirmed to be a soft instruction — see Decision #030 for the precise, git-recorded finding on how reliable it actually was. Two independent, functionally-equivalent implementations of a real code-level gate were built concurrently without either session aware of the other: `core_ai/unbacked_action_detector.py` (Bray, 6339e1c, pushed directly to `main`) and `core_ai/action_claim_gate.py` (a parallel Claude Code session, 7351e55, on a feature branch based on stale `main`). Caught before either was blindly merged over the other, by checking real git state (`git fetch` + `git merge-base --is-ancestor`) rather than trusting either session's own account of what had landed. The duplicate (`action_claim_gate.py`) was cleanly reverted (61032b2, not force-rewritten — a `git revert` on top of already-pushed history) and the branch rebuilt on top of Bray's version via a normal merge before fast-forwarding into `main` (f900423). See Decision #030 and the Lessons Learned below — this is the same coordination-failure pattern Milestone 6 flagged, recurring in this milestone despite the standing rule written specifically to prevent it.
- **Real Gmail sending, scoped to one case (7c85d31)**: `gmail.send` added to the existing Calendar OAuth scope list rather than a new auth mechanism — one shared `/oauth/google/connect` consent now covers both. `scheduling/email_provider.py` reuses the same tenant-scoped `CalendarTokenStore` row and the same proactive refresh-before-expiry logic calendar already has (imported directly, not reimplemented). Wired to exactly one new backed action — `CONVERSATION_SUMMARY_EMAIL`, narrowly scoped to "email/send me a summary of *this conversation*" — after confirming the other candidate action (a calendar-confirmation email) needed no new code at all: `GoogleCalendarProvider.create_event` already sends one via `sendUpdates="all"`. Not verified end-to-end: no `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` and no stored OAuth token exist in the environment this was built in, and completing OAuth consent requires the founder's own real browser action — see Known Issues in `docs/Current_Status.md`.
- **Knowledge base content rewrite (c962b5e)**: `process.md`, `case_studies.md`, `company.md`'s differentiators, and `faq.md` replaced with real, founder-provided facts in place of the generic placeholder content an earlier audit flagged as too thin to support specific answers. Two verified competitor comparisons added to `competitors.md` (Podium; Cogent Labs, independently confirmed via `cogentlabs.co`) — Cogent Labs' real pricing figures were deliberately left out of the comparison text; see Decision #031. A `Payments` section with the real 50% deposit figure was added to `docs/Internal_Pricing_Reference.md`, kept out of every file `KnowledgeBase` can load, same treatment as the setup fee and monthly figures already isolated there.

---

### Files Modified

`api/routers/leads.py`, `chat_widget.html`, `config.py`, `core_ai/conversation_engine.py`, `core_ai/prompt_builder.py`, `core_ai/unbacked_action_detector.py` (new), `scheduling/email_provider.py` (new), `scheduling/google_calendar_provider.py`, `evals/run_conversation_evals.py`, `evals/README.md`, `docs/Internal_Pricing_Reference.md`, `knowledge/kaivix/{process,case_studies,company,competitors,faq}.md`, plus new test files: `tests/test_unbacked_action_detector.py`, `tests/test_conversation_engine_unbacked_actions.py`, `tests/test_email_provider.py`, `tests/test_conversation_engine_summary_email.py`, `tests/test_calendar_confirmation_email_coverage.py`, `tests/test_prompt_builder_engine_rules.py`, `tests/test_leads_router_auth.py`, and extensions to existing suites.

---

### Architecture Impact

The unbacked-action gate sits in `ConversationEngine.process_message`, checked before intent classification, stage detection, or any LLM call — the same "Python decides, LLM never gets a turn" placement `_maybe_resolve_booking` already established for booking. `EmailProvider` follows `GoogleCalendarProvider`'s exact shape (same token store, same refresh discipline) rather than introducing a second auth pattern. `core_ai/planning_engine.py` remained untouched throughout, the third consecutive milestone validating that boundary.

---

### Decisions Made

Decision #029 — LLM migration to `openai/gpt-oss-120b`, forced by Groq's `llama-3.3-70b-versatile` decommission (not a comparative model selection — see the decision entry for a correction of a premise this milestone's own instructions assumed).
Decision #030 — deterministic code-level gate adopted over the prompt-only rule as the actual guarantee against fabricated action claims.
Decision #031 — the knowledge base's dollar-figure guardrail (`tests/test_pricing_knowledge_scoping.py`) left intact rather than widened for verified competitor pricing; Cogent Labs' comparison written qualitatively instead.

---

### Testing

Suite grew from 384 (Milestone 6 baseline) to **469**, entirely additive, run and verified at every commit boundary. One environment-level fix along the way (a broken `cryptography`/`_cffi_backend` install) retroactively confirmed roughly 29 previously-reported "environment-only" failures really were environment noise and not disguised regressions, once the environment itself was repaired.

---

### Lessons Learned

**On the fabricated-action-claims fix, specifically, without softening it**: the prompt-only rule (ENGINE_RULES #12) looked like it had closed the gap — it read clearly, it was general rather than scoped to one incident, and it passed review. `core_ai/unbacked_action_detector.py`'s own docstring records what actually happened when it met live production: *"ENGINE_RULES rule 12 asks the model never to fabricate an action, but live production testing found it only holds about half the time — it is a soft instruction with nothing actually enforcing it."* A rule the model can silently ignore roughly half the time is not a fix, no matter how well-reasoned it reads in a diff. The thing that actually holds is the deterministic gate: not because it was proven against a tally of live production calls (see Decision #030 for why no such tally exists on record, and a correction of that specific premise), but because it structurally removes the LLM from the decision entirely — `tests/test_conversation_engine_unbacked_actions.py::TestUnbackedActionTwentyRunDeterminism` proves this by forbidding the LLM call outright across 20 runs, a stronger guarantee than sampling live output ever could be. The general lesson: a prompt instruction, however well-written, is a request the model can decline. A guarantee has to be structural.

**Process, again**: Milestone 6 recorded a standing rule after multiple concurrent sessions produced near-misses on this same repo — "one active backend session at a time, and every session checks `git status`/`git log` against reality before trusting any inherited instruction or premise." That exact failure mode recurred in this milestone: two sessions independently built the same gate, neither aware of the other, and one very nearly got blindly merged over the other on a false premise about which branch held which commit. It was caught the same way Milestone 6 said it should be — checking real git state before acting — not because the rule was followed in advance, but because it was applied as a check afterward. Worth restating rather than assuming Milestone 6's write-up alone prevents a repeat: it didn't, this time.

---

### Remaining Work

- Real end-to-end verification of the summary-email feature: no `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` and no stored OAuth token exist in the environment this was built in; the founder must reconnect via `/oauth/google/connect` (gmail.send is a new scope) and a real send must be confirmed to land in a real inbox.
- `knowledge/kaivix/objections.md` still references Lumina Shades metrics (20+ hours/week, sub-2-minute response time) that were removed from `case_studies.md` in this milestone's rewrite — flagged, not fixed; out of scope for the rewrite that touched it.
- Real end-to-end booking test against a live calendar: still not performed (carried over from Milestone 6).
- Eval suite: still cannot complete a full pass against the real LLM from every environment this work has been done in (Groq API unreachable / no key in at least one working environment this milestone) — carried over from Milestone 6, not newly caused here.

---

### Next Milestone

Real end-to-end verification (email and calendar booking both), then whatever Milestone 6 already named next: production testing and deployment.

---

# Future Milestones



Future milestones should follow the template above.



Each completed milestone should be added to this document immediately after completion.



\---



\# Milestone Guidelines



Future milestones should follow the template above.



Each completed milestone should be added to this document immediately after completion.



\---



\# Milestone Guidelines



Every milestone should have:



✓ Clear objective



✓ Defined scope



✓ Completion criteria



✓ Testing



✓ Documentation update



✓ Lessons learned



✓ Next milestone identified



\---



\# Definition of Complete



A milestone is complete only when:



\- Implementation finished

\- Testing completed

\- Documentation updated

\- Decision Log updated (if applicable)

\- Current Status updated

\- Repository committed



Only then should work begin on the next milestone.



\---



\# Revision History



| Date | Change | Author |

|------|--------|--------|

| 2026-07-25 | Initial milestone log created | Kaivix Development Team |

