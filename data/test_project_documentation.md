# Enterprise Customer Support & Smart Subscription Platform - Project Documentation

Document version 2.1 - Clean Local Execution Suite (No Docker / Direct Python Stack).

## 1. Project Overview

Enterprise Customer Support & Smart Subscription Platform (ECSS-Platform) is an integrated web application designed for enterprise customer service, multi-currency loyalty wallet management, and real-time support ticketing. Support agents log customer interactions, manage flash-sale purchasing inquiries, handle partial refunds, process ticket escalations, and manage seat licenses. Support leads and administrators oversee operations through automated real-time dashboards and fraud detection logs.

Duration: 4 weeks / 1 month (four one-week sprints). Delivery goal: A production-ready MVP capable of handling complex edge-case operations by the end of week 4.

## 2. Business Problem

Currently, the customer operations team relies on disconnected spreadsheets, manual multi-currency refund calculations, and fragmented ticketing tools. Key business problems include:
- Inconsistent partial refund handling: Returning items bought under tiered coupon codes results in lost revenue or over-refunding.
- Disrupted workflows during account deactivation: When an agent is deactivated, assigned high-priority tickets and active background tasks stall without ownership transfer.
- Payment gateway timeout conflicts: Asynchronous third-party payment responses arrive after reservation windows expire, creating double-allocations or unrecorded payment charges.
- Exchange rate discrepancies: Refunding loyalty balances across multiple currencies causes financial variances due to fluctuating conversion rates.

## 3. Project Objectives

- Provide a single unified system for support ticketing, multi-currency wallet tracking, and dynamic order adjustments.
- Enforce automated edge-case resolution rules for refund calculations, account deactivation ownership transfer, and payment timeouts.
- Eliminate orphan tickets and unassigned background processes when support staff change roles or are deactivated.
- Deliver operational metrics alongside automated fraud and variance anomaly flagging (>35% above regional baselines).
- Deploy a secure, fully tested Python MVP within a strict 4-week timeline under constrained dev capacity.

## 4. Scope

In scope for the MVP:
- Authentication, RBAC, and session management.
- Customer management with multi-currency loyalty wallets (USD, EUR, EGP).
- Ticket management with status workflows, priority escalation, and internal audit comments.
- Dynamic Flash Checkout & Reservation dispute ticketing with 5-minute hold windows.
- Automated Partial Refund & Tiered Coupon Recalculation logic.
- Agent account management with mandatory process/ticket ownership reassignment upon deactivation.
- Advanced search, multi-parameter filtering, and real-time operational dashboard with fraud flagging.
- REST API, PostgreSQL database with schema migrations, structured logging, and direct local Python entrypoints (`python main.py`).

## 5. Out of Scope

- Native mobile applications (iOS/Android).
- Unstructured natural language AI voice streaming.
- Third-party CRM synchronization beyond core payment/SMS gateways.
- Advanced custom visual report builders.
- Containerized container orchestration and Docker setups.

## 6. Users and Personas

- Support Agent: Creates and updates customer records, opens/processes support tickets, issues partial/full refunds under strict business constraints, adds internal audit comments.
- Support Lead: Manages agent accounts, reviews high-variance refund flags, overrides SLA priority escalations, exports CSV reports, and monitors team load.
- Administrator: Manages global system settings, RBAC definitions, system configuration, and database migrations.

## 7. Functional Requirements

- **FR-01 Authentication & Session Limits:** Users sign in using email and password with modern hashing (Argon2/Bcrypt). Active sessions expire after 15 minutes of inactivity; failed login attempts are rate-limited.
- **FR-02 User Roles & RBAC:** Enforces role permissions (Agent, Lead, Admin) across all endpoints.
- **FR-03 Account Deactivation Ownership Transfer:** When a Support Lead or Admin deactivates an Agent account, the system MUST require explicit reassignment of all open/in-progress tickets and active background processes to an active agent before deactivation is committed.
- **FR-04 Customer Management & Loyalty Wallet:** Agents create, edit, and view customer profiles containing multi-currency loyalty point balances (USD, EUR, EGP). Points earned on purchases are locked during active refund windows.
- **FR-05 Ticket Creation & SLA Priority Auto-Escalation:** Tickets are created with title, description, category, and priority (Low, Medium, High, Urgent). High/Urgent tickets auto-escalate if unassigned after 30 minutes.
- **FR-06 Flash Checkout Reservation Disputes:** System handles ticket inquiries regarding 5-minute reservation checkout holds. If an asynchronous payment gateway confirmation returns AFTER the 5-minute window has expired and the item was re-allocated, the system MUST automatically trigger a Store Credit Fallback to the customer's loyalty wallet without throwing unhandled exceptions.
- **FR-07 Partial Refund & Tiered Coupon Recalculation:** When processing a partial return for an order that qualified for a tiered discount (e.g., "Spend $100, Get $20 Off"), the system MUST recalculate the remaining order total against the threshold. If the remaining total falls below $100, the $20 discount is revoked, and the refund amount is reduced accordingly.
- **FR-08 Multi-Currency Refund Rate Policy:** Refunds processed for foreign-currency purchases MUST be executed based on the original transaction exchange rate, preserving the exact original nominal currency amount regardless of current market exchange rate fluctuations.
- **FR-09 Ticket Status & Cyclic Dependency Prevention:** Tickets move strictly through status states: Open -> In Progress -> Waiting for Customer -> Resolved -> Closed. Closed tickets cannot return to Open without a Lead override.
- **FR-10 Internal Audit Comments:** Agents add internal comments. System automatically appends immutable system logs whenever ticket priority, assignee, or refund status changes.
- **FR-11 B2B Workspace & Seat Licensing Proration:** Leads manage subscription seat licenses. Mid-cycle addition or removal of seats triggers an immediate prorated calculation based on remaining days in the billing cycle.
- **FR-12 Advanced Search & Filtering:** Users search tickets/customers by keyword, ticket ID, or customer name, with multi-parameter filtering by status, priority, assignee, date range, and fraud-flag status.
- **FR-13 Operational Dashboard & Fraud Flagging:** Shows real-time counts of open tickets, tickets by status/priority, agent load metrics, and flags any refund request exceeding a 35% financial variance threshold for Lead review.
- **FR-14 Data Export:** Leads export filtered ticket and refund lists to CSV with complete system metadata.

