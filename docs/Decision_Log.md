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



# Decision #021

## LLM Provider Failures Become a 503 at the API Boundary, Not an Unhandled 500

**Date**

2026-07-30

**Status**

Accepted

### Context

`utils/llm.py` called Groq with no exception handling, and nothing above it caught anything either. When the Groq quota was exhausted the call raised, and the catch-all handler in `api/handlers/exceptions.py` flattened it into `HTTP 500 {"message": "Internal Server Error"}`. This was observed live: `/chat` returned 500 to every visitor while `/health` stayed 200, because `/health` never touches the LLM — so nothing alerted.

### Decision

Three parts:

1. `utils/llm.py` catches `GroqError` (the single base class for every Groq failure) and re-raises `utils.exceptions.LLMUnavailableError`, a provider-agnostic exception.
2. `api/handlers/exceptions.py` registers a handler for `LLMUnavailableError` returning **503** with `Retry-After: 30` and a message naming a contact channel that does not depend on the AI.
3. The failure log records the exception **class** and HTTP status, never `str(error)`.

### Reasoning

500 says "we have a bug"; 503 says "temporarily unavailable, retry" — the latter is true and actionable, and monitoring can distinguish it. Translating at the LLM boundary means nothing above `utils/llm.py` imports a vendor SDK to handle an outage, which is what makes Decision #022's registry possible.

Logging the class rather than the message is deliberate: an `AuthenticationError` message can quote part of the API key. The class plus status (`RateLimitError`/429 vs `AuthenticationError`/401) is enough to diagnose and cannot leak.

The translation is scoped to `GroqError` specifically, **not** a blanket `except Exception`. A genuine defect must keep surfacing as a defect rather than being dressed up as a soft outage and hidden from monitoring.

### Consequences

**Benefits**
- An outage costs a slow reply, not a lead
- The failure is visible in logs and distinguishable by status code
- Secrets cannot reach the log on the failure path

**Trade-offs**
- Does not retry or fail over to a second provider; it degrades and tells the visitor. Failover needs a second provider to exist first.

---

# Decision #022

## Provider Selection Goes Through a Registry; Knowledge Is Deliberately Excluded

**Date**

2026-07-30

**Status**

Accepted

### Context

`config/businesses/<id>/providers.yaml` carried `llm_provider`, `crm_provider`, `calendar_provider` and `knowledge_provider`, and `BusinessConfig` validated all four — but nothing ever read them. `ConversationEngine` did `self.llm = LLM()` and `self.lead_service = LeadService()`, and `LeadService.__init__` hardcoded `SQLiteCRM()`. Every business got Groq + SQLite regardless of what its config said.

### Decision

`llm_provider` and `crm_provider` now resolve through name-to-class registries (`utils/llm_provider.py`, `crm/registry.py`). `ConversationEngine.__init__` reads both from `business_config.providers`. An unrecognised name raises at construction.

`knowledge_provider` is **not** wired up. `calendar_provider` remains as-is.

`BaseCRM` was expanded from one abstract method to the five `LeadService` actually calls.

### Reasoning

The LLM had exactly one call site and one method (`generate`), so the seam is one method wide — a second provider implements `generate`, registers itself, and `ConversationEngine` is never edited.

CRM already had a `BaseCRM` ABC and a single hardcoding point, so it supported the same pattern cleanly. But `BaseCRM` declared only `save_lead` while `LeadService` calls five methods — a second implementation could satisfy the ABC and still crash the first time anything read a lead back. Completing the interface was a precondition, not a nice-to-have. `crm/hubspot.py` and `crm/gohighlevel.py` exist but are empty files, so `sqlite` remains the only registered CRM.

Knowledge was excluded because the existing code does not cleanly support it yet, on three counts: there is no ABC and no second implementation, so the abstraction would be invented rather than wired up; `_load_documents` hardcodes filesystem globbing and consumers read `knowledge.documents` directly, so the seam is wider than one method; and **two config fields already compete for the same decision** — `knowledge.source_type` in `knowledge.yaml` and `providers.knowledge_provider` — with nothing specifying which is authoritative. Picking one silently would bake in a guess. That ambiguity should be resolved before the abstraction is built.

Unknown names fail loudly rather than falling back to the default, because silently serving a different provider than the one recorded in config is worse than refusing to start.

### Consequences

**Benefits**
- `providers.yaml` means something for two of its four fields
- A second LLM or CRM provider requires no change to `ConversationEngine`
- "Implements `BaseCRM`" now means "usable by `LeadService`"

**Trade-offs**
- `knowledge_provider` and `calendar_provider` are still decorative; the duplicate-knowledge-config question is deferred, not answered
- Provider errors now surface at engine construction rather than at first use

