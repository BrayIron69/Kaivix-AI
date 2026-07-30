\# Kaivix Core Roadmap



\*\*Version:\*\* 1.0

\*\*Status:\*\* Active

\*\*Last Updated:\*\* 2026-07-31



\---



\# Purpose



This roadmap defines the long-term development strategy for Kaivix Core.



Unlike the Current Status document, this roadmap focuses on major product milestones rather than daily development tasks.



Each phase represents a significant step toward building a complete AI Employee platform.



\---



\# Vision



Build the world's most configurable AI Employee platform.



Businesses should be able to deploy highly intelligent AI Employees without custom software development.



Customers configure the platform.



They should not need developers.



\---



\# Current Phase



\## Phase 1



\*\*AI Employee Version 1\*\*



Status



🟨 In Progress



Objective



Deliver a production-ready AI Employee capable of handling real customer interactions and lead generation.



\---



\# Phase 1 Milestones



\## Foundation



Completed



\- Core Architecture

\- Conversation Engine

\- Memory System

\- Knowledge Base

\- Planning Engine

\- Qualification Engine

\- CRM

\- API



\---



\## Remaining Work



Updated 2026-07-30. Three items previously listed here are now done and have moved to Completed above:



\- ~~BusinessConfig~~ — complete, refactoring backlog 7/7

\- ~~Appointment Scheduling~~ — built and unit-tested; live end-to-end booking verification still pending

\- ~~Google Calendar Integration~~ — built and unit-tested; live end-to-end booking verification still pending



Genuinely remaining:



\- Deployment

\- Production Testing — blocked on the conversation-quality eval suite being runnable (Groq free-tier token cap; see docs/Current\_Status.md)

\- Live end-to-end booking verification against a real calendar

\- UI Improvements

\- Stability Improvements

\- Error Handling — partly addressed: LLM failures now degrade to a 503 rather than an unhandled 500 (Decision #021)

\- Documentation



\---



\## Deployment



Status



Planned — sequenced after current appointment scheduling verification completes



Objective



Get the AI Employee running on real infrastructure, reachable by real website visitors, replacing the current static/fake demo on kaivixlab.com with the actual working system.



Key Requirements



\- Containerize the backend (Dockerfile)

\- Choose and provision hosting

\- Deploy with production secrets configured (never committed to source)

\- Update Google OAuth redirect URI for the production domain

\- Connect the real chat widget (chat_widget.html already exists and works — it needs its hardcoded localhost API URL updated and to be embedded into the live site, not built from scratch)

\- Verify the deployed instance behaves identically to local dev before opening it to real visitors



Success Criteria



\- A real website visitor can have a real conversation with Bray, get qualified, and book a real appointment — no mock data, no static demo content

\- Secrets are never present in source control or client-side code

\- The deployed instance passes the conversation-quality eval suite



\---



\## Release Goal



AI Employee Version 1



The AI Employee should be capable of:



\- Answering questions

\- Understanding context

\- Qualifying leads

\- Booking appointments

\- Saving leads

\- Escalating to humans

\- Completing conversations naturally



\---



\# Phase 2



\## Customer Validation



Status



Planned



Objective



Acquire the first paying customers.



Primary Activities



\- Cold Outreach

\- Product Demonstrations

\- Customer Feedback

\- Case Studies

\- Testimonials

\- Website Improvements

\- Sales Process



Success Criteria



\- First paying client

\- Successful production deployment

\- Customer feedback incorporated



\---



\# Phase 3



\## Kaivix Core Platform



Status



Planned



Objective



Transform the AI Employee into a reusable platform.



Major Features



\- BusinessConfig

\- Configuration System

\- Business Templates

\- Knowledge Configuration

\- Scheduling Configuration

\- Branding Configuration

\- Qualification Configuration



Success Criteria



New customers require configuration rather than source code modifications.



\---



\# Phase 4



\## Multi-Tenant Platform



Status



Future as a phase — but note that several of its features have already been built early, as a side effect of the BusinessConfig work rather than as a deliberate start on Phase 4.



Objective



Support multiple businesses from one platform.



Major Features



\- Tenant Isolation — largely built. Every component below ConversationEngine is business\_id-scoped: CRM, LongTermMemory, ConversationMemory, KnowledgeBase namespacing, and calendar OAuth token storage. One process can serve many businesses (Decision #023).

\- Authentication — built. Admin dashboard uses Basic Auth; POST /chat/{business\_id} requires a per-business X-API-Key, stored as a SHA-256 hash and verified with secrets.compare\_digest (Decision #024). Plain POST /chat stays unauthenticated by design — it carries the live widget's traffic. Not yet built: customer-facing key management, rotation policy, or any self-service issuance.

\- Admin Dashboard — built for CRM lead viewing, behind Basic Auth.

\- Customer Dashboard

\- Billing

\- Usage Tracking

\- User Management



Caveat: multi-business serving is proven against a synthetic in-test second business only. No real second business config exists, and engines are cached per process with no eviction.



Success Criteria



Multiple customers operate independently on the same infrastructure.



\---



\# Phase 5



\## Enterprise Platform



Status



Future



Objective



Expand Kaivix into an enterprise AI automation platform.



Potential Features



\- Voice AI

\- WhatsApp Integration

\- Email Automation

\- CRM Integrations

\- Analytics Dashboard

\- Plugin Marketplace

\- Workflow Automation

\- Human Handoff

\- Team Collaboration

\- Enterprise Security



\---



\# Long-Term Goals



\## Product



Become a leading AI Employee platform.



\---



\## Technology



Maintain:



\- Modular architecture

\- Configuration-driven design

\- Enterprise scalability

\- High reliability



\---



\## Business



Acquire businesses across multiple industries.



Examples



\- Dental Clinics

\- Medical Practices

\- Law Firms

\- Real Estate

\- Marketing Agencies

\- Construction

\- E-Commerce

\- SaaS

\- Local Businesses



\---



\# Guiding Principles



Every new feature should satisfy at least one of the following:



\- Improves customer experience.

\- Increases platform reusability.

\- Reduces onboarding time.

\- Improves maintainability.

\- Enables future scalability.

\- Supports enterprise readiness.



If a feature satisfies none of these, it should be reconsidered.



\---



\# Release Strategy



\## Version 1



Production AI Employee



↓



\## Version 2



Reusable Kaivix Core



↓



\## Version 3



Multi-Tenant SaaS



↓



\## Version 4



Enterprise AI Platform



\---



\# Current Priority



The immediate objective is \*\*not\*\* to build every planned feature.



The priority is to complete AI Employee Version 1 and begin customer outreach.



Real customer feedback will guide future development.



\---



\# Success Definition



Kaivix Core succeeds when:



\- Businesses can deploy AI Employees with minimal configuration.

\- Customers trust the platform in production.

\- The platform scales without architectural redesign.

\- New features integrate cleanly into the existing architecture.

\- The first paying customers validate the product.



\---



\# Roadmap Maintenance



This document should only be updated when:



\- Product strategy changes.

\- Major milestones are completed.

\- Long-term priorities shift.

\- New platform phases are introduced.



It should remain stable and strategic rather than tracking daily development.