## 8. Non-Functional Requirements

- **API Performance:** HTTP 200 responses under 200ms latency at 95th percentile under 2,000 concurrent active connections.
- **Data Integrity:** Zero double-charge tolerance during concurrent payment/refund operations.
- **Security & Compliance:** Modern password hashing, OAuth2/JWT authentication, and audit logs for all Protected Customer Data (PCD) reads and writes.
- **Availability:** 99.9% uptime for core API services during operational hours.
- **Database:** PostgreSQL with version-controlled schema migrations.
- **Test Coverage:** Minimum 80% automated unit and integration test coverage across financial calculation modules and status state machines.
- **Execution:** Direct Python entrypoint execution (`python main.py`).

## 9. Technical Constraints

- Project timeline is fixed at 4 weeks (4 one-week sprints).
- Restricted scope strictly focused on the MVP functional specifications.
- Development capacity limited to approximately 30 productive hours per team member per week.
- Stack requirement: Python backend framework (FastAPI/Django), PostgreSQL, Redis caching layer, Local Virtual Environment (`venv`).

## 10. Team Information

- 1 Project Manager (part-time on delivery tasks, sprint planning, and documentation)
- 2 Backend Developers
- 2 Frontend Developers
- 1 UI/UX Designer
- 1 QA Engineer

## 11. Timeline

- Week 1 (Sprint 1): Foundations - Repo setup, database schema migrations, OAuth2/JWT authentication, RBAC, wireframe approval.
- Week 2 (Sprint 2): Core Ticketing & Multi-Currency Loyalty - Customer management, ticket creation, status state machine, agent deactivation transfer logic.
- Week 3 (Sprint 3): Financial Edge Cases & Dashboard - Dynamic checkout timeouts, partial refund coupon recalculation logic, multi-currency conversion rules, dashboard metrics, and fraud flagging.
- Week 4 (Sprint 4): QA Integration, Stress Testing, Bug Fixing, System Hardening, and MVP Release.

## 12. Milestones

- M1 (End of Week 1): Authentication, RBAC, and core PostgreSQL database schema migrations deployed to dev environment.
- M2 (End of Week 2): End-to-end customer and ticket creation working; ownership transfer logic enforced on agent deactivation.
- M3 (End of Week 3): Partial refund logic, currency exchange rules, and dashboard integrated; regression test suite running.
- M4 (End of Week 4): Full MVP stack functional, passing QA acceptance criteria, and delivered to stakeholders.

## 13. Dependencies

- Ticket status escalation depends on database schema migrations and authentication middleware.
- Refund calculation endpoints depend on core customer loyalty wallet module integration.
- Dashboard fraud flags depend on completion of partial refund and ticket logging pipelines.
- Final deployment depends on QA regression suite execution and zero open critical severity bugs.

## 14. Risks

- Complex Financial Logic Delays: Edge-case refund rules and tiered coupon recalculations may take longer to implement and test than estimated.
- Reassignment Bottlenecks: Unassigned process transfers during agent deactivation may cause foreign-key or state lock conflicts in PostgreSQL.
- Payment Gateway Latency Simulation: Simulating late-arriving asynchronous payment callbacks in test environments may delay QA validation.
- QA Capacity Constraints: A single QA engineer testing financial edge cases, RBAC, and ticket workflows in Sprints 3 and 4.
- Scope Creep: Unplanned stakeholder requests for live streaming or complex analytics during sprint execution.

## 15. Acceptance Criteria

- Support Agents can execute customer creation, ticket management, and status updates end-to-end.
- Deactivating an Agent account with open tickets or active background tasks forces mandatory reassignment to another active agent before proceeding.
- Processing a partial refund on an order with a tiered discount correctly recalculates remaining order eligibility and deducts revoked discounts accurately.
- Late-arriving payment callbacks after a reservation window expiry automatically trigger a Store Credit Fallback to the customer's wallet.
- Search and multi-parameter filtering return results in under 2 seconds on a test dataset of 10,000 records.
- Entire stack initializes successfully via standard Python entrypoint (`python main.py`).

## 16. MVP Definition

The MVP is complete when support agents and leads can process tickets, manage loyalty wallets, handle complex partial refunds, and manage team accounts without data orphan risks; when financial edge cases (refund recalculation, payment timeouts) execute predictably; and when the application runs successfully via Python entrypoints by the end of Week 4.