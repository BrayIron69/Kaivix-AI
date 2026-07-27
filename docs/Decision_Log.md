\# Kaivix Core Decision Log



\*\*Version:\*\* 1.0  

\*\*Status:\*\* Active  

\*\*Last Updated:\*\* 2026-07-25



\---



\# Purpose



This document records significant architectural, technical, and product decisions made during the development of Kaivix Core.



The purpose is to preserve the reasoning behind important decisions so they are not revisited unnecessarily.



Every major architectural or product decision should be documented here.



\---



\# Decision Format



Every decision follows this structure.



\---



\## Decision #XXX



\*\*Title\*\*



\*\*Date\*\*



\*\*Status\*\*



Accepted | Rejected | Deprecated | Superseded



\### Context



Why was this decision needed?



\### Decision



What was decided?



\### Reasoning



Why was this chosen?



\### Consequences



Benefits



Trade-offs



Future considerations



\---



\# Accepted Decisions



\---



\# Decision #001



\## Python Owns Business Logic



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



Business decisions must remain predictable and testable.



\### Decision



All deterministic business logic will be implemented in Python.



\### Reasoning



Language models can be inconsistent.



Business rules require deterministic behavior.



Python provides validation, testing, debugging, and predictable execution.



\### Consequences



Benefits



\- Predictable behavior

\- Easier testing

\- Better debugging

\- Easier maintenance



Trade-offs



\- More Python code

\- Less prompt-driven logic



\---



\# Decision #002



\## LLM Generates Language Only



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



Language models excel at communication but should not control application behavior.



\### Decision



The LLM is responsible only for generating natural language.



\### Reasoning



The AI should communicate decisions rather than make business decisions.



Business workflows remain deterministic.



\### Consequences



Benefits



\- Reliable workflows

\- Easier debugging

\- Lower hallucination risk



Trade-offs



\- Additional application logic required



\---



\# Decision #003



\## Configuration Over Customization



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



Kaivix Core will support many businesses.



Hardcoding customer-specific behavior is not scalable.



\### Decision



Customers will customize behavior through configuration instead of modifying source code.



\### Reasoning



Configuration enables rapid onboarding and reduces maintenance.



\### Consequences



Benefits



\- Easier onboarding

\- Cleaner architecture

\- Better scalability



Trade-offs



\- Larger configuration system



\---



\# Decision #004



\## Modular Architecture



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



Large software projects become difficult to maintain when responsibilities overlap.



\### Decision



Each component must have one primary responsibility.



\### Reasoning



Smaller modules are easier to understand, test, and extend.



\### Consequences



Benefits



\- Better maintainability

\- Easier testing

\- Simpler debugging



Trade-offs



\- More modules



\---



\# Decision #005



\## Conversation Engine Is the Orchestrator



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



The system requires a single coordinator for conversation flow.



\### Decision



ConversationEngine coordinates all major components.



\### Reasoning



Central orchestration simplifies communication between independent modules.



\### Consequences



Benefits



\- Clear execution flow

\- Better separation of responsibilities



Trade-offs



\- ConversationEngine must remain lightweight



\---



\# Decision #006



\## MemoryManager Is the Single Memory Entry Point



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



Multiple memory modules require centralized management.



\### Decision



MemoryManager becomes the only component responsible for coordinating memory operations.



\### Reasoning



Centralized access prevents inconsistent memory handling.



\### Consequences



Benefits



\- Cleaner interfaces

\- Easier maintenance

\- Future extensibility



Trade-offs



\- MemoryManager becomes a critical component



\---



\# Decision #007



\## Planning Before Response Generation



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



The AI should determine its objective before generating language.



\### Decision



Planning occurs before PromptBuilder and the LLM.



\### Reasoning



Responses should be driven by goals rather than generated spontaneously.



\### Consequences



Benefits



\- Goal-driven conversations

\- Better lead qualification

\- More consistent behavior



Trade-offs



\- Slightly more processing



\---



\# Decision #008



\## BusinessConfig Will Drive Customer Customization



\*\*Date\*\*



2026-07-25



\*\*Status\*\*



Accepted



\### Context



Future customers should not require source code modifications.



\### Decision



Business-specific settings will be stored inside BusinessConfig.



\### Reasoning



BusinessConfig enables reusable deployments.