---

# Decision #023

## Multi-Business Serving Lives Entirely in ChatService; Decision #011 Stands

**Date**

2026-07-30

**Status**

Accepted

### Context

Decision #011 bound `business_id` once at `ConversationEngine.__init__` and recorded that "real multi-tenant serving (one process handling many businesses) is an explicitly deferred future phase", predicting that `process_message` would need its own `business_id` parameter when that phase arrived.

That phase has now been implemented, minimally, against a synthetic second business.

### Decision

`ChatService` holds `dict[business_id, ConversationEngine]`, constructed lazily on first request per business and reused after. `POST /chat/{business_id}` was added. The plain `POST /chat` endpoint is unchanged and continues to serve `DEFAULT_BUSINESS_ID`.

No engine-level file was modified.

### Reasoning

Decision #011's prediction turned out to be wrong in a useful way: `process_message` did **not** need a `business_id` parameter. Because every component below `ConversationEngine` was already `business_id`-scoped, multi-business serving was achieved by holding *several* engines rather than by changing how any one engine binds its business. #011's actual decision — bind once at construction, don't thread it through `process_message` — is therefore validated, not superseded, and remains in force. Only its "will need to be revisited" caveat is retired.

Engines are built lazily because a business nobody has messaged should cost nothing, and loading every configured business's knowledge base at startup would make process boot scale with the customer list.

An unknown `business_id` in the URL returns 404, not 500: a typo'd path is a client error, and `BusinessConfigError` would otherwise reach the catch-all handler.

The synthetic test business is an in-test `SimpleNamespace` plus a temp directory. No `config/businesses/test-business-b/` was created — no real second business exists, and committing config for a fake one would leave misleading artifacts.

### Consequences

**Benefits**
- One process can serve many businesses; the capability is proven, not assumed
- The live widget needs zero changes — it posts to plain `/chat`, byte-identical behaviour
- Confirms the #011-era scoping work was genuinely complete

