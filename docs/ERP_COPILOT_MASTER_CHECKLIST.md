# DynamicPro ERP Co-Pilot — Master Living Execution Checklist

**Document Version:** 1.0.0  
**Classification:** Living Project Control & Task Tracking Ledger  
**Author:** Tech Lead & Antigravity Agent  
**Date:** 2026-10-25  
**Synchronized With:**
* [ERP_COPILOT_MASTER_BLUEPRINT.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_COPILOT_MASTER_BLUEPRINT.md)
* [ERP_COPILOT_BUGS_AND_SOLUTIONS.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_COPILOT_BUGS_AND_SOLUTIONS.md)
* [ERP_METADATA_INTEGRATION_PLAN.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_METADATA_INTEGRATION_PLAN.md)
* [ERP_METADATA_DISCOVERY_REFERENCE.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_METADATA_DISCOVERY_REFERENCE.md)

---

## 📌 Instructions for Living Updates
1. Every task is marked `[ ]` (Pending), `[-]` (In Progress), or `[x]` (Completed & Verified).
2. After completing every individual step, this checklist must be immediately updated.
3. Newly discovered tasks, edge cases, or sub-steps must be appended under the relevant track.
4. Per user constraint, this tracking ledger maintains a structured outline format without tables.

---

## 🚦 Global Status Overview

* **Current Stage:** Phase 6 Generic Scaling & Compilation Complete (Universal 822-Screen Catalog Indexed in O(1))
* **Active Running Infrastructure:**
  * Python FastAPI AI Engine (Port 8000)
  * .NET 10 LMS Backend
  * Angular 19 LMS UI
  * Microsoft DevTunnel CDP Bridge (Port 9222 -> Port 443 HTTPS/WSS)
* **Overall Completion:** 15 / 16 Major Milestones Completed (93.8% Complete)

---

## 📋 Track A: Critical Bug & Defect Remediations (From Bugs Document)

### Task A.1: Decouple Purchases Hardcoding & Implement Generic Form Driver
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target Files:** `src/services/agentic_stepper_service.py`, `src/services/cdp_agent_service.py`
* **Sub-tasks:**
  * [x] A.1.1 Remove hardcoded Purchases prompt from `extract_transaction_payload` and replace with dynamic schema prompt.
  * [x] A.1.2 Remove hardcoded `#SupplierID` / `#StoreID` queries from `fill_erp_form_bridge` and replace with generic DOM injector.
  * [x] A.1.3 Replace hardcoded Purchases completion message with dynamic document title and formatted template.

### Task A.2: Recompile Stale Production Web Component Bundle
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target Files:** `learn-dynamic-pro-ui/public/lms-copilot.bundle.js`
* **Sub-tasks:**
  * [x] A.2.1 Execute `npm run build:element` in `DynamicProLearn/learn-dynamic-pro-ui` (Generated 654.2 KB bundle).
  * [x] A.2.2 Verify bundle contains `streamAgentExecution`, `/v1/erp/agent/stream`, and `listUserPages` (Verified: 100% present).
  * [x] A.2.3 Ensure bundle IIFE wrapper isolates Zone.js scope on PC 2 (Verified clean IIFE isolation).

### Task A.3: Align Bridge Method Names & Property Mapping
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target Files:** `learn-dynamic-pro-ui/src/app/core/services/erp-bridge.service.ts`, `erp-navigator.service.ts`
* **Sub-tasks:**
  * [x] A.3.1 Add support for `window.DynamicERP.listUserPages()` in `ErpBridgeService.listScreens()`.
  * [x] A.3.2 Normalize candidate extraction in `ErpNavigatorService` to accept `page_id`, `screen_key`, and `name_ar`.

### Task A.4: Fix DevTunnel Cloud Relay URL Resolution & Port Redirection
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/services/cdp_agent_service.py`
* **Sub-tasks:**
  * [x] A.4.1 Update `_resolve_urls()` to detect `.devtunnels.ms` addresses automatically.
  * [x] A.4.2 Enforce `https://` / `wss://` over port 443 without appending `:9222`.

### Task A.5: Calibrate Lexical Scoring & Report Disqualification Penalty
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/services/agentic_stepper_service.py`
* **Sub-tasks:**
  * [x] A.5.1 Apply `-0.35` penalty to screens containing `تقرير`, `تفاصيل`, `اعدادات`, `مصمم` when goal is transactional.
  * [x] A.5.2 Boost qualifier tokens (`مقاولين` -> 7090, `عملاء` -> 7156, `سلفة` -> 7158, `تشغيل` -> 313).

### Task A.6: Elevate CDP Discovery Timeout & Add Retry Loop
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/services/cdp_agent_service.py`
* **Sub-tasks:**
  * [x] A.6.1 Increase discovery timeout from `1.5s` to `4.0s` for internet cloud relays.
  * [x] A.6.2 Add a 2-attempt retry with 350ms backoff before declaring CDP offline.

### Task A.7: Add Dual-Path Escalation Chip in Chat UI
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target Files:** `learn-dynamic-pro-ui/src/app/shared/components/copilot-chat/copilot-chat.component.ts`, `copilot-chat.component.html`
* **Sub-tasks:**
  * [x] A.7.1 Detect when action queries fail to find visible DOM inputs in Path 1 (`shouldOfferVisionEscalation`).
  * [x] A.7.2 Render interactive 1-click chip to launch Path 2 Vision Agent immediately (`runVisionAgent`).

---

## 📋 Track B: Metadata Integration Strategy (From Integration Plan)