\### Consequences



Benefits



\- Rapid customer onboarding

\- Reduced maintenance

\- Platform scalability



Trade-offs



\- More complex configuration system



\---

# Decision #009

## Config-Driven Refactor Delivered Incrementally, Not as a Big-Bang Rewrite

**Date**

2026-07-26

**Status**

Accepted

### Context

BusinessConfig existed as a spec and as unconsumed scaffolding. Every engine component (PromptBuilder, QualificationEngine, KnowledgeBase, CRM, LongTermMemory) still hardcoded Kaivix-specific values. Wiring all of them to BusinessConfig at once would touch the entire pipeline in a single change, with a large surface area for regressions.

### Decision

Each component was given an optional `business_config`/`business_id` parameter, defaulting internally to Kaivix's own config (`DEFAULT_BUSINESS_ID = "kaivix"`) when not supplied. Components were migrated one at a time, in backlog order, each proven independently before the next began. `ConversationEngine` itself — the only caller of all these components — was deliberately left untouched until every callee already supported the seam.

### Reasoning

This means every intermediate state of the refactor is a fully working, fully tested system with zero observable behavior change, rather than a multi-file change that only works once everything lands together. It also means each milestone has an independent, verifiable acceptance test (usually: prove byte-identical output for Kaivix's default path, then prove a second, distinct config actually changes behavior).

### Consequences

**Benefits**
- Every milestone independently revertible via git
- No "half-wired" intermediate state where the system is broken
- Each component's config-driven behavior is tested in isolation before the orchestrator ties them together

**Trade-offs**
- Until item #6 lands, `BusinessConfig` exists as dead weight for every component except when explicitly passed in tests — no runtime code path actually varies behavior by business yet.
- More total milestones than a single large refactor would have taken.

---

# Decision #010

## Tenant Scoping Implementation Differs by Storage Backend, Same Guarantee

**Date**

2026-07-26

**Status**

Accepted

### Context

Two different storage backends needed tenant scoping: `LongTermMemory` (SQLite, key-value interface via `BaseLongTermMemoryStore`) and the CRM (SQLite, relational table with a `UNIQUE` constraint). A single uniform implementation didn't fit both cleanly.

### Decision

`LongTermMemory` encodes `business_id` into a composite string key (`f"{business_id}::{email}"`) passed through its existing opaque `get(key)`/`save(key, profile)` interface — no interface or schema change needed beyond adding a queryable `business_id` column for visibility. The CRM's `leads` table instead gained a real `business_id` column with a table-level `UNIQUE(business_id, email)` constraint, since SQL uniqueness constraints require real columns, not string-encoded compound keys.

### Reasoning

Each backend already had a stable interface shape (`BaseLongTermMemoryStore`'s opaque key, and the `leads` table's relational schema); the tenant-scoping fix should adapt to each shape rather than forcing one implementation pattern onto both. The correctness guarantee (no cross-business data collision) is identical in both cases even though the mechanism differs.

### Consequences

**Benefits**
- Neither storage backend's public interface changed
- Each fix is the minimal, idiomatic change for its own backend

**Trade-offs**
- Two different-looking implementations of "the same kind of fix," which could read as inconsistent to someone unfamiliar with the reasoning — hence this decision entry.

---

# Decision #011

## business_id Bound Once at ConversationEngine Construction, Not Per-Message

**Date**

2026-07-26

**Status**

Accepted (pending backlog item #6 implementation)

### Context

The original backlog wording called for `ConversationEngine` to accept `business_id` in both its constructor and `process_message` signature. `ChatService` holds exactly one long-lived `ConversationEngine` instance and reuses it for every conversation. The project's explicit V1 constraint (per the founding handoff document) is one deployment per customer.

### Decision

`business_id` is resolved once, at `ConversationEngine.__init__`, into a cached `BusinessConfig`. `process_message`'s signature is not changed. No caller (`ChatService`, any API router) needs modification.

### Reasoning

Under a one-deployment-per-customer model, `business_id` cannot legitimately vary between messages within a single running process — there is only one business per deployment. Threading it through `process_message` now would add a parameter with no real use case yet, and would require touching every call site for no behavioral gain. Real multi-tenant serving (one process handling many businesses) is an explicitly deferred future phase, not a current requirement.

### Consequences

**Benefits**
- Smaller diff, fewer files touched
- No caller code changes required
- Correctly scoped to what V1 actually needs

**Trade-offs**
- When true multi-tenant serving is eventually built (multiple businesses through one running process), `process_message` will need its own `business_id` parameter at that point — this decision will need to be revisited, not just extended.

---

# Decision #012

## Real Data-Loss Risk Confirmed Before Every Disposable-Data Reset

**Date**

2026-07-26

**Status**

Accepted

### Context

Several backlog items required schema changes to `crm/leads.db` and `memory/long_term_memory.db` that were easiest to implement as a fresh rebuild rather than an in-place data migration.

### Decision

Before any database file was deleted and regenerated, the founder was explicitly asked whether its contents were disposable dev/test data or real captured leads, on a per-database, per-milestone basis — this was not assumed once and reused.

### Reasoning

`memory/long_term_memory.db` and `crm/leads.db` have different real-world risk profiles: the former is purely internal test data, the latter is fed by the live website's chat widget and could plausibly contain real visitor-submitted leads. Treating them identically without asking would have risked silent data loss.

### Consequences

**Benefits**
- Zero risk of destroying real business data during a schema refactor
- Establishes the standing pattern for any future schema-changing milestone

**Trade-offs**
- None — this is a pure process safeguard.

---

# Decision #013

## BusinessConfigRepository Fails Loudly When Its Own Default Reference Is Incomplete

**Date**

2026-07-26

**Status**

Accepted

### Context

`_get_default_sections()` falls back to Kaivix's own config files when another business's optional file is missing. If `config_root`'s Kaivix directory is itself missing a file, the code fell through to a bare `model_cls()` call — which throws an unhandled `pydantic.ValidationError` for any model with required fields (e.g. `BusinessPersona`), instead of the project's own established `BusinessConfigError` with a clear file/field-attributed message. Surfaced while building backlog item #6's cross-business test, where a temp `config_root` had no `kaivix/` directory at all.

### Decision

`_get_default_sections()` now raises a `BusinessConfigError` with a clear message when Kaivix's own reference directory can't supply a usable default for a given section, instead of letting a raw Pydantic exception escape.

### Reasoning

Consistent with the project's existing rule (Business_Config.md §6): malformed or unusable config should fail loudly with an attributed message, never silently or with an opaque stack trace. Kaivix's own config directory is the fallback backing every other business — if it's ever incomplete, that's a configuration problem worth a clear error, not a confusing crash three layers removed from the actual cause.

### Consequences

**Benefits**
- Clear, actionable error instead of an opaque Pydantic stack trace
- No change to the fallback *policy* itself — only to how failure is reported

**Trade-offs**
- None identified.

---

# Decision #014

## Should a Business With No persona.yaml Really Inherit Bray's Identity?

**Date**

2026-07-26

**Status**

Accepted — resolved: persona.yaml is now required per business (option b)

### Context

Per the original BusinessConfig spec, every optional section (including `persona`) falls back to Kaivix's own values when a business doesn't supply its own file. This makes sense for `qualification.yaml` (a generic starter field list is reasonably business-agnostic). It does not obviously make sense for `persona.yaml` — a business with no persona file would silently get "You are Bray, a friendly and confident sales agent for Kaivix Labs," which is a real, wrong identity, not a placeholder.

### Decision

Option (b): `persona.yaml` is now required per business, exactly like `identity.yaml` already was. `BusinessConfigRepository` no longer treats `persona.yaml` as optional — it fails loudly with a `BusinessConfigError` ("persona.yaml is required and was not found for business_id=...") if a business doesn't supply its own, instead of silently borrowing Kaivix's persona.

### Reasoning

Deliberately left open at #013's investigation time rather than fixed opportunistically — this was a product decision (how strict should onboarding be?) more than a code-correctness one. Option (b) was chosen over (a) and (c) because a business with no persona should never be able to run in production as "Bray from Kaivix Labs"; failing loudly at onboarding time is safer than either accepting the risk (a) or inventing a generic default persona no one asked for (c).

### Consequences

**Benefits**
- A business can no longer silently run under Kaivix's own persona
- Consistent with how `identity.yaml` is already handled — one rule for "required, business-specific" files instead of two
- Onboarding failures now surface immediately and loudly, at config-load time, not as a mystery in production behavior

**Trade-offs**
- Onboarding a new business now requires writing `persona.yaml` before the business can be loaded at all (previously optional) — a small process cost.
- The prior `_get_default_sections()` fallback-crash fix (Decision #013) no longer applies to `persona.yaml` specifically, since there is no fallback path left for it to crash on; #013 still applies to the remaining optional sections (`qualification`, `knowledge`, `tools`, `channels`, `guardrails`, `providers`).

### Implementation

`core_ai/business_config.py`: removed `"persona.yaml"` from `_OPTIONAL_FILES`; added `BusinessConfigRepository._load_persona()`, mirroring `_load_identity()`; `load()` now calls both directly and passes both `identity` and `persona` into `BusinessConfig(**kwargs)` outside the optional-files loop; `_get_default_sections()` no longer builds a persona default. Kaivix's own `config/businesses/kaivix/persona.yaml` already existed, so Kaivix's own `load()` behavior is unchanged.

---

# Decision #015

## ConversationMemory Persistence: SQLite, Tenant-Scoped From Day One

**Date**

2026-07-26

**Status**

Accepted

### Context

ConversationMemory was in-memory only (a defaultdict), losing all active conversations on any process restart. Its own docstring already anticipated a swap to a persistent backend.

### Decision

Replaced with a SQLite-backed store (memory/conversation_memory.db), following the same BaseCRM/BaseLongTermMemoryStore abstraction pattern already used elsewhere. Unlike CRM and LongTermMemory, this was built with a business_id column from the start, not retrofitted later.

### Reasoning

SQLite matches every other storage layer in this project and requires no new infrastructure (no Redis service to operate). Building it tenant-scoped immediately applies the direct lesson from Decisions in the earlier backlog, where CRM and LongTermMemory both needed correctness-bug fixes after the fact.

### Consequences

**Benefits:** conversations survive restarts; consistent storage pattern; no retrofit needed later.

**Trade-offs:** none identified.

---

# Decision #016

## Pricing Numbers Removed Structurally, Not Just by Instruction

**Date**

2026-07-26

**Status**

Accepted

### Context

A real production bug: Bray could quote exact prices to unqualified visitors. The root cause was structural — real dollar figures lived in the same retrievable documents (knowledge/kaivix/pricing.md AND knowledge/kaivix/objections.md, the latter found independently mid-fix) that Bray's own instructions told it to quote directly from.

### Decision

Real numbers were removed entirely from every document KnowledgeBase can retrieve, and moved to docs/Internal_Pricing_Reference.md, a path structurally outside KnowledgeBase's glob scope. PromptBuilder's ENGINE_RULES rule 7 was reworded to be business-agnostic pricing-policy guidance instead of "give it directly."

### Reasoning

An LLM instructed "don't quote this number" while the number sits directly in its context is an unreliable safeguard. Removing the number from anything retrievable is a deterministic guarantee, consistent with this project's established preference for Python-enforced correctness over prompt-only instructions.

### Consequences

**Benefits:** structurally impossible for Bray to leak Kaivix's real pricing figures, verified by a dedicated test scanning all loaded documents for dollar patterns.

**Trade-offs:** none identified.

---

# Decision #017

## Conversation-Quality Eval Suite Kept Separate From CI Unit Tests

**Date**

2026-07-26

**Status**

Accepted

### Context

All existing tests (65+ at the time) prove architectural correctness deterministically. None prove Bray actually behaves well in real conversation — exactly the kind of gap that let the pricing leak ship undetected.

### Decision

Built evals/run_conversation_evals.py as a standalone, manually-run script — not part of python -m unittest discover -s tests. It calls the real Groq LLM, runs each scripted scenario 3 times to reduce flakiness, and uses pattern-based checks (no_price_leak, no_bot_admission, no_crash) rather than exact-match assertions.

### Reasoning

Non-deterministic, API-costing, network-dependent checks would make the regular test suite flaky and slow if mixed in. This is a pre-deploy quality gate, run deliberately before shipping prompt/knowledge/persona changes, not on every commit.

### Consequences

**Benefits:** a real safety net for conversational regressions that architecture tests can't catch; reuses the pricing allowlist logic directly from the test suite so the two can't drift apart.

**Trade-offs:** requires manual/deliberate running; not enforced automatically in CI.

---

# Decision #018

## Calendar OAuth: Tenant-Scoped Token Storage, Shared App-Level Credentials

**Date**

2026-07-26

**Status**

Accepted

### Context

Google Calendar integration needed per-business calendar connections. There is currently one shared Google Cloud OAuth application (one Client ID/Secret) for the whole platform, not a separate OAuth app per business.

### Decision

scheduling/calendar_token_store.py stores each business's resulting token/refresh_token/scopes, keyed by business_id as primary key (one connection per business). GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are read from environment variables at the provider level, NOT stored per-business-row.

### Reasoning

The OAuth application itself is shared platform infrastructure; only the resulting per-business authorization (which calendar, whose consent) is genuinely tenant-specific data. Storing client credentials redundantly per row would add no correctness benefit and more secret-handling surface area.

### Consequences

**Benefits:** clean separation between platform-level app credentials and business-level authorization; matches how CRM/LTM already separate "the database" from "the tenant's rows."

**Trade-offs:** if a future business needs its own entirely separate Google Cloud OAuth app (e.g. their own branding on the consent screen), the schema would need extending — not needed today.

---

# Decision #019

## Booking Confirmation Uses Numbered-Slot Matching, Not Fuzzy Date/Time Parsing

**Date**

2026-07-26

**Status**

Accepted

### Context

Resolving which calendar slot a visitor picked, from free-text conversation, is the first feature in this project with a real, external, hard-to-undo side effect (an actual calendar event with a real attendee).

### Decision

Offered slots are numbered (1, 2, 3) when presented. scheduling/slot_matcher.py matches ONLY a standalone digit at a valid position or an ordinal word (first/second/third) — explicitly excluding multi-digit numbers and time-shaped tokens (e.g. "2pm") to avoid coincidental false positives. No match found means no booking attempt — never a guess.

### Reasoning

Fuzzy natural-language date/time matching is inherently ambiguous and this is the one place in the system where a wrong guess creates a real external artifact, not just a wrong sentence. Strict, narrow matching with a fail-safe "ask again" default was chosen deliberately over convenience.

### Consequences

**Benefits:** booking can only occur on an unambiguous visitor confirmation; a coincidental "2pm works" reply right after offering slot #2 is correctly NOT treated as selecting option 2 (caught and fixed during implementation).

**Trade-offs:** visitors must reply with a number/ordinal, not natural phrasing like "the Tuesday one" — a real, deliberate UX constraint traded for booking safety.

---

# Decision #020

## PlanningEngine Stays I/O-Free; Calendar Operations Live in ConversationEngine

**Date**

2026-07-26

**Status**

Accepted

### Context

PlanningEngine already produces a deterministic "drive_to_booking" signal. The question was whether calendar API calls (free/busy lookup, event creation) should live inside PlanningEngine itself.

### Decision

PlanningEngine was not modified at all (confirmed via empty git diff across every scheduling milestone). All calendar I/O lives in new ConversationEngine orchestration methods (_maybe_attach_availability, _maybe_resolve_booking), mirroring the existing _sync_lead_to_crm pattern — wrapped in try/except, logged on failure, never interrupting the conversation.

### Reasoning

PlanningEngine's own docstring is explicit that it only sequences signals already computed elsewhere and never touches external systems. Respecting that boundary kept this entire feature additive to ConversationEngine without touching the one component most central to the platform's deterministic-decision philosophy.

### Consequences

**Benefits:** PlanningEngine's test suite needed zero changes across the entire scheduling feature; the boundary between "decide" and "act" stayed clean.

**Trade-offs:** none identified.

---



\# Future Decisions



Every important architectural, product, or engineering decision should be recorded here before implementation.



Examples



\- Multi-tenant architecture

\- Plugin system

\- Vector database adoption

\- Calendar provider abstraction

\- CRM abstraction

\- Voice AI architecture

\- Analytics architecture

\- Deployment strategy

\- Security architecture



\---



\# Rules



1\. Never delete historical decisions.



2\. If a decision changes:



\- Mark the original as Superseded.

\- Add a new decision.



3\. Record the reasoning, not only the outcome.



4\. Significant architectural discussions should result in a documented decision.



5\. This document is the historical record of Kaivix Core.

