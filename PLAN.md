# DealFlow360 — Implementation Plan

Purpose: This file is the execution roadmap for Claude Code.

This is NOT a complete system-design document. It describes how we are going to build the project, in what order, what must be validated, and how context must be preserved.

The project must be implemented incrementally. Do not attempt to build everything at once.

**Stack note:** We are building on FastAPI + React + PostgreSQL, NOT inside the Odoo framework itself. The hackathon problem statement explicitly allows any tech stack. Wherever this plan says "Odoo-native patterns," it means business logic that conceptually mirrors how Odoo would model this domain (roles, approval chains, ledgers, audit trails) — NOT literal Odoo modules.

**This is an ERP system.** Build to industry-standard ERP practices throughout, not hackathon-shortcut patterns: normalized schema, explicit state machines for every lifecycle entity, versioned migrations, audit trails, soft-delete/archival instead of hard deletes on master data, idempotent business operations, and consistent API contracts. Judging criteria center on **data model quality, business logic correctness, and end-to-end workflow** — treat these as the primary engineering bar, above UI polish.

---

## 0. READ THIS FIRST

Before making any code changes:

1. Inspect the existing repository.
2. Understand the current project structure.
3. Read all existing documentation and configuration.
4. Read:
    * PLAN.md
    * PROJECT_CONTEXT.md
    * IMPLEMENTATION_LOG.md
    * DealFlow360_PRD_Merged.md (full source PRD — authoritative for feature scope)
    * SECURITY_SPEC.md (authoritative for security implementation — already uses the correct PRD roles, no remapping needed)
    * any existing README.md
5. Inspect the relevant code before modifying it.
6. Do not assume that something is missing until the repository has been inspected.
7. Do not introduce technologies merely because they appear in this plan — see Section 0.5.
8. Preserve existing functionality unless a change explicitly requires modifying it.
9. If this is a brand-new repository (no code yet), skip inspection and proceed to Phase 1 (Foundation) directly.

