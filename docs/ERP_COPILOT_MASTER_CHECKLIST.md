# DynamicPro ERP Co-Pilot — Master Living Execution Checklist

**Document Version:** 1.1.0  
**Classification:** Living Project Control & Task Tracking Ledger  
**Author:** Tech Lead & Antigravity Agent  
**Date:** 2026-11-01  
**Synchronized With:**
* [ERP_COPILOT_MASTER_BLUEPRINT.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_COPILOT_MASTER_BLUEPRINT.md)
* [ERP_COPILOT_BUGS_AND_SOLUTIONS.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_COPILOT_BUGS_AND_SOLUTIONS.md)
* [ERP_METADATA_INTEGRATION_PLAN.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_METADATA_INTEGRATION_PLAN.md)
* [ERP_METADATA_DISCOVERY_REFERENCE.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/docs/ERP_METADATA_DISCOVERY_REFERENCE.md)
* [comprehensive_status_report_and_architecture_guide.md](file:///C:/Users/EGY%20DYNAMIC/.gemini/antigravity-ide/brain/c77ecb53-302d-4229-9983-0d42683fcffe/comprehensive_status_report_and_architecture_guide.md)

---

## 📌 Instructions for Living Updates
1. Every task is marked `[ ]` (Pending), `[-]` (In Progress), or `[x]` (Completed & Verified).
2. After completing every individual step, this checklist must be immediately updated.
3. Newly discovered tasks, edge cases, or sub-steps must be appended under the relevant track.
4. Per user constraint, this tracking ledger maintains a structured outline format without tables.

---

## 🚦 Global Status Overview

* **Current Stage:** Phase 7 Live Field Pilot Observations & Quality Remediation (Pending User Approval)
* **Active Running Infrastructure:**
  * Python FastAPI AI Engine (Port 8000)
  * .NET 10 LMS Backend (Port 5115)
  * Angular 19 LMS UI (Port 4200)
  * Microsoft DevTunnel CDP Bridge (Port 9222 -> Port 443 HTTPS/WSS via `xhfmws6g-9222.eun1.devtunnels.ms`)
* **Overall Completion:** 15 / 22 Major Milestones Completed (Tracks A, B, C complete; Track D planned)

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

---

## 📋 Track D: Live Field Pilot Observations & Precision Remediation (2026-11-01)

### Task D.1: Enforce Strict Exact-Match Priority in `ng-select` Typeahead Driver
* **Status:** [x] Completed & Verified (2026-11-01)
* **Target File:** `learn-dynamic-pro-ui/src/app/core/services/form-driver/control-interactor.ts`
* **Defect Resolved:** In `session_session_20261101_141950_tnkf.log` (Line 16), selecting `طريقة البيع مباشرة` picked `مبيعات غير مباشرة`.
* **Implementation Details:**
  * [x] D.1.1 Extracted pure function `pickBestOption(options, term)` prioritizing strict string equality (`cleanTerm === optText`).
  * [x] D.1.2 Added negation penalty: if `cleanTerm` lacks `غير`, any candidate option containing `غير` (e.g. `مبيعات غير مباشرة`) is disqualified.
  * [x] D.1.3 Integrated `pickBestOption` into `setNgSelect` before executing click selection.

### Task D.2: Support Dynamic Cash-Paid & Total Settlement Auto-Population
* **Status:** [x] Completed & Verified (2026-11-01)
* **Target Files:** `src/core/prompts.py`, `src/services/agentic_stepper_service.py`, `src/data/forms_metadata.json`, `learn-dynamic-pro-ui/src/app/core/services/form-driver/form-inspector.ts`, `learn-dynamic-pro-ui/src/app/core/services/erp-form-driver.service.ts`
* **Defect Resolved:** In `y6p6.log`, cash settlement field `POPaid` remained blank because footer label `.dp-edit__totlbl` was unmapped.
* **Implementation Details:**
  * [x] D.2.1 Created unified `ERP_PAYMENT_RULES` defining `$TOTAL` assignment for numeric payment fields (`POPaid`, `CashPaid`, `المدفوع نقداً`) and preventing `$TOTAL` on treasury dropdowns (`SafeAccounId`).
  * [x] D.2.2 Injected `ERP_PAYMENT_RULES` into both `ERP_FORM_EXTRACTION_PROMPT_TEMPLATE` and `agentic_stepper_service.py` extraction prompt.
  * [x] D.2.3 Enriched screen 244 (Sales Invoices) schema in `forms_metadata.json` with concrete keys: `customerID, ContractType, CostItemId, StoreID, SalesMan, POPaid`, and grid `product, Qty, UnitPrice`.
  * [x] D.2.4 Updated `findLabelForElement` in `form-inspector.ts` to inspect `.dp-edit__totlbl` on sibling/parent containers so `POPaid` maps to `"المحصل نقدا"`.
  * [x] D.2.5 Added explicit `input[name="POPaid" i]` and `input[name*="popaid" i]` to `paidSelectors` in `erp-form-driver.service.ts`.
  * [x] D.2.6 Verified with unit tests in `tests/unit/test_extraction_prompts.py` (3 passed).

### Task D.3: Harden Host Bridge & Enforce Safe Draft Policy
* **Status:** [x] Completed & Verified (2026-11-01)
* **Target Files:** `learn-dynamic-pro-ui/src/app/core/services/erp-bridge.service.ts`
* **Defect Resolved:** In `tnkf.log` (Line 185), `submitActiveForm` threw `TypeError` because host bridge lacked this function.
* **Implementation Details:**
  * [x] D.3.1 Guarded `submitActiveForm` with `typeof (window.DynamicERP as any)?.submitActiveForm !== 'function'`.
  * [x] D.3.2 Returns clean `ErpSaveResult` with Arabic guidance: *"الحفظ التلقائي غير مدعوم في هذه النسخة من النظام. يرجى مراجعة البيانات والضغط على زر الحفظ يدوياً."* without throwing or breaking UI flow.
  * [x] D.3.3 Enterprise Draft-State Safety Gate enforced: manual user click is required to save.

### Task D.4: Reset Grid Rows & Form Context Prior to Re-filling
* **Status:** [x] Completed & Verified (2026-11-01)
* **Target File:** `learn-dynamic-pro-ui/src/app/core/services/erp-form-driver.service.ts`
* **Defect Resolved:** In `tnkf.log` (Line 66), re-applying prompt in an open form appended duplicate rows into `dataObject.rows`.
* **Implementation Details:**
  * [x] D.4.1 Inspected `activeCtx.rows` before calling `this.bridge.fillFormData`. If dirty/populated items already exist, pass `rows: []` to prevent host-side row duplication.
  * [x] D.4.2 In-DOM row driver updates rows in-place at indices `rIdx`, avoiding creation of extra rows.

### Task D.5: Resolve 244 vs 290 Intent Conflict in Metadata Catalogs
* **Status:** [x] Completed & Verified (2026-11-01)
* **Target Files:** `src/data/screens_metadata.json`, `src/data/forms_metadata.json`
* **Defect Resolved:** Sales invoice intents erroneously mapped to Page 290 (Store Transfers) instead of Page 244 (Sales Invoices).
* **Implementation Details:**
  * [x] D.5.1 Enriched Page 244 in `screens_metadata.json` with all sales aliases and intents.
  * [x] D.5.2 Stripped all sales aliases from Page 290 in `screens_metadata.json` and restored warehouse transfer metadata.
  * [x] D.5.3 Re-mapped `"المبيعات"` and sales intents in `forms_metadata.json` to 244 and added standalone `"تحويلات المخازن": 290`.
  * [x] D.5.4 Verified with unit tests in `tests/unit/test_forms_resolution.py` (2 passed).

### Task D.6: Comprehensive Decoupling of Pure Q&A Mode from Action & Execution Mode
* **Status:** [x] Completed & Verified (2026-11-01)
* **Target Files:**
  * UI Template: `learn-dynamic-pro-ui/src/app/shared/components/copilot-chat/copilot-chat.component.html`
  * UI Logic: `learn-dynamic-pro-ui/src/app/shared/components/copilot-chat/copilot-chat.component.ts`
  * UI Styles: `learn-dynamic-pro-ui/src/app/shared/components/copilot-chat/copilot-chat.component.css`
  * System Prompts: `src/core/prompts.py`
  * Search / RAG Service: `src/services/search_service.py`
  * Production Bundle: `learn-dynamic-pro-ui/public/lms-copilot.bundle.js`
* **Implementation Details:**
  * [x] D.6.1 Added `isActionMode: boolean = false` (default Q&A mode). Mutually exclusive with `isVisionAgentMode`.
  * [x] D.6.2 Added mode badge indicator above chat footer and action mode toggle button `⚡` with active highlight.
  * [x] D.6.3 Dynamic placeholder based on mode (Q&A: lecture questions / Action: command execution / Vision: CDP goal).
  * [x] D.6.4 In `streamQuery`, if `!isActionMode`, completely bypass navigation (`resolveAndNavigate`), bypass `prepareFreshForm`, pass `visibleFields = undefined`, `formSchema = undefined`, force `resolvedIntent = 'question'`, and disable `canEscalateToVisionAgent`.
  * [x] D.6.5 Added Directive 7 (Procedural & How-To Guidance) in `_RAW_RAG_SYSTEM_PROMPT` instructing Gemini to answer procedural questions educationally without referencing action cards.
  * [x] D.6.6 Removed dead `extracted_form_fields` parameter and branch from `prompts.py` and `search_service.py`.
  * [x] D.6.7 Verified with unit tests in `tests/unit/test_rag_prompt.py` (2 passed), `test_citations_and_sources.py` (9 passed), and `test_multi_lesson_search.py` (6 passed).
  * [x] D.6.8 Built production bundle via `npm run build:element` -> `public/lms-copilot.bundle.js` (661.3 KB).

---

## 📋 Track E: Scaled Forms Catalog & Ground-Truth Metadata Architecture (2026-11-02)

### Task E.1: Phase 1 — Scaler Logic Hardening & Intent Alignment (`scale_forms_catalog.py`)
* **Status:** [x] Completed & Verified (2026-11-02)
* **Target Files:**
  * Scaler Script: `scripts/scale_forms_catalog.py`
  * Ground-Truth Compiler: `scripts/compile_ground_truth_catalog.py`
  * Unit Tests: `tests/unit/test_forms_catalog.py`
* **Objective:** Clean internal hardcoded dictionaries and protect curated schemas from being overwritten by auto-scaled heuristics.
* **Implementation Details:**
  * [x] E.1.1 Re-mapped sales intent dictionary (`"فاتورة مبيعات"`, `"فاتورة المبيعات"`, `"فواتير المبيعات"`, `"فاتورة بيع"`, `"تسجيل مبيعات"`) strictly to Page `244` (Sales Invoices) instead of `290`.
  * [x] E.1.2 Assigned `"تحويلات المخازن"` and warehouse movements strictly to Page `290` and `112`.
  * [x] E.1.3 Hardened handcrafted schema filter (`CORE_CURATED_PIDS = {289, 290, 7158, 311, 112, 244}`) to guarantee retention of enriched controls (`customerID`, `POPaid`, `VendorID`, etc.).
  * [x] E.1.4 Verified resolution and retention logic via unit tests in `tests/unit/test_forms_catalog.py` (5 passed).

### Task E.2: Phase 2 — Dry-Run Diagnostic & Archetype Benchmark Verification
* **Status:** [x] Completed & Verified (2026-11-02)
* **Target Files:** `scripts/compile_ground_truth_catalog.py`
* **Objective:** Perform safe zero-write simulation to validate archetype distribution and intent resolution without mutating disk state.
* **Implementation Details:**
  * [x] E.2.1 Executed `python scripts/compile_ground_truth_catalog.py --dry-run`.
  * [x] E.2.2 Verified terminal output metrics:
    * Total screens processed equals 822.
    * Core curated operational screens: 6 screens (IDs: [112, 244, 289, 290, 311, 7158]).
    * Ground-truth database schemas: 616 screens (74.9%).
    * Verified report/inquiry views: 200 screens (24.3%).
    * Processing duration: 316.00ms (< 400 μs/screen).
  * [x] E.2.3 Confirmed zero modifications to `src/data/forms_metadata.json` during dry-run.

### Task E.3: Phase 3 — Controlled Compilation & Catalog Regression Suite Execution
* **Status:** [x] Completed & Verified (2026-11-02)
* **Target Files:**
  * Catalog File: `src/data/forms_metadata.json`
  * Unit Tests: `tests/unit/test_forms_catalog.py`, `tests/unit/test_forms_resolution.py`, `tests/unit/test_extraction_prompts.py`, `tests/unit/test_generic_auto_scaling.py`
* **Objective:** Persist compiled universal catalog and execute full regression test suite to ensure zero breaking changes across pilot features.
* **Implementation Details:**
  * [x] E.3.1 Executed `python scripts/compile_ground_truth_catalog.py --compile` to generate production `forms_metadata.json`.
  * [x] E.3.2 Created automatic safety backup at `src/data/forms_metadata_backup_1793616014.json`.
  * [x] E.3.3 Ran targeted pytest suite across catalog, prompt, and resolution contracts (`10 passed in 0.64s`).
  * [x] E.3.4 Ran full pytest suite across `LMS_CO_Pilot` (`90 passed, 0 failures`).
  * [x] E.3.5 Verified TypeScript compilation across `learn-dynamic-pro-ui` (`npx tsc --noEmit` exited clean 0).

### Task E.4: Phase 4 — Ground-Truth SQL `ListSetups` & Structure API Ingestion Pipeline
* **Status:** [x] Completed & Verified (2026-11-02)
* **Target Files:**
  * Ingestion Data: `Listsetups.json`, `pageAttribute.json`, `pdetail.json`, `pages.json`, `modul.json`, `menumaster.json`
  * Production Compiler: `scripts/compile_ground_truth_catalog.py`
  * Output Schema Catalog: `src/data/forms_metadata.json`
* **Objective:** Transition from heuristic archetype inference to 100% ground-truth database schemas extracted from host ERP.
* **Implementation Details:**
  * [x] E.4.1 Ingested complete raw SQL Server metadata datasets: 7,206 field setups (`Listsetups.json`), 950 page definitions (`pages.json`), 32 ERP modules (`modul.json`), 188 menus (`menumaster.json`), and 417 grid structures (`pdetail.json`).
  * [x] E.4.2 Ingested verified physical column names (`ColumnName`), Arabic labels (`arColumnLabel`), exact control types (`InsertType`), and mandatory flags (`IsRquired`).
  * [x] E.4.3 Successfully mapped and persisted exact database-bound schemas for 616 screens and report view schemas for 200 screens in `src/data/forms_metadata.json`.


