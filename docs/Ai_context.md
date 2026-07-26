\# AI Context



\*\*Project:\*\* Kaivix Core



\*\*Version:\*\* 1.0



\*\*Status:\*\* Active Development



\*\*Last Updated:\*\* 2026-07-25



\---



\# Purpose



This document is the primary onboarding guide for any AI assistant working on Kaivix Core.



Every new AI session should begin by reading this document before reviewing any code or making recommendations.



The purpose is to quickly establish the project's vision, architecture, engineering philosophy, and current priorities without requiring the AI to infer context from long conversations.



This document summarizes the project.



The remaining documentation provides the detailed reference.



\---



\# What Is Kaivix Core?



Kaivix Core is a reusable AI Employee platform.



This repository is NOT a customer project.



It is the core engine that future customer AI Employees will inherit.



Businesses should be onboarded through configuration rather than rewriting source code.



The long-term objective is to build a configurable enterprise AI Employee platform.



\---



\# Project Mission



Build AI Employees that can:



\- Answer customer questions

\- Understand business knowledge

\- Qualify leads

\- Book appointments

\- Remember conversations

\- Execute deterministic business workflows

\- Integrate with business systems



The platform must be reusable across many industries.



\---



\# Current Development Stage



Current Goal



Complete AI Employee Version 1.



Current Focus



Documentation Foundation



Next Technical Milestone



BusinessConfig



Future Milestones



\- Appointment Scheduling

\- Google Calendar Integration

\- Production Testing

\- AI Employee V1 Release

\- Customer Outreach

\- Kaivix Core Platform

\- Multi-Tenant SaaS



\---



\# Core Philosophy



Python owns business logic.



The language model generates natural language.



Business logic must never exist inside prompts.



Configuration is preferred over hardcoding.



The AI communicates.



Python decides.



Python validates.



Python executes.



\---



\# Architecture Summary



Main Components



\- Conversation Engine

\- Memory Manager

\- Working Memory

\- Conversation Memory

\- Conversation Summary

\- Long-Term Memory

\- Customer State

\- Goal Engine

\- Planning Engine

\- Intent Detector

\- Qualification Engine

\- Entity Extractor

\- Knowledge Base

\- Prompt Builder

\- LLM Client

\- CRM

\- FastAPI API



ConversationEngine coordinates the system.



MemoryManager is the single memory entry point.



Planning occurs before prompt generation.



PromptBuilder prepares context.



The LLM generates responses only.



\---



\# Technology Stack



Backend



\- Python



Framework



\- FastAPI



Database



\- SQLite



Version Control



\- Git

\- GitHub



Frontend



\- Vercel



LLM



\- Groq



Future provider abstraction planned.



\---



\# Current Priorities



Highest Priority



Complete AI Employee Version 1.



Version 1 includes



\- Stable conversations

\- Memory

\- Knowledge

\- Lead qualification

\- CRM

\- BusinessConfig

\- Appointment Scheduling

\- Google Calendar Integration

\- Production Testing



Only after Version 1 is complete should customer outreach begin.



\---



\# Development Workflow



Every milestone follows this sequence.



1\. Business Discussion

2\. Architecture

3\. Planning

4\. Review

5\. Implementation

6\. Testing

7\. Documentation Update



Never skip architecture.



Never jump directly into implementation.



\---



\# Engineering Rules



Always:



\- Prefer maintainability over speed.

\- Keep modules focused.

\- Minimize file changes.

\- Avoid duplicated logic.

\- Preserve backward compatibility where practical.

\- Update documentation after implementation.

\- Test before considering work complete.



Never:



\- Move business logic into prompts.

\- Hardcode customer-specific behavior.

\- Create hidden dependencies.

\- Introduce unnecessary complexity.



\---



\# AI Responsibilities



When working on Kaivix Core:



Challenge assumptions.



Suggest better architecture.



Explain trade-offs.



Think about long-term scalability.



Optimize for enterprise quality rather than rapid development.



Do not agree automatically.



Identify technical debt before implementation.



\---



\# Repository Structure



Major folders



```

app/

agents/

analytics/

api/

crm/

docs/

memory/

services/

utils/

```



Documentation



```

AI\_Context.md

Architecture.md

Development\_Rules.md

Decision\_Log.md

Current\_Status.md

Roadmap.md

Milestone\_Log.md

```



\---



\# Required Reading Order



Before making recommendations, read:



1\. AI\_Context.md

2\. Current\_Status.md

3\. Decision\_Log.md

4\. Architecture.md

5\. Development\_Rules.md



Read additional documents only when necessary.



\---



\# Definition of Success



Kaivix Core succeeds when:



Businesses can deploy AI Employees through configuration rather than software development.



The platform is modular.



The platform is scalable.



The platform is maintainable.



The platform is enterprise-ready.



\---



\# Working Agreement



When assisting this project:



Think before coding.



Review architecture before implementation.



Explain decisions.



Document important changes.



Prefer quality over speed.



Protect the long-term health of the project.



If a proposal conflicts with the documented architecture or engineering principles, explain the conflict before recommending changes.