If important information is missing, **do not silently invent it** — see Section 0.6 (Ask, Don't Assume).

---

## 0.5 TECHNOLOGY EVALUATION CHECKPOINT (run this before starting EVERY phase)

Before beginning any phase below, explicitly answer these questions and record the answer in PROJECT_CONTEXT.md under "Important Technical Decisions," even if the answer is "no change needed":

1. Does this phase have a real, specific requirement that our current stack (FastAPI, React, PostgreSQL, Docker Compose) cannot cleanly satisfy?
2. If yes — name ONE concrete candidate technology or library that addresses it (not a category, a specific tool).
3. State: what problem forces this, why the current stack doesn't solve it, what breaks or degrades without it, and what the simplest alternative would be.
4. Do NOT add the dependency yet. Present the option and reasoning to the team/user for a decision first, then record the outcome (adopted or rejected, and why) in PROJECT_CONTEXT.md.

This is a deliberate, recurring checkpoint — every phase should genuinely consider whether something new is warranted, not default to silence. This is different from blindly adding new tech: the bar is still "does it solve a real, present problem in this specific phase," per Section 20 (No Unnecessary Over-Engineering).

---

## 0.6 ASK, DON'T ASSUME

If a business-logic detail is ambiguous or not fully specified, **stop and ask the user** rather than picking a default silently. This applies especially to:

* Exact blended discount risk score formula/weighting (not yet locked — see PROJECT_CONTEXT.md known issues)
* Proration rounding rules (round up/down/nearest, and to what precision)
* Deal-health anomaly thresholds (what counts as "stalled," what counts as a discount "anomaly" relative to a rep's history)
* Approval chain exact percentage boundaries if not explicitly stated for a given category
* Warehouse selection tie-breaking rules when two warehouses are equally preferable
* Any field, workflow branch, or edge case not explicitly described in DealFlow360_PRD_Merged.md

When something is genuinely unclear after checking the PRD file, state the specific question clearly and wait for an answer. If a decision must be made to keep moving, state the assumption explicitly in PROJECT_CONTEXT.md and flag it for later confirmation — never bury an invented rule silently in code.

---

## 1. SOURCE OF TRUTH

**PLAN.md** — implementation phases, development order, priorities, acceptance criteria, architectural direction.

**PROJECT_CONTEXT.md** — current understanding of the project. Updated whenever an important architectural, technical, product, or implementation decision is made.

**IMPLEMENTATION_LOG.md** — what has actually happened during implementation.

**DealFlow360_PRD_Merged.md** — authoritative source for feature scope and business logic. If this plan and the PRD conflict, the PRD wins on *what* to build; this plan governs *order and process*.

**SECURITY_SPEC.md** — authoritative for security implementation (JWT handling, rate limiting, RBAC, attack mitigations). Uses the correct 5 PRD roles directly (Sales Rep, Sales Manager/Approver, Finance/Operations User, Customer, Admin) — no remapping needed.

**Rule:** Code is the implementation truth. Documentation describes intent and context. If documentation conflicts with the code, inspect the code and update the documentation rather than blindly following stale documentation.

---

## 2. HOW CLAUDE SHOULD WORK

**Step 1 — Understand:** current behavior, existing architecture, dependencies, affected modules, potential side effects.

**Step 2 — Plan:** smallest implementation required, files to modify, files NOT to touch, dependencies, validation required. Run the Section 0.5 tech checkpoint here.

**Step 3 — Implement:** smallest clean change that satisfies the current phase. Do not refactor unrelated code.

**Step 4 — Validate:** run relevant tests, type checks, linting, builds, migrations, manual checks.

**Step 5 — Document:** update IMPLEMENTATION_LOG.md, and PROJECT_CONTEXT.md when necessary.

**Step 6 — Continue:** only move to the next phase when the current phase has a working, validated result.

---

## 3. DEVELOPMENT PRINCIPLE

Build from:

**Foundation → Data Model → Core Workflow → Integration → Security → Supporting Features → Reliability → Performance → Frontend Polish → Demo Polish**

The project should always remain runnable.

---

## 4. HACKATHON TIMELINE (24 HOURS, 3 PEOPLE) — MAPS TO PHASES BELOW

| Hours | Phase(s) | Exit Condition |
|---|---|---|
| 0–3 | Phase 0 + Phase 2 (schema lock — see below, this now gets extra time given its judging weight) | PROJECT_CONTEXT.md fully filled; schema, constraints, and state machines agreed and diagrammed |
| 3–5 | Phase 1 (Foundation) | Repo scaffolded, `docker-compose up` runs empty app successfully |
| 5–15 | Phase 3 (Core Workflow — 🔴 Core features from PRD, in priority order within Core) | Rep can build a quote, risk score computes, over-limit quote auto-routes to approval, warehouse split + backorder works, hybrid billing + proration works, customer portal negotiation + re-approval works |
| 15–19 | Phase 4–6 (Integration, Security/RBAC hardening, 🟡 Supporting features) | Deal health dashboard, upsell panel, reporting/export, RBAC fully enforced server-side |
| 19–22 | Phase 9–10 (Error handling, Frontend integration per mockup, Demo Polish) | Demo flows run cleanly twice in a row |
| 22–24 | Phase 11–12 (Demo Engineering, Viva Readiness) | Backup demo recording exists; PROJECT_CONTEXT.md viva section complete |

If behind schedule, drop to 🟢 Bonus items first (multi-currency, multi-company — see Section 18), never drop 🔴 Core items.

---

## 5. PHASE 0 — REPOSITORY RECONNAISSANCE

Inspect repo structure, backend, frontend, database models, API endpoints, authentication, configuration, Docker/environment setup, dependencies, existing tests, existing UI (or note "none — fresh start").

Produce/update PROJECT_CONTEXT.md.

**Exit condition:** We understand the existing codebase (or the intended one, if fresh) well enough to modify it safely.

---

## 6. PHASE 1 — PROJECT FOUNDATION

Set up:

* FastAPI project structure (routers, models, schemas, auth middleware)
* React project structure (routes per role — see note in Phase 8 about waiting for design input)
* PostgreSQL via SQLAlchemy + **Alembic for versioned migrations** (industry-standard ERP practice — schema will evolve, migrations must be tracked, not ad-hoc `create_all`)
* Docker Compose (Postgres + backend + frontend — no Redis, no extra infra at this stage)
* Development tooling (linting, env config)

Run Section 0.5 checkpoint before starting.

**Exit condition:** The project starts successfully and the basic foundation is verified.

---

## 7. PHASE 2 — CORE DATA MODEL (treat as first-class engineering — this is a primary judging criterion)

This phase gets more time and rigor than a typical hackathon schema pass. Implement the full data model required across **all** PRD features (Core + Supporting + Bonus-if-time), covering: users/roles, customers, products (with variants), price lists, discount tiers, approval chains, quotations, quotation lines, warehouses, stock levels, fulfillment splits, backorders, subscription plans, billing schedules, proration records, upsell/cross-sell rule tables, deal health snapshots, approval/audit logs.

For every model, determine and document in PROJECT_CONTEXT.md:

* Purpose and every field with its type and constraints (NOT NULL, CHECK constraints — e.g., discount percentage ranges, UNIQUE where applicable)
* Relationships and foreign keys, with explicit ON DELETE behavior considered (RESTRICT vs CASCADE — do not leave this as a default you haven't thought about)
* Indexes on foreign keys and any column used in frequent filters (customer_id, status, created_at)
* Audit columns on every table: `created_at`, `updated_at`, `created_by`
* Archival pattern for master data (products, customers) — use an `archived_at`/`is_active` flag, not hard deletes, matching standard ERP practice
* **Explicit state machines** for every lifecycle entity — do not leave state transitions implicit:
  - Quotation: draft → pending_approval → approved → confirmed → fulfilled / cancelled
  - Approval: pending → approved / rejected / returned_for_revision
  - Subscription: active → modified → cancelled
  - Fulfillment: pending → partially_fulfilled → fulfilled / backordered

  Document each as an explicit enum plus its allowed transitions, validated in code — invalid transitions must be rejected, not just unused.

**Deliverable:** a one-page ERD (Mermaid or equivalent) checked into the repo, kept up to date whenever the schema changes. This doubles as part of the required hackathon architecture diagram deliverable.

Run Section 0.5 checkpoint before starting (e.g., is a schema-diagramming or migration tool needed beyond Alembic?).

**Validation:** records can be created/read, relationships work, constraints behave correctly (test invalid input is rejected), state transitions reject invalid moves.

**Exit condition:** The full data model supports every Core and Supporting workflow in the PRD, is diagrammed, and is under migration control.

---

## 8. PHASE 3 — CORE BUSINESS WORKFLOW (🔴 Core features from PRD, full scope, sequenced)

Per the PRD's own Core/Supporting/Bonus breakdown (see Section 18), implement in this order — each fully working end-to-end before starting the next:

1. Login (all roles: Sales Rep, Sales Manager/Approver, Finance/Operations User, Customer/Portal User, Admin)
2. Quotation builder: products, quantities, line-level discounts, live totals
3. **Blended discount risk engine** — confirm exact formula with the user per Section 0.6 before implementing; this is the signature differentiator
4. Automated approval routing (Manager, then Finance if blended score requires it)
5. Multi-warehouse fulfillment splitting + backorder handling
6. Hybrid billing: one-time + recurring subscription lines on the same order, with proration on mid-cycle change (confirm rounding rule per Section 0.6)
7. Customer portal negotiation screen, with auto re-entry into approval on threshold breach
8. Audit trail on every approval/rejection/edit (user, timestamp, reason)

Priority within this phase: Correctness > Reliability > Simple UX > Validation > Error handling.

**Exit condition:** A rep can run both full demo flows (discount → approval → warehouse split; upsell → portal negotiation → re-approval) end-to-end.

---

## 9. PHASE 4 — API / FRONTEND INTEGRATION

Connect frontend to backend for each screen as it becomes ready. See Phase 8 (Section 13 below) for the frontend hold-point before UI work begins.

**Exit condition:** The core workflow works through the actual intended interface.

---

## 10. PHASE 5 — 🟡 SUPPORTING FEATURES (per PRD's own classification)

Only after Phase 3 (Core) is fully working end-to-end:

* Live upsell/cross-sell panel (rule-based recommendation table — see Section 20, not ML)
* Deal health and anomaly dashboard (stalled deals, discount anomalies, delivery slippage)
* Reporting with filters (period, sales team, approval status, product) + PDF/XLS export
* Product variants and price-list complexity (customer-tier and currency-specific rules)
* Manual warehouse override on the fulfillment split screen
* Nudge/escalation actions from deal health alerts

Run Section 0.5 checkpoint before starting (e.g., does PDF/XLS export need a specific library? Evaluate and record the choice.).

**Exit condition:** Each supporting feature works reliably before moving to the next.

---

## 11. PHASE 6 — SECURITY / RBAC (using SECURITY_SPEC.md)

**Reference:** SECURITY_SPEC.md is the authoritative implementation spec — it already uses the correct 5 PRD roles directly:

* **Admin** — full system access, user/role management, all analytics
* **Sales Manager/Approver** — reviews/approves discount-flagged quotations, configures discount tiers and approval chains, monitors deal health
* **Sales Representative** — builds/edits own quotations, applies discounts within tier, tracks approval/fulfillment status
* **Finance/Operations User** — second-level approval for high-risk discounts, manages fulfillment/backorder decisions, reconciles billing/credit notes
* **Customer (Portal User)** — views and negotiates only their own quotations; no access to internal screens

Implement using **permission-based authorization** (not hardcoded role checks), e.g., `deal.create`, `deal.approve_manager`, `deal.approve_finance`, `deal.update_own`, `portal.own_quote.view`, `portal.own_quote.negotiate` — mirroring the pattern in the security spec, applied to the roles above.

Required from the security spec, adapted to this project:

* Password hashing (Argon2/bcrypt) — never plaintext
* JWT: short-lived access tokens, refresh-token rotation, algorithm explicitly whitelisted, no sensitive data in payload, `exp`/`iss`/`aud` validated
* **Resource-level (ownership) checks** — a Sales Rep can only edit their own quotations; a Customer can only view their own quotation (prevents IDOR — e.g., `/api/quotations/101` → `/102`)
* Rate limiting on login endpoints; generic (non-user-enumerating) auth failure messages
* All approval/rejection/edit actions written to the audit log (user, timestamp, reason) — this is also a PRD-explicit requirement, not just a security nicety
* Backend enforcement is authoritative — frontend hiding of buttons is UX only, never the actual control

Document every security decision (why needed, what it protects, simplest safe implementation) in PROJECT_CONTEXT.md, and complete the JWT security checklist from the spec file before final submission.

**Exit condition:** Unauthorized users cannot perform protected operations, verified by explicitly testing cross-role and cross-resource access attempts (not just the happy path).

---

## 12. PHASE 7 — REDIS / CACHING

Not planned by default. Only introduce if the Phase 0.5 checkpoint at any stage surfaces a real, measured bottleneck (not a theoretical one). Document justification before implementing: what's stored, TTL, invalidation strategy, graceful failure behavior if Redis is unavailable.

---

## 13. PHASE 8 — FRONTEND — WAIT FOR DESIGN INPUT BEFORE BUILDING UI

**Do not assume a visual design.** A mockup exists in Excalidraw. Before starting any frontend screen implementation:

1. Ask the user to provide the Excalidraw mockup reference and/or a markdown file describing the design system, component patterns, or frontend resources to follow.
2. Do not invent a visual design system, color palette, or component library choice on your own in the meantime.
3. Once provided, follow it as the source of truth for layout/visual decisions, while backend-defined API contracts (Phase 4) remain the source of truth for data shape and behavior.

Prioritize screens in this order once design input is available: Quotation Builder → Approval Screen → Warehouse Split Screen → Billing Screen → Customer Portal → Deal Health Dashboard.

---

## 14. PHASE 9 — ERROR HANDLING & RESILIENCE

Review for: invalid input, missing data, duplicate operations, unauthorized requests, backend failures, database errors, partial operations, concurrent operations (e.g., two managers approving the same quote at once — needs optimistic locking / a version column on quotations).

The system should fail predictably. Avoid silent failures.

---

## 15. PHASE 10 — UI/UX & DEMO POLISH

Only after core product and supporting features work. Prioritize: clean primary workflow, clear dashboards, useful feedback, meaningful empty/loading/error states, demo-friendly seed data.

---

## 16. PHASE 11 — DEMO ENGINEERING

Create a deterministic demo path covering at least 2 full flows (per the PRD's 5-minute demo requirement):

**Flow 1:** Rep gives over-limit discount → auto-routes to approval → approved → warehouse split (with backorder if relevant).

**Flow 2:** Rep adds upsell suggestion (margin updates live) → confirms → customer portal shows quote → customer counters → quote auto re-enters approval → hybrid billing (one-time + subscription) reflected correctly.

Prepare realistic seed data. **Record a full backup demo video** in case of live failure.

---

## 17. PHASE 12 — VIVA READINESS

PROJECT_CONTEXT.md's "Viva-Critical Decisions" section must cover, for each major decision: what we chose, why, the alternative, the trade-off, the failure scenario. Minimum coverage: tech stack, schema/state-machine design, blended risk score, warehouse split logic, security/RBAC model, no-Redis, no-AI-for-upsell decisions, and any technology adopted via a Section 0.5 checkpoint.

---

## 18. SCOPE — PRD'S OWN CLASSIFICATION (full feature set, sequenced not cut)

**🔴 Core — must work, build in this order within Phase 3/5:**
Authentication, Quotation, Discount governance, Approval routing, Blended risk, Upsell/cross-sell, Warehouse splitting, Backorders, Hybrid billing, Customer negotiation, Deal health, Audit trail, Reporting, RBAC.

**🟡 Supporting — important, build after Core is fully working:**
Product variants, Price-list complexity, Promotion ranking, Manual warehouse override, Nudges/escalations, Exports.

**🟢 Bonus — explicitly optional per PRD, only if ahead of schedule:**
Multi-currency, Multi-company.

**Separately avoid (not PRD features — architectural over-engineering, not scope):**
ML/AI-based upsell recommendation models, Kubernetes/microservices, unnecessary Redis, unnecessary abstractions — see Section 20.

When time becomes limited: finish 🔴 Core completely first, then 🟡 Supporting, then 🟢 Bonus only if stable. Never sacrifice a 🔴 Core feature to add 🟡 or 🟢 features early.

---

## 19. SCOPE CONTROL

Before implementing a new feature, ask: does it directly improve the core product or judging/demo value? Can it be implemented safely within remaining time? Can we explain it in the viva? Does it introduce disproportionate complexity? If mostly no — and it's not a 🔴 Core PRD feature — defer it.

---

## 20. NO UNNECESSARY OVER-ENGINEERING

Do NOT automatically introduce: microservices, Kubernetes, Kafka, event-driven architecture, multiple databases, unnecessary Redis, unnecessary AI/ML, unnecessary abstractions. This is distinct from Section 0.5 — that checkpoint asks "is something genuinely needed here," this section is the default answer of "no" until proven otherwise.

---

## 21. CONTEXT PRESERVATION RULES

Every meaningful implementation session must leave the repository understandable to the next session. Update IMPLEMENTATION_LOG.md using its defined format after each meaningful task.

---

## 22. HANDOFF PROTOCOL

Incoming sessions read PLAN.md, PROJECT_CONTEXT.md, IMPLEMENTATION_LOG.md, README, then relevant source files, then git diff/status. Determine what's implemented, partial, broken, and the next highest-priority task. Do not restart completed work. Do not assume prior implementation is correct without verification.

---

## 23. GIT CHECKPOINTS

Small, understandable commits after stable milestones (e.g., `feat: add blended risk score engine`, `feat: add resource-ownership checks for quotations`).

---

## 24. TESTING STRATEGY

At minimum validate: core business logic (risk score, proration), state machine transition rules, permission/resource-ownership boundaries, database constraints, critical error paths, demo-critical workflows. Never claim something works without checking it.

---

## 25. DEFINITION OF DONE

A feature is done when: implementation exists, existing functionality still works, relevant tests/checks pass, important errors are handled, security/RBAC is verified for that feature, documentation is updated, the next session can understand what happened.

---

## 26. WHEN THE HACKATHON CLOCK IS RUNNING OUT

Switch into Demo Survival Mode. Priority: complete 🔴 Core workflow → stability → demo reliability → security basics → 🟡 Supporting features if time allows → UI polish → viva prep. Drop 🟢 Bonus first, always.

---

## 27. FINAL DELIVERY CHECKLIST

**Product:** All 🔴 Core PRD features work end-to-end; 🟡 Supporting features implemented if time allowed; edge cases handled; demo data prepared.

**Data Model:** Schema fully normalized with justified constraints/indexes; ERD diagram current; state machines documented and enforced; migrations tracked via Alembic.

**Business Logic Fidelity:** Approval routing, discount governance, warehouse splitting, billing proration implemented in application logic (not hardcoded/faked); customer portal is a genuinely separate, restricted view.

**Security:** Permission-based RBAC enforced server-side for all real PRD roles; resource ownership checks in place; JWT security checklist (from the security spec file) completed; audit logging on all approval/security events.

**Demo:** Deterministic demo path; backup recording exists; demo story is clear (before → after).

**Viva:** Every major decision (including any adopted via Section 0.5) is documented and explainable; failure scenarios and scalability limitations are understood.

**Documentation:** PLAN.md, PROJECT_CONTEXT.md, IMPLEMENTATION_LOG.md current; README usable.

**Deliverables (per hackathon spec):** Working app + seed data; 5-minute live demo covering 2 full flows; one-page architecture diagram (can reuse the ERD); short "what we'd build next" note.

---

## 28. CLAUDE'S OPERATING RULE

Treat this file as the implementation path, not a script to follow blindly. If repository reality conflicts with the plan: stop, understand the conflict, choose the simplest safe resolution (asking the user if it involves a business-logic ambiguity per Section 0.6), update the relevant context, continue.

The goal is a **working + impressive + reliable + explainable** ERP-grade hackathon project — with a data model and business logic that would hold up to real engineering scrutiny, not just a demo that looks right on the surface.
