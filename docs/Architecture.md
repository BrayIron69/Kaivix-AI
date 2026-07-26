\# Kaivix Core Architecture



\*\*Version:\*\* 1.0

\*\*Status:\*\* Active

\*\*Last Updated:\*\* 2026-07-25



\---



\# Purpose



This document defines the architecture of Kaivix Core.



Kaivix Core is a reusable AI Employee platform that allows different businesses to deploy intelligent AI Employees through configuration rather than rewriting application logic.



This document is the single source of truth for how the system is designed.



\---



\# Core Design Principles



\## 1. Python Owns Business Logic



Business logic must always be implemented in Python.



The LLM is responsible only for generating natural language.



The LLM must never make deterministic business decisions.



\---



\## 2. Configuration Over Customization



Every customer should be onboarded by configuration.



Business-specific behavior should be stored inside BusinessConfig rather than modifying the engine.



\---



\## 3. Modular Architecture



Every major responsibility belongs to a dedicated component.



Components should have a single responsibility.



\---



\## 4. Long-Term Maintainability



The architecture should prioritize:



\- readability

\- scalability

\- maintainability

\- testing

\- modularity



over writing the fewest lines of code.



\---



\# High-Level Architecture



```

&#x20;               User

&#x20;                 │

&#x20;                 ▼

&#x20;       Conversation Engine

&#x20;                 │

&#x20;     ┌───────────┼────────────┐

&#x20;     ▼           ▼            ▼

&#x20;Intent      Goal Engine   Entity Extraction

&#x20;Detection

&#x20;     │           │            │

&#x20;     └───────────┼────────────┘

&#x20;                 ▼

&#x20;         Planning Engine

&#x20;                 │

&#x20;     ┌───────────┼────────────┐

&#x20;     ▼           ▼            ▼

&#x20;Memory      Knowledge      BusinessConfig

&#x20;                 │

&#x20;                 ▼

&#x20;         Prompt Builder

&#x20;                 │

&#x20;                 ▼

&#x20;               LLM

&#x20;                 │

&#x20;                 ▼

&#x20;     Natural Language Response

&#x20;                 │

&#x20;                 ▼

&#x20;     CRM / API / Scheduling

```



\---



\# Major Components



\## Conversation Engine



Responsibilities



\- manages conversation flow

\- coordinates all system components

\- determines conversation stage

\- orchestrates processing pipeline



\---



\## Memory System



Responsibilities



\- working memory

\- conversation memory

\- summaries

\- long-term memory

\- customer state



Purpose



Maintain conversation context across sessions.



\---



\## Planning Engine



Responsibilities



\- determine next action

\- create execution plans

\- coordinate goals

\- support deterministic workflows



\---



\## Goal Engine



Responsibilities



\- determine conversation objective

\- prioritize goals

\- update active goals



\---



\## Intent Detector



Responsibilities



\- classify user intent

\- assist routing

\- support planning



\---



\## Qualification Engine



Responsibilities



\- qualify leads

\- calculate qualification progress

\- identify missing information



\---



\## Entity Extractor



Responsibilities



Extract structured business information including:



\- name

\- email

\- phone

\- company

\- budget

\- timeline

\- pain points

\- custom business fields



\---



\## Knowledge Base



Responsibilities



\- retrieve business information

\- answer customer questions

\- provide factual grounding



Knowledge should always come from configured business data.



\---



\## Prompt Builder



Responsibilities



Construct prompts using:



\- conversation history

\- memory

\- business knowledge

\- planning output

\- business configuration



Prompt Builder does not contain business logic.



\---



\## LLM Client



Responsibilities



\- communicate with the language model

\- generate responses

\- return natural language



The LLM should never contain application logic.



\---



\## CRM



Responsibilities



\- store leads

\- update lead records

\- retrieve customer information

\- support future integrations



Current implementation:



\- SQLite



Future:



\- HubSpot

\- Salesforce

\- Zoho

\- Custom CRM integrations



\---



\## API Layer



Responsibilities



Expose backend functionality.



Current technology:



\- FastAPI



\---



\# Memory Architecture



```

MemoryManager

│

├── WorkingMemory

├── ConversationMemory

├── ConversationSummary

├── LongTermMemory

└── CustomerState

```



MemoryManager is the single entry point for all memory operations.



\---



\# Conversation Flow



1\. User sends message.

2\. Conversation Engine receives message.

3\. Memory is updated.

4\. Intent is detected.

5\. Goal is determined.

6\. Entities are extracted.

7\. Planning Engine creates execution plan.

8\. Knowledge is retrieved.

9\. Prompt Builder constructs prompt.

10\. LLM generates natural language.

11\. Business actions are executed if required.

12\. Response returned to user.

13\. Memory updated.



\---



\# Configuration System



Future versions will support BusinessConfig.



BusinessConfig will define:



\- company information

\- products

\- services

\- branding

\- qualification fields

\- conversation stages

\- scheduling settings

\- integrations

\- knowledge sources



BusinessConfig replaces hardcoded business behavior.



\---



\# Current Technology Stack



Backend



\- Python

\- FastAPI



Database



\- SQLite



Version Control



\- Git

\- GitHub



Deployment



\- Vercel (Frontend)

\- Backend deployment TBD



LLM Providers



\- Groq

\- Future provider abstraction planned



\---



\# Future Architecture



Planned additions



\- BusinessConfig

\- Appointment Scheduling

\- Google Calendar Integration

\- Email Notifications

\- Multi-Tenant Support

\- Analytics

\- Plugin System

\- Voice AI

\- WhatsApp

\- CRM Integrations

\- Enterprise Features



\---



\# Architecture Rules



1\. Python owns business logic.

2\. LLM generates language only.

3\. Configuration over customization.

4\. Components should have a single responsibility.

5\. Prefer deterministic behavior.

6\. Avoid duplicated logic.

7\. Minimize coupling between modules.

8\. All new features should fit the existing architecture.



\---



\# Document Ownership



This document is updated only when the architecture changes.



Feature implementation should reference this document before making structural changes.