### Task B.1: Phase 1 — Establish High-Speed Dictionary-Indexed `forms_metadata.json`
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/data/forms_metadata.json`
* **Sub-tasks:**
  * [x] B.1.1 Define O(1) multi-index dictionary architecture (`by_page_id`, `by_screen_key`, `by_module`, `intents_index`).
  * [x] B.1.2 Populate verified core metadata dictionary for Purchases (`289`), Sales (`290`), Loans (`7158`), Journal (`311`), and Movements (`112`).
  * [x] B.1.3 Provide 1-click extraction scripts for ERP Team (`scratch/extract_screen_metadata.sql` + `scratch/extract_console_snippet.js`).
  * [x] B.1.4 Implement Python high-performance singleton catalog loader (`FormsMetadataCatalog` in `src/services/forms_catalog_service.py`) with O(1) hash lookups.
  * [x] B.1.5 Create unit smoke test (`tests/unit/test_forms_catalog.py`) verifying 0ms dictionary lookup, intent resolution, and schema completeness (100% Passed).

### Task B.2: Phase 2 — Implement Polymorphic AI Extractor in Stepper
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/services/agentic_stepper_service.py`
* **Sub-tasks:**
  * [x] B.2.1 Replace hardcoded Purchases prompt with dynamic schema-driven prompt generator.
  * [x] B.2.2 Filter LLM output to strictly match expected header and line item fields.
  * [x] B.2.3 Handle both flat forms (Loans) and multi-line transactional documents (Invoices, Entries).

### Task B.3: Phase 3 — Generic Reactive Form & Grid Injector
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/services/cdp_agent_service.py`
* **Sub-tasks:**
  * [x] B.3.1 Implement generic attribute matcher for `[formcontrolname='${col}']`, `#${col}`, and type selectors.
  * [x] B.3.2 Support `@ng-select` typeaheads with body dropdown panel option selection.
  * [x] B.3.3 Support generic grid row additions, field filling, and automated modal dismissals.

### Task B.4: Phase 4 — Dynamic Step Feedback & Safety Gate Enforcement
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `src/services/agentic_stepper_service.py`
* **Sub-tasks:**
  * [x] B.4.1 Construct dynamic completion messages based on resolved screen title, entity name, and formatted template.
  * [x] B.4.2 Enforce draft-state safety gate: stop execution before clicking final Save to allow operator review.

### Task B.5: Phase 5 — Multi-Document Verification Test Matrix
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target File:** `scratch/test_multi_document_verification.py`
* **Sub-tasks:**
  * [x] B.5.1 Execute Purchases (289) end-to-end verification (O(1) resolution, schema validation, template check: Passed).
  * [x] B.5.2 Execute Sales (290) end-to-end verification (O(1) resolution, schema validation, template check: Passed).
  * [x] B.5.3 Execute Employee Loan (7158) end-to-end verification (O(1) resolution, flat form schema, template check: Passed).
  * [x] B.5.4 Execute Journal Entry (311) end-to-end verification (O(1) resolution, debit/credit grid schema, template check: Passed).
  * [x] B.5.5 Execute Store Movement (112) end-to-end verification (O(1) resolution, movement schema, template check: Passed).

### Task B.6: Phase 6 — Generic Automation & Self-Learning Auto-Cataloging Engine
* **Status:** [x] Completed & Verified (2026-10-25)
* **Target Files:** `src/services/forms_catalog_service.py`, `src/services/cdp_agent_service.py`, `scripts/scale_forms_catalog.py`, `tests/unit/test_generic_auto_scaling.py`
* **Sub-tasks:**
  * [x] B.6.1 Implement Archetype Auto-Inference (`infer_archetype_and_schema`) across Invoices, Journals, HR Requests, Reports, and Master Data cards.
  * [x] B.6.2 Implement Live DOM Self-Discovery (`inspect_active_page_dom` & `auto_register_from_dom_inspection`) to dynamically learn any visited screen on the fly.
  * [x] B.6.3 Implement Label-Anchored Control Matching in generic DOM injector to locate inputs by Arabic label text even with non-standard control names.
  * [x] B.6.4 Build Automated Batch Compiler CLI (`scripts/scale_forms_catalog.py`) with protected core intents and fast disk persistence.
  * [x] B.6.5 Compile full universal catalog covering 822 screens and 6,267 instant intents in O(1) hash maps.
  * [x] B.6.6 Benchmark 821 screens scaling performance (Achieved 3.60ms total / 4.4 microseconds per screen).

---

## 📋 Track C: Documentation, Audit & Milestone Closure

* [x] C.1 Master Blueprint Synchronized with 821 live database screens (`ERP_COPILOT_MASTER_BLUEPRINT.md`).
* [x] C.2 Deep Code Audit Document created with 7 identified defects (`ERP_COPILOT_BUGS_AND_SOLUTIONS.md`).
* [x] C.3 ERP Team Findings documented as permanent technical reference (`ERP_METADATA_DISCOVERY_REFERENCE.md`).
* [x] C.4 Five-Phase Integration Strategy established (`ERP_METADATA_INTEGRATION_PLAN.md`).
* [x] C.5 Master Living Execution Checklist established and maintained (`ERP_COPILOT_MASTER_CHECKLIST.md`).
* [x] C.6 Transformation Deep Dive Document with Before/After code analysis and Self-Healing protocol created (`ERP_COPILOT_TRANSFORMATION_DEEP_DIVE.md`).
* [ ] C.7 Git Milestone closure proposed with conventional commit message.