**Trade-offs**
- Config errors now surface on a business's first request rather than at import. This also means one business's broken config can no longer stop the process serving everyone else — a deliberate exchange of fail-fast for blast-radius containment.
- Engines are cached for process lifetime with no eviction. Fine for a handful of businesses; a real tenant list would want a bounded cache.
- Nothing authenticates `business_id`. Any caller can address any configured business. Acceptable while every configured business is our own; a prerequisite before third parties can reach this endpoint. **(Closed by Decision #024.)**

---

# Decision #024

## Per-Business API Keys Authenticate `/chat/{business_id}`; Plain `/chat` Stays Open By Design

**Date**

2026-07-30

**Status**

Accepted

### Context

Decision #023 shipped `POST /chat/{business_id}` and recorded, as an explicit trade-off, that "nothing authenticates `business_id`. Any caller can address any configured business." That was acceptable only while every configured business was our own. It is the single gap standing between the current code and a third party's `business_id` existing in `config/businesses/`.

The exposure was not merely "an unauthorized party can chat". Because the route resolves config and constructs a `ConversationEngine` for whatever id is in the path, an anonymous caller could also spend our LLM budget under any tenant's persona, write leads into that tenant's CRM rows, and enumerate which `business_id`s exist by reading 404-vs-200.

### Decision

Four parts:

1. `auth/api_key_store.py` — a tenant-scoped SQLite store, `business_id` as PRIMARY KEY, one active key per business. Only a **SHA-256 hash** of the key is stored; verification hashes the presented value and compares with `secrets.compare_digest`.
2. `POST /chat/{business_id}` requires a valid `X-API-Key` **for that specific `business_id`**, enforced as a FastAPI dependency so it completes before the handler body.
3. `POST /chat` (no `business_id`) remains completely unauthenticated and byte-identical.
4. `scripts/issue_api_key.py <business_id>` issues or rotates a key, printing the plaintext once. A key has been issued for `kaivix`.

Every rejection is the same 401: missing header, wrong key, another business's key, or a business with no key provisioned.

### Reasoning

**Why hashed at rest, and why SHA-256 rather than bcrypt/argon2.** A stolen database read must not yield a usable credential — the same reason `api/routers/admin.py` never stores a comparable secret and compares in constant time. But a slow KDF is the wrong tool here: bcrypt and argon2 exist to make brute force expensive against *low-entropy human-chosen passwords*. These keys are 32 bytes of `os.urandom`, so there is no dictionary to run, and a deliberately slow hash would instead tax every `/chat` request on the hot path. Constant-time comparison is the property that matters, and it is used.

**Why the key is scoped to `business_id`, not global.** A single shared secret would authenticate the *caller* and not the *business*, which is the failure mode that looks like it works: tenant A's valid key would let tenant A hold conversations as tenant B, write into B's CRM, and read B's knowledge base. The store looks up by `business_id` before any comparison, so a key is valid for exactly one business. Four tests assert this directly, including the realistic case of our own production key being tried against another business.

**Why auth runs before business resolution.** Two reasons. An unauthorized request now costs nothing — no config load, no knowledge-base read, no engine construction — which removes an unauthenticated compute-amplification path. And an unknown `business_id` returns the same 401 as a known one, so the endpoint is no longer an oracle for which businesses exist. This does change #023's observable behaviour: an *unauthenticated* request for an unknown id now gets 401 rather than 404. #023's 404-not-500 handling is untouched and still reachable for an authorized caller whose own config is broken, which is who that status was always meant for; both paths are tested.

**Why an unprovisioned business is closed rather than open.** Treating "no key on record" as "no key required" is the classic authentication bypass, and it would mean adding a business to `config/businesses/` silently published an open endpoint. Unconfigured means denied, matching admin auth's "no default credentials" stance.

**Why plain `/chat` must stay unauthenticated.** This is not a concession, it is the correct design. `chat_widget.html` is client-side JavaScript on the public marketing site, served to anonymous visitors. Any key shipped to it would be readable in view-source by anyone, so authenticating that route would add no security while guaranteeing an outage the moment it was enforced. The public widget's threat model is abuse control (the message-length cap from #023, rate limiting later), not authentication. A byte-identical-output test runs against this route with the auth layer installed, so the guarantee is checked rather than asserted.

**Why a script rather than an admin-dashboard screen.** No real second business exists. A management UI would be scaffolding for a problem that has not arrived, and a browser-reachable credential-minting button is a larger attack surface than a command requiring shell access to the host. The script refuses an unrecognised `business_id` by default, because a key issued for a typo'd id is silently useless.

### Consequences

**Benefits**
- A third party's `business_id` can now exist in `config/businesses/` without publishing an open endpoint for it
- A leaked key compromises exactly one business, and rotation is one command
- A database read yields no usable credential
- Unauthenticated callers can no longer enumerate `business_id`s or spend LLM budget

**Trade-offs**
- One key per business, so there is no way to run two valid keys during a rotation window; rotation is a hard cutover. Fine while keys are handed over by hand, and a second row per business is the obvious extension when it isn't.
- No expiry, no scopes, no per-key rate limiting, and no usage attribution beyond "this business's key was accepted".
- `auth/api_keys.db` is another SQLite file to back up alongside `crm/leads.db` and `scheduling/calendar_tokens.db`. Losing it locks every business out until keys are re-issued.
- Plain `/chat` remains an unauthenticated LLM-spending endpoint. That is inherent to a public widget and is bounded by the message-length cap, not by auth; per-IP rate limiting is the real answer and is not built yet.

---

# Decision #025

## `providers.knowledge_provider` Is Authoritative; `knowledge.source_type` Is Removed

**Date**

2026-07-30

**Status**

Accepted

### Context

Two config fields claimed the same decision — which backend reads a business's knowledge:

- `knowledge.source_type` in `config/businesses/<id>/knowledge.yaml`
- `providers.knowledge_provider` in `config/businesses/<id>/providers.yaml`

Both were validated by `BusinessConfig`. Neither was read by anything. Nothing recorded which one would win. Decision #022 named this ambiguity as one of the three reasons knowledge was kept out of the provider registry, and deliberately left it unresolved rather than picking silently.

### Decision

`providers.knowledge_provider` is authoritative. `source_type` is removed from `KnowledgeConfig` and from Kaivix's `knowledge.yaml`.

`knowledge.yaml` keeps `namespace` — *where the corpus lives* — which is a different question from *what reads it* and was never in conflict.

### Reasoning

`providers.yaml` is where backend selection already lives, and the consistency argument is one-sided. It holds all four choices under one `*_provider` naming convention, and two of them (`llm_provider`, `crm_provider`) already resolve through real registries as of Decision #022. Keeping the knowledge backend in a different file, under a different naming convention, would mean the answer to "which backends is this business using?" required reading two files and knowing that one field was special. `source_type` also names a *kind of source* rather than a provider, which is a subtly different concept and part of why the duplication went unnoticed.

Removing the field rather than leaving it as a documented no-op: an inert field that looks live is the thing that created this problem. Pydantic ignores unknown keys, so a `source_type:` line left in any existing `knowledge.yaml` is silently inert — the removal cannot break a config that still carries one. A test asserts exactly that, and another asserts the key has not been reintroduced into Kaivix's own file.

**This changes no behaviour.** Neither field was ever read; `knowledge_provider` is still not wired to a registry, for the reasons #022 gave (no ABC, no second implementation, and `_load_documents` hardcodes filesystem globbing while consumers read `knowledge.documents` directly). What changes is that when that abstraction is built, there is one field to read and no guess to make. Tests assert Kaivix's namespace, loaded document set, and retrieval output are unchanged.

### Consequences

**Benefits**
- One field, in one file, decides each backend
- Decision #022's blocker on wiring up knowledge is cleared; only the code-shape work remains
- A stale `source_type` cannot be mistaken for a live setting

**Trade-offs**
- `knowledge_provider` is still decorative. This resolves which field is authoritative, not the absence of a knowledge abstraction — a reader could mistake "authoritative" for "wired up", which is why both this entry and `providers.yaml` state plainly that it is not.
- Pydantic's ignore-unknown-keys behaviour is what makes the removal safe, and it also means a *typo'd* provider field anywhere in these configs is silently ignored rather than rejected. Pre-existing, not introduced here, but this decision leans on it.

---

# Decision #026

## Logs Mask Direct Identifiers and Keep Qualification Data

**Date**

2026-07-30

**Status**

Accepted

### Context

`Logger.log_lead` wrote a captured lead's name, email, business, budget, timeline and pain point to `logs/app.log` verbatim. That file is plaintext, not access-controlled, copied around with the repo directory, never rotated, and included in any careless directory copy or container image. It amounted to an append-only customer contact list sitting beside the code.

The exposure was latent rather than active: `log_lead` currently has **no callers**, and the one `Lead Captured` line in the existing log has empty name/email fields. So this fixes a loaded gun before it fires rather than cleaning up a breach.

### Decision

`log_lead` now masks direct identifiers and keeps everything else:

| Field | Treatment |
|---|---|
| `email` | First character of the local part + full domain (`n***@ridgeline-dental.com`) |
| `name` | Initials (`N.O.`) |
| `ref` | New: `sha256(business_id + email)[:12]`, a stable non-reversible handle |
| `company`, `budget`, `timeline`, `pain_point` | Kept, length-bounded at 60 characters |

### Reasoning

The line drawn is **direct identifiers are masked; non-identifying qualification data is kept**. That is a rule someone can apply to the next field they add, which "redact PII" on its own is not.

Dropping the whole line, or reducing it to an opaque id, would have been easier and worse: an operator reading the log needs to see that a lead was captured, roughly who, and with what qualification signal, or they will go add the fields back under pressure during an incident.

The domain is deliberately kept while the local part is not. The domain is where the debugging value is — spotting a wave from one company, or a throwaway address — and it does not identify a person by itself.

`ref` exists so removing the identifiers does not remove the ability to correlate. It is seeded with `business_id` as well as email because the CRM allows one address in two businesses as two distinct records (`UNIQUE(business_id, email)`), and a reference that collapsed them would be actively misleading. It is a correlation handle, not a secret: someone holding the log could confirm a *guessed* address by hashing it, since an email is low-entropy input. That is a far weaker capability than reading addresses off disk, and it is why the authoritative record stays in the CRM and admin dashboard.

Truncation of the free-text fields is a length guard, not redaction, and the code says so. It stops one pasted essay from dominating the log; it does not make visitor-written text safe.

### Consequences

**Benefits**
- No customer email address or full name is written to disk in the clear
- The log remains useful for "was this lead captured, and what did it look like"
- Lines about one lead can still be tied together, and to the full CRM record
- The masking helpers are unit-tested independently of the log line

**Trade-offs**
- `pain_point` is visitor-written free text and is still logged. If a visitor types their phone number into it, that reaches the log. Bounding it is not sanitising it; treating every free-text field as unloggable is the stricter position and was not taken, because it would empty the line.
- **`log_user` and `log_ai` in `app.py` still log whole conversation turns verbatim, which is the same class of exposure and a larger one** — a visitor message routinely contains a name and address. `logs/app.log` currently holds four such lines (test domains). Out of scope here and not fixed; `app.py` is the local CLI harness, not the FastAPI serving path, which is why it is lower priority rather than harmless.
- No log rotation and no retention limit, so `app.log` still grows without bound and old entries are never aged out.
- The reference is unsalted, so a guessed address can be confirmed against the log.

---

\---



\# Rules



1\. Never delete historical decisions.



2\. If a decision changes:



\- Mark the original as Superseded.

\- Add a new decision.



3\. Record the reasoning, not only the outcome.



4\. Significant architectural discussions should result in a documented decision.



5\. This document is the historical record of Kaivix Core.

