\# Kaivix Core — BusinessConfig Specification v0.1



Status: DRAFT — for review before any implementation begins.

Owner: Architecture chat (this project).

Consumers of this doc: Claude Code (implementation), future contributors.



\---



\## 1. Purpose



BusinessConfig is the single customization boundary of Kaivix Core. It is the

\*only\* mechanism by which a business's identity, rules, and preferences enter

the engine. No engine component may hardcode a business fact (name, persona,

tone, required fields, knowledge path, tools, channels, guardrails) — those

facts live in BusinessConfig and are resolved by `business\_id`.



This spec defines the file layout, per-file schemas, the Python validation

model, loading/caching behavior, fallback behavior, and exactly which engine

components consume which section. It does not implement anything.



\---



\## 2. What BusinessConfig is NOT



\- It is not a place for orchestration logic, pipeline order, or decision

&#x20; algorithms. Those stay in Core (ConversationEngine, PlanningEngine,

&#x20; QualificationEngine's \*algorithm\*, GoalEngine, etc.).

\- It is not a runtime-mutable object. It is loaded once per business, cached,

&#x20; and treated as read-only for the lifetime of the cache entry.

\- It is not a full app config (no secrets, no infra settings, no API keys —

&#x20; those stay in environment variables / a secrets manager, never in

&#x20; business-authored YAML).



\---



\## 3. File layout



One directory per business, multiple files inside it. Cleaner diffs when a

business only changes one thing (e.g. a support agent doesn't need to touch

qualification.yaml), and it scales cleanly as more sections get added later.



```

config/

&#x20; businesses/

&#x20;   kaivix/                      <- business\_id

&#x20;     identity.yaml

&#x20;     persona.yaml

&#x20;     qualification.yaml

&#x20;     knowledge.yaml

&#x20;     tools.yaml

&#x20;     channels.yaml

&#x20;     guardrails.yaml

&#x20;     providers.yaml

&#x20;   acme-dental/

&#x20;     identity.yaml

&#x20;     persona.yaml

&#x20;     qualification.yaml

&#x20;     ...

```



`business\_id` is the directory name. It is an opaque scoping key — never a

display name, never used for matching or lookup logic beyond "give me this

folder." (Matches the existing rule: never `client\_name` in code or storage.)



\---



\## 4. Per-file schemas



\### 4.1 `identity.yaml`

```yaml

business\_id: kaivix

business\_name: "Kaivix Labs"

industry: "AI Automation Agency"

description: "Builds custom AI employees for businesses."

contact:

&#x20; email: brayiron@kaivixlab.com

&#x20; phone: null

&#x20; whatsapp: "+923424287544"

timezone: "Asia/Karachi"

locale: "en-US"

```



\### 4.2 `persona.yaml`

```yaml

ai\_name: "Bray"

role: "sales agent"

tone: "friendly, confident, conversational"

formality: "casual-professional"

signature\_phrases: \[]

booking\_link: "https://calendly.com/brayiron-kaivixlab/30min"

identity\_statement: >

&#x20; You are Bray, a friendly and confident sales agent for Kaivix Labs.

&#x20; You are NOT a bot. You are a real human sales rep having a genuine

&#x20; business conversation.

objectives:

&#x20; - "Understand what the visitor's business needs"

&#x20; - "Qualify them as a potential client"

&#x20; - "Handle objections confidently without being pushy"

&#x20; - "Guide them toward booking a free 30-minute demo call"

```

Note: `identity\_statement` + `objectives` replace `PromptBuilder.AGENT\_IDENTITY`

verbatim for the Kaivix default — this is a lossless extraction, not a rewrite.



\### 4.3 `qualification.yaml`

```yaml

\# Ordered list. Order = priority order PlanningEngine already respects.

fields:

&#x20; - id: name

&#x20;   prompt\_hint: "Ask for their name."

&#x20;   required: true

&#x20; - id: email

&#x20;   prompt\_hint: "Ask for an email address so we can follow up."

&#x20;   required: true

&#x20; - id: company

&#x20;   prompt\_hint: "Ask what company or business they represent."

&#x20;   required: true

&#x20; - id: budget

&#x20;   prompt\_hint: "Ask about their budget for this kind of solution."

&#x20;   required: true

&#x20; - id: timeline

&#x20;   prompt\_hint: "Ask about their timeline for getting started."

&#x20;   required: true

```

This is a lossless extraction of `QualificationEngine.required\_fields` +

`PlanningEngine.\_FIELD\_QUESTIONS`. A business with no `qualification.yaml`

inherits exactly this file as the default (see §6, Fallback Behavior).



\### 4.4 `knowledge.yaml`

```yaml

namespace: kaivix          # scoped folder/table key, not a filesystem path

source\_type: file          # V1 only supports "file"; interface allows more later

```



\### 4.5 `tools.yaml`

```yaml

enabled\_tools: \[]          # V1: empty for all businesses. Interface exists,

&#x20;                           # nothing implemented yet (no tools built in V1).

```



\### 4.6 `channels.yaml`

```yaml

enabled\_channels:

&#x20; - web\_chat

\# whatsapp / email / sms listed here once each adapter exists;

\# ConversationEngine branches on channel only for output formatting.

```



\### 4.7 `guardrails.yaml`

```yaml

disclaimers: \[]

forbidden\_topics: \[]

escalation\_triggers: \[]

```

V1: present, structurally valid, empty by default. No business currently

needs these populated, but the shape must exist so PromptBuilder's

config-driven block (backlog item #2) has a stable place to read from.



\### 4.8 `providers.yaml`

```yaml

\# V1: this file is VALIDATED but not yet READ for provider selection.

\# Every business is hardcoded to these values in code. The file exists

\# now so the schema is stable before provider-switching is built later.

llm\_provider: groq

crm\_provider: sqlite

calendar\_provider: none      # not built yet

knowledge\_provider: file

```



\---



\## 5. Python validation model (outline, not implementation)



One Pydantic model per file, composed into a single `BusinessConfig`:



```

BusinessIdentity      <- identity.yaml

BusinessPersona       <- persona.yaml

QualificationSchema   <- qualification.yaml   (list\[QualificationField])

KnowledgeConfig       <- knowledge.yaml

ToolsConfig           <- tools.yaml

ChannelsConfig        <- channels.yaml

GuardrailsConfig      <- guardrails.yaml

ProvidersConfig       <- providers.yaml



BusinessConfig:

&#x20;   identity: BusinessIdentity

&#x20;   persona: BusinessPersona

&#x20;   qualification: QualificationSchema

&#x20;   knowledge: KnowledgeConfig

&#x20;   tools: ToolsConfig

&#x20;   channels: ChannelsConfig

&#x20;   guardrails: GuardrailsConfig

&#x20;   providers: ProvidersConfig

```



A `BusinessConfigRepository` is responsible for:

\- reading the six-to-eight YAML files for a given `business\_id`

\- validating each into its sub-model (raises a clear, file-attributed error

&#x20; on malformed YAML — malformed config should fail loudly; \*missing optional

&#x20; content\* should fall back, per §6)

\- assembling the composed `BusinessConfig`

\- caching it (loaded once, reused for the life of the process or until

&#x20; explicitly invalidated — no per-turn disk reads)



This repository is the seam `ConversationEngine` will take a dependency on

(backlog item #6). It does not exist yet.



\---



\## 6. Fallback behavior



\- \*\*Missing optional file or field\*\* (e.g. no `qualification.yaml` at all,

&#x20; or `guardrails.yaml` present but empty) → the sub-model falls back to

&#x20; Kaivix's current default, which is defined once as a constant default

&#x20; config, not re-derived per caller. A business with zero config files still

&#x20; gets a fully functional AI employee running Kaivix's own defaults.

\- \*\*Malformed file\*\* (invalid YAML, wrong types, unknown required field

&#x20; missing) → fail loudly at load time with a file-and-field-attributed error.

&#x20; This is a config authoring bug, not a "business hasn't customized this yet"

&#x20; case, and should never silently degrade.

\- \*\*`identity.yaml` is the one file that is never optional\*\* — a business

&#x20; must exist with a name/id before anything else resolves. Everything else

&#x20; degrades gracefully; identity does not.



\---



\## 7. Component consumption map



| Config section     | Consumed by                                    |

|---------------------|------------------------------------------------|

| identity            | PromptBuilder, CRM/LTM records, logging        |

| persona              | PromptBuilder (replaces AGENT\_IDENTITY)        |

| qualification        | QualificationEngine, PlanningEngine field hints|

| knowledge             | KnowledgeBase (namespace scoping)              |

| tools                | PlanningEngine (future — V1 tools list is empty)|

| channels              | ConversationEngine (output formatting only)    |

| guardrails            | PromptBuilder (config-driven block)            |

| providers             | Provider factories (interface only in V1)      |



Nothing in this table changes \*how\* a component reasons — only \*what data\*

it reasons over. This is the one-sentence platform philosophy already

established: only the data changes, never the reasoning.



\---



\## 8. Migration path for Kaivix itself



Kaivix Labs becomes `business\_id: kaivix`, with its config files populated

with exactly the values currently hardcoded in `PromptBuilder` and

`QualificationEngine` (see §4.2 and §4.3 — both are lossless extractions,

not rewrites). This means the very first BusinessConfig ever loaded is

Kaivix's own, and it must produce byte-for-byte the same system prompt

behavior as today. That equivalence is the acceptance test for backlog

item #2 (PromptBuilder split).



\---



\## 9. Explicitly deferred to later phases



\- Provider selection actually switching behavior (schema exists now, wiring

&#x20; later)

\- Tools schema populated with real tools (nothing is built yet)

\- Multi-business runtime serving (V1 is one deployment per customer per the

&#x20; handoff doc — BusinessConfig existing does not imply multi-tenant serving

&#x20; yet)

\- Hot-reloading config without a process restart

\- A YAML editing UI — V1 is hand-authored files



\---



\## 10. Acceptance criteria for this spec being "done"



\- \[ ] You've reviewed and approved/amended this doc

\- \[ ] `kaivix/` config files drafted matching current hardcoded values exactly

\- \[ ] Confirms zero behavior change when engine eventually reads them (backlog

&#x20;     items #2 and #3 are refactors, not feature changes)

