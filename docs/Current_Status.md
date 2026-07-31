# Kaivix Core Current Status

**Version:** 1.0
**Status:** Active Development
**Last Updated:** 2026-07-31

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
AI Employee Version 1 (Roadmap Phase 1). Note: this document has historically called the current work "Phase 2", meaning the second half of AI Employee V1. `docs/Roadmap.md` uses "Phase 2" to mean Customer Validation. See Open Questions — the two documents disagree on the label, not on the work.

**Current Milestone**
Milestone 5 (Production Hardening & Appointment Scheduling) — complete, 2026-07-26. The work since then (bug-fix sweep, admin dashboard, LLM 503 fallback, provider registry, multi-business serving, per-business API keys, PII redaction — Decisions #021–#027) has **no milestone entry in `docs/Milestone_Log.md`** and no agreed name. See Open Questions.

**Overall Progress**
🟩 BusinessConfig refactoring backlog complete (7/7). 🟩 Milestone 5 complete. 🟩 Post-Milestone-5: three of the four then-open Known Issues are now closed, an admin CRM dashboard exists, LLM provider failures degrade to a 503 instead of a 500, `providers.yaml` actually drives LLM and CRM selection, one process can serve many businesses, `POST /chat/{business_id}` is authenticated per business, and conversation turns are withheld from logs by default. **384 automated tests passing** (verified by running `python -m unittest discover -s tests` on 2026-07-31, not carried over from a previous doc revision).

Not yet done: a real end-to-end booking test against a live calendar, and deployment + production testing. The conversation-quality eval suite is currently **unrunnable** against Groq's free tier — see Known Issues.

---

# Completed Components

## Core Engine
- ✅ Conversation Engine — resolves a `BusinessConfig` once at construction and threads it into every sub-component (backlog item #6, backlog complete 7/7); also reads `providers` (Decision #022) and gates calendar booking on `tools.enabled_tools`, failing closed
- ✅ Intent Detection — misclassification fixes landed (`tests/test_intent_detector.py`)
- ✅ Goal Engine
- ✅ Planning Engine — field hints now read from each business's `qualification.yaml` `prompt_hint`; the hardcoded `_FIELD_QUESTIONS` dict is gone. Still I/O-free (Decision #020)
- ✅ Prompt Builder — config-driven (persona identity + response length read from BusinessConfig, universal rules stay in engine code)
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
- ✅ SQLite CRM — tenant-scoped: `business_id` column, composite `UNIQUE(business_id, email)` constraint (previously unique on email alone, a real cross-tenant correctness bug)
- ✅ Lead Storage
- ✅ `delete_lead` now `business_id`-scoped through `BaseCRM`, `SQLiteCRM` and `LeadService` (closes the Known Issue logged at Milestone 5; one residual gap at the REST route, see Known Issues)
- ✅ `BaseCRM` expanded from one abstract method to the five `LeadService` actually calls, so "implements `BaseCRM`" now means "usable by `LeadService`" (Decision #022)
- ✅ CRM provider selected via `crm/registry.py` from `providers.crm_provider`; `sqlite` is the only registered implementation (`crm/hubspot.py` and `crm/gohighlevel.py` are empty files)
- ✅ Admin CRM dashboard behind Basic Auth (`tests/test_admin_dashboard.py`), including a `WWW-Authenticate` header fix found while building it

## BusinessConfig
- ✅ BusinessConfig spec finalized (`docs/Business_Config.md`)
- ✅ YAML file structure: one directory per business (`config/businesses/<id>/`), split across 8 files (identity, persona, qualification, knowledge, tools, channels, guardrails, providers)
- ✅ Pydantic validation models + `BusinessConfigRepository` (`core_ai/business_config.py`)
- ✅ Kaivix's own config populated, verified byte-identical to the previously hardcoded values it replaced
- ✅ `DEFAULT_BUSINESS_ID = "kaivix"` seam adopted consistently across every refactored component

## Conversation-Quality Eval Suite
- ✅ `evals/run_conversation_evals.py` — standalone, manually-run pre-deploy tool (deliberately not part of `python -m unittest discover -s tests`), runs scripted adversarial conversations against the real Groq LLM and checks for known-bad patterns (price leaks, bot admissions, crashes)
- ⬜ Cannot currently complete a full pass on Groq's free tier — see Known Issues

## Resilience & Provider Abstraction (new since last status update)
- ✅ LLM provider failures degrade to `HTTP 503` with `Retry-After: 30` instead of an unhandled 500 (Decision #021). `utils/llm.py` catches `GroqError` and re-raises a provider-agnostic `LLMUnavailableError`; the failure log records the exception **class** and status, never `str(error)`, because a provider message can quote part of an API key. Fixed in response to a real live outage where `/chat` returned 500 to every visitor while `/health` stayed 200
- ✅ `providers.yaml` drives real provider selection for `llm_provider` and `crm_provider` via name-to-class registries (`utils/llm_provider.py`, `crm/registry.py`); an unrecognised name raises at engine construction rather than silently falling back (Decision #022)
- ⬜ `knowledge_provider` and `calendar_provider` remain decorative — see Known Issues

## Multi-Business Serving (new since last status update)
- ✅ `ChatService` holds `dict[business_id, ConversationEngine]`, built lazily on first request per business and reused after; `POST /chat/{business_id}` added; plain `POST /chat` unchanged and still serves `DEFAULT_BUSINESS_ID` byte-identically (Decision #023)
- ✅ Proven against a synthetic in-test second business. **No real second business config exists** — no `config/businesses/test-business-b/` was committed, deliberately
- ✅ Message length capped
- ✅ CORS restricted to known origins, including the `www` variant (`tests/test_cors_policy.py`)
- ⬜ Engines are cached for process lifetime with no eviction; fine for a handful of businesses, a real tenant list would want a bounded cache

## Business Authentication & Privacy (new since last status update)
- ✅ Per-business API keys (Decision #024) — `auth/api_key_store.py`, tenant-scoped with `business_id` as primary key, storing only a SHA-256 hash and verifying with `secrets.compare_digest`. Plaintext exists once, at issue time
- ✅ `POST /chat/{business_id}` requires a matching `X-API-Key`, enforced as a dependency so it runs **before** config loading and engine construction: an unauthorized caller does no work, and an unknown `business_id` returns the same 401 as a known one rather than acting as an enumeration oracle
- ✅ Plain `POST /chat` deliberately left unauthenticated — it is the live widget's traffic. Byte-identical output asserted with the auth layer installed
- ✅ `scripts/issue_api_key.py` issues/rotates a key and refuses a `business_id` with no valid config. A key has been issued for `kaivix`
- ✅ Knowledge provider conflict resolved (Decision #025) — `providers.knowledge_provider` is authoritative and `knowledge.source_type` is removed, so all four backend choices live in `providers.yaml` under one naming convention. A stale `source_type` key is inert (pydantic ignores unknown keys), so no existing config breaks
- ✅ Lead PII masked in logs (Decision #026) — `Logger.log_lead` reduces email to first char + domain and name to initials, adds a non-reversible correlation ref, and keeps bounded qualification data. `log_lead` had no callers, so this closed a latent exposure rather than a breach
- ✅ Conversation turns withheld from logs by default (Decision #027) — closes the trade-off #026 left open. Checking the log corrected #026's premise: three of four leaked lines came from `ConversationEngine._log_turn` on the live serving path, not from the CLI harness `log_user`/`log_ai` calls #026 had scoped to. `log_user`/`log_ai` bodies are now withheld outright; `_log_turn`'s structured fields (stage, intent, goal, completion, missing field names) are kept in full, while its free-text `conversation_summary` narrative is withheld and its `working_memory.summary` is swept for addresses and bounded. `KAIVIX_LOG_CONVERSATION_BODIES=1` re-enables bodies for debugging; masking and bounding still apply even then

## Google Calendar Integration
- ✅ Provider interface + tenant-scoped OAuth token storage (`scheduling/base_calendar_provider.py`, `scheduling/google_calendar_provider.py`, `scheduling/calendar_token_store.py`), one connection per business, shared app-level OAuth credentials
- ✅ FastAPI OAuth router (`api/routers/calendar_oauth.py`), OAuth setup itself verified with a real browser consent flow
- ✅ Real availability surfacing — `ConversationPlan.available_slots`, a read-only free/busy lookup triggered by PlanningEngine's existing `drive_to_booking` signal, surfaced in Bray's prompt
- ✅ Real booking confirmation — numbered-slot matching (`scheduling/slot_matcher.py`, strict digit/ordinal only, never fuzzy) and real calendar event creation, with a Calendly-link fallback on no-match or API failure
- ✅ OAuth `code_verifier` persistence, `redirect_uri` derived from `PUBLIC_BASE_URL` (no longer hardcoded to localhost), calendar token expiry handling, appointment-length slot chunking, and a fix so the booking confirmation reads as natural language rather than a leaked system instruction
- ✅ Booking gated on `tools.enabled_tools`, not only on OAuth connection status
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
With business authentication merged (2026-07-31), the remaining work before deployment is verification rather than construction: a real end-to-end booking against a live calendar, and getting the eval suite runnable again so there is a working pre-deploy safety net.

The authorization gap that Decision #023 recorded as an explicit trade-off ("nothing authenticates `business_id`") is now closed on `main` — it was the single gap standing between the code and a third party's `business_id` existing in `config/businesses/`.

**Current Tasks**
- Real end-to-end calendar connection + live booking verification (`/oauth/google/connect`, a real conversation through to a real booked event, confirm and clean up)
- Unblock the eval suite (see Known Issues) so there is a working pre-deploy safety net before deployment
- Then: production testing, Docker deployment

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

## Milestone: Business Authentication & Hardening
**Status:** Complete and merged to `main` (2026-07-31) — per-business API keys (#024), knowledge provider authority (#025), lead PII redaction (#026), conversation turns withheld from logs by default (#027)
**Priority:** Was High — #024 was the prerequisite before any third party's `business_id` could exist

## Milestone: Production Deployment
**Status:** Not Started — planned after live booking verification and after the eval suite is runnable again
**Priority:** High

Sequenced steps:
1. Create a Dockerfile and confirm the app reads `PORT` from the environment (required by most container hosts)
2. Choose a hosting platform (leading candidate: Google Cloud Run, given the existing GCP account and genuine free tier fit — not yet finalized)
3. Deploy with `GROQ_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` set as real platform secrets, never baked into the image or committed
4. Add the production redirect URI to the existing Google OAuth client (alongside the localhost one, not replacing it)
5. Reconnect Kaivix's calendar against the production URL
6. Update `chat_widget.html`'s hardcoded `API_URL` (currently `http://localhost:8000/chat`) to the real production URL
7. Embed the widget into the actual live kaivixlab.com pages, replacing the current static/scripted fake "Live demo" chat card
8. Run the conversation-quality eval suite against the deployed instance before opening it to real visitors — **currently blocked, see Known Issues**
9. Basic uptime/error monitoring — at minimum, visibility if the server or LLM call fails while a real visitor is mid-conversation

Note: `chat_widget.html` and the `/chat` API endpoint already exist and are functional — this milestone is about deployment and connection, not building a widget or API from scratch.

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

## Issue: Conversation-quality eval suite cannot complete a pass on Groq's free tier
**Status:** Open — blocking
**Owner:** Evals / Infrastructure
**Priority:** High — this is the designated pre-deploy safety net, and it currently cannot run

A full eval pass is **~24 real LLM calls at ~2,600 tokens each, so ~62,000 tokens**. Groq's on-demand tier enforces two separate token limits, measured 2026-07-30 on `llama-3.3-70b-versatile`:

| Limit | Value | Behaviour |
|---|---|---|
| Tokens per minute (TPM) | 12,000 | Refills continuously. A full pass is ~5x this, so it **will** be hit. |
| Tokens per day (TPD) | 100,000 | Rolling ~24h window. A full pass is ~62% of it. |

The two need opposite responses, and the runner now handles them differently: a TPM block is waited out with a short constant retry, while a TPD block cannot be waited out inside a run, so the first call that exhausts its retries marks the provider hard-blocked and every remaining call fails immediately instead of re-waiting.

Consequence for reading results: **a `no_crash` FAIL is ambiguous on its own** — it means either the engine genuinely raised, or the provider refused. A rate-limited turn prints `[EXCEPTION] LLMUnavailableError ... status=429`, which is neither an engine defect nor evidence the check passed. A scenario that never reached the model has **no result**, and reporting it as a pass is the specific mistake to avoid.

Note that `429` is all the tool can see. The 429 *body* names the limit, the amount used and the reset time, and `utils/llm.py` discards it deliberately (Decision #021 — provider error text can quote part of an API key). To get real numbers, call the API directly and print the error body.

The runner now paces around this: a TPM block is retried briefly, then sustained refusal marks the provider hard-blocked so the rest of the run fails fast instead of re-waiting for every call. `--runs N` was added. This makes a blocked run *legible*; it does not make a full pass possible within the free tier's daily cap.

Practical options: pace a pass across days, trim the scenario set, or move the eval to a paid tier or a second provider. Not yet decided.

## Issue: Real end-to-end booking test against the live calendar not yet performed
**Status:** Open, flagged not fixed
**Owner:** Scheduling
**Priority:** High — recommended before real site visitors reach this feature

Every calendar/booking behavior is proven with mocked unit tests (Google API and LLM calls fully mocked, 384 passing); the OAuth setup itself was separately verified with a real browser consent flow (confirmed real calendars listed). A full, deliberate end-to-end run — connect a real calendar via `/oauth/google/connect`, complete a real conversation through to a real booked event on `brayiron@kaivixlab.com`'s calendar, confirm and clean up — has not yet been performed.

## Issue: `knowledge_provider` and `calendar_provider` still decorative
**Status:** Open, deliberately deferred
**Owner:** BusinessConfig / Knowledge
**Priority:** Low

Decision #022 wired `llm_provider` and `crm_provider` to real registries but deliberately excluded knowledge on three counts: there is no ABC and no second implementation, so the abstraction would be invented rather than wired up; `_load_documents` hardcodes filesystem globbing and consumers read `knowledge.documents` directly, so the seam is wider than one method; and two config fields competed for the same decision with nothing specifying which won.

The third of those is now resolved by Decision #025 (`providers.knowledge_provider` is authoritative, `knowledge.source_type` removed), which clears #022's stated blocker. The code-shape work — an ABC and a real second implementation — remains. `calendar_provider` is untouched and has only one implementation.

## Issue: `DELETE /leads/{email}` route not business_id-scoped
**Status:** Open — residual narrowing of a closed issue
**Owner:** CRM / API
**Priority:** Low

The CRM layer is now fully scoped: `BaseCRM.delete_lead`, `SQLiteCRM.delete_lead` and `LeadService.delete` all take `business_id`. But `api/routers/leads.py` calls `lead_service.delete(email)` without one, so the route silently operates on `DEFAULT_BUSINESS_ID`. With multi-business serving now real (Decision #023), this admin route can only ever delete Kaivix's leads — currently a limitation rather than a cross-tenant hazard, since it cannot reach another tenant's row. Worth closing before a second real business exists.

## Issue: Engine cache has no eviction
**Status:** Open, accepted trade-off
**Owner:** ChatService
**Priority:** Low

`ChatService` caches one `ConversationEngine` per `business_id` for the process lifetime with no eviction (Decision #023). Fine for a handful of businesses; a real tenant list would want a bounded cache.

## Closed since the last update

- **PlanningEngine field-hint duplication** — closed. `_FIELD_QUESTIONS` is gone; hints now read from each business's `qualification.yaml` `prompt_hint`, with a fallback for fields that define none (`tests/test_planning_engine_field_questions.py`).
- **CRM `delete_lead` not business_id-scoped** — closed at the CRM layer; see the residual route gap above.
- **`BusinessConfig.tools.enabled_tools` unused** — closed. `ConversationEngine` reads it to gate calendar booking and fails closed when it is empty or null (`tests/test_conversation_engine_tool_gating.py`).
- **Unauthenticated `business_id`** — closed by Decision #024, merged to `main` on 2026-07-31. `POST /chat/{business_id}` now requires a per-business `X-API-Key`.

---

# Current Technical Debt

No significant technical debt beyond the Known Issues above.

---

# Active Branch

`main`, at `a19e76a`, pushed to `origin`. No unmerged feature branches — `phase-5-business-auth-and-hardening` (Decisions #024–#026) and the conversation-turn-redaction branch (Decision #027) were both fast-forward merged into `main` on 2026-07-31 and deleted; neither existed on `origin` before its merge.

---

# Current Technology Stack

**Backend**
- Python
- FastAPI

**Database**
- SQLite (separate databases, intentionally not merged: `crm/leads.db`, `memory/long_term_memory.db`, `memory/conversation_memory.db`, plus tenant-scoped calendar OAuth token storage)

**Version Control**
- Git
- GitHub

**Deployment**
- Frontend: Vercel
- Backend: To Be Determined

**LLM**
- Groq (`llama-3.3-70b-versatile`), selected via `providers.llm_provider` through `utils/llm_provider.py`; the only registered LLM provider today

**Provider Abstraction**
- Real for `llm_provider` and `crm_provider` — name-to-class registries, unknown names fail loudly at engine construction (Decision #022)
- Still decorative for `knowledge_provider` and `calendar_provider` (see Known Issues)

---

# Project Goals

**Immediate Goal**
Land the business-auth work, perform a real end-to-end calendar connection and live booking verification, and get the eval suite runnable again — then finish AI Employee Version 1 (Production Testing, Docker Deployment).

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
- Appointment scheduling — built and unit-tested (Milestone 5, hardened since); live end-to-end verification pending
- Google Calendar integration — built and unit-tested (Milestone 5, hardened since); live end-to-end verification pending
- Production testing — blocked on the eval suite being runnable
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

**2026-07-27 to 2026-07-30 — Post-Milestone-5 hardening (no milestone entry yet; see Open Questions)**

- Scheduling fixes: OAuth `code_verifier` persistence, numbered-slot booking presentation, appointment-length slot chunking, and a fix so the booking confirmation reads as natural language rather than a leaked system instruction (with a regression eval scenario added). OAuth `redirect_uri` derived from `PUBLIC_BASE_URL` instead of hardcoded localhost.
- Admin CRM dashboard behind Basic Auth, including a `WWW-Authenticate` header bug found while building it.
- Bug-fix sweep (`31cdebd`): intent misclassification, calendar token expiry, `delete_lead` scoping, `enabled_tools` gating, CORS restriction including the `www` variant, and unified qualification hints. This closed three of the four Known Issues standing at Milestone 5.
- Live outage fix: Groq exceptions were surfacing as unhandled 500s — `/chat` returned 500 to every visitor while `/health` stayed 200, so nothing alerted. Now a 503 with `Retry-After`, via a provider-agnostic `LLMUnavailableError` (Decision #021).
- `providers.yaml` wired to real provider selection for LLM and CRM, with `BaseCRM` completed from one abstract method to five as a precondition (Decision #022).
- Multi-business serving: one process, many businesses, via lazily-constructed per-business engines in `ChatService`. Notably, Decision #011's prediction that `process_message` would need a `business_id` parameter turned out to be wrong in a useful way — because every component below `ConversationEngine` was already scoped, the capability came from holding *several* engines rather than changing how one binds its business. #011 stands, validated (Decision #023). Message length also capped.
- Suite grew from 93 to **261 tests**, all passing.
- Eval suite found to be blocked by Groq's token-per-day cap; the block was initially reported without numbers because `utils/llm.py` discards the 429 body by design. Real limits since measured — see Known Issues.

**2026-07-30 to 2026-07-31 — Business authentication & hardening (Decisions #024–#027)**

- Per-business API keys on `POST /chat/{business_id}`, closing the authorization gap Decision #023 had recorded as an explicit trade-off. Enforced as a dependency ahead of config loading, and an unknown `business_id` returns the same 401 as a known one so the endpoint is not an enumeration oracle. Plain `POST /chat` left unauthenticated on purpose — it carries the live widget's traffic (Decision #024).
- `providers.knowledge_provider` made authoritative and `knowledge.source_type` removed, resolving the duplicate-config ambiguity Decision #022 had deliberately left open rather than guessing at. Zero behaviour change for Kaivix, asserted on namespace, loaded document set and retrieval output (Decision #025).
- `Logger.log_lead` now masks direct identifiers while keeping qualification data. No callers existed, so this closed a latent exposure rather than a breach (Decision #026).
- Eval harness gained rate-limit pacing and `--runs N`, and `evals/README.md` gained a measured token-budget section. This corrected an earlier report that the eval was "blocked on Groq quota" with no numbers — the runner could not see them because `utils/llm.py` discards the 429 body by design.
- Suite grew from 261 to **342 tests**, all passing.
- Merged to `main` as a fast-forward on 2026-07-31 (`724c161..057b635`) and pushed to `origin`; the branch was deleted. It had never been pushed to `origin`, so until that merge all of #024–#026 existed only on one local machine.
- Conversation turns withheld from logs by default, closing the trade-off #026 explicitly left open (Decision #027). Checking the actual log before starting corrected the premise #026 was written on: only one of the four `@`-bearing lines in `logs/app.log` came from `log_user`; the other three came from `ConversationEngine._log_turn` on the FastAPI serving path, which #026 never mentioned. `_log_turn`'s generated `conversation_summary` narrative concentrates exactly the fields #026 went to the trouble of masking, so masking alone (as done for `log_lead`) couldn't apply to it — a turn is prose, not fields, so free text is withheld wholesale rather than field-masked, while structured turn metadata (stage, intent, goal, completion) is kept in full.
- Suite grew from 342 to **384 tests**, all passing. Merged to `main` as a fast-forward on 2026-07-31 (`057b635..a19e76a`) and pushed to `origin`; the branch was deleted, never having existed on `origin`.

Every milestone above: proven with a dedicated test (not just "it runs"), confirmed zero blast radius outside its named files via `git diff --stat`, and committed/pushed as an individual rollback checkpoint before the next milestone began.

---

# Next Immediate Task

1. Real end-to-end calendar connection + live booking verification: connect via `/oauth/google/connect`, complete a real conversation through to a real booked event on `brayiron@kaivixlab.com`'s calendar, confirm and clean up. Recommended before the scheduling feature reaches real site visitors.
2. Decide how to unblock the eval suite (pace across days, trim scenarios, or pay for a tier), since it gates the deployment checklist.
3. Production testing, then Docker deployment.

---

# Open Questions

These are genuinely unresolved from the commit history and Decision Log, and are recorded rather than guessed at.

1. **Does the post-Milestone-5 work constitute Milestone 6?** `docs/Milestone_Log.md` has no entry after Milestone 5 and no reference to a Milestone 6 anywhere in `docs/`. The work from 2026-07-27 onward is substantial and carries Decisions #021–#027, and the log's own rule is that "each completed milestone should be added to this document immediately after completion" — but nothing states whether this was intended as one milestone, two (hardening, then business auth), or ongoing work not yet at a milestone boundary. No entry has been invented for it.

2. **What does "Phase 2" mean?** This document has used "Phase 2" for the second half of AI Employee V1 (production hardening, testing, deployment). `docs/Roadmap.md` uses "Phase 2" for Customer Validation, with all V1 work inside Phase 1. Both are internally consistent; they just disagree on the label. Worth picking one.

3. **Was the live booking verification attempted?** It is still listed as not performed. `de27c26` and `ef5fc84` fixed booking-presentation bugs in a way that suggests real interaction with the feature, but no commit records a completed end-to-end run against a live calendar, so it remains open.

---

# Notes

This document should be updated:

- At the beginning of every milestone.
- At the completion of every milestone.
- Whenever priorities change.
- Whenever blockers are discovered.

It should always represent the current state of Kaivix Core.
