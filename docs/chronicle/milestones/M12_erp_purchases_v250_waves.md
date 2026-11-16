# Milestone 12: ERP Purchases v2.5.0 Entity Resolution, Wave 1–2 & Unified Telemetry

**Date Range:** 2026-10-13 -> 2026-11-16  
**Status:** ✅ WAVE 1 & WAVE 2 COMPLETED (Wave 3 `POPaidCurrancy` Planned)  
**Repositories:** `DynamicProLearn` (Widget) + `LMS_CO_Pilot` (FastAPI) + `Dynamicpro/FrontEnd` (Host Bridge)

---

## 1. The Core Tension
1. **Unverified Guessing vs Strict Lookup Resolution:** Early form-filling relied on raw LLM extraction or DOM heuristics, risking wrong IDs on Arabic lookups (`SupplierID`, `StoreID`, `ProjectID`, `SafeAccounId`) or silent failures on host dropdowns.
2. **Double Form Opening & Host Bridge Drift:** Saving an invoice left `getActiveScreen()` returning empty `screenKey`, master-list filter dropdowns (`*_gd`) triggered false open-form detection, and `fallbackModels.SafeAccounId` in Host Bridge pointed to `SafeAccount`/`AccID` instead of `MonyAccount`/`AcID` (causing a ~6.1s timeout per invoice).
3. **Eager Bundle Load & Telemetry Fragmentation:** `lms-copilot.bundle.js` (`829.3 KB` with duplicate `zone.js` and `Router`) loaded on ERP startup, while browser and backend logs lived in separate formats.

---

## 2. Decisions & Architecture
1. **Strict v2.5.0 Registry & Resolver (`DynamicProLearn`):**
   - Arabic normalization + strict exact/synonym matching (`PurchasesEntityResolverService`) that halts on ambiguity (`ambiguous`) instead of guessing.
   - Confirmed safe header execution order (`PURCHASES_SAFE_HEADER_ORDER`):
     `POSetting -> CurrancyID -> SupplierID -> StoreID -> ProjectID -> SafeAccounId`
   - YAGNI cleanup: removed speculative `altValueKeys`/`altTextKeys` after live CDP verification locked `ProjectID -> ProductNonInventory (ProID/ProName)` and `SafeAccounId -> MonyAccount (AcID/AcName)`.
2. **Host Bridge & Performance (`Dynamicpro/FrontEnd` + `DynamicProLearn`):**
   - `b651c2bb` & `67ed4858` (Host ERP): unified `fallbackModels.SafeAccounId` to `MonyAccount`/`AcID`, added `item.AcID`, and switched `lms-copilot.bundle.js` to lazy load on first click (`0ms` ERP boot impact).
   - Removed duplicate `zone.js` polyfill and `Router` injection from `lms-copilot.bundle.js`, shrinking bundle from `829.3 KB` to **`793.4 KB`** (`183.59 KB` transfer).
3. **Unified JSONL Blackbox Telemetry (`LMS_CO_Pilot`):**
   - Commit `2e969bd`: `/erp/telemetry` delegates to `session_telemetry.append_session_event` with `BROWSER.*` stage prefixes and `trace_id` correlation.

---

## 3. Verification Proof
- **Live Invoice Save (`session_20261116_160534_ey2x.jsonl`, `trc_khmdm2`):**
  - `POID: 13777` (`#241`) saved with `ProjectID: 36965`, `SafeAccounId: 7619`, single `triggerAddNew()`.
  - `selectLookup('SafeAccounId', 7619)` latency dropped from `~6.1s` to **`69ms`**; full 6-header + row fill completed in **`565ms`**.
- **Automated Checks:**
  - `tsc -p tsconfig.element.json --noEmit` & `tsc -p tsconfig.spec.json --noEmit`: Exit `0`
  - Karma ERP Copilot suite: **`104 / 104 SUCCESS`**
  - Backend unit tests (`test_erp_endpoints.py`, `test_session_telemetry_hierarchical.py`): **`18 / 18 passed`**

---

## 4. Next Planned Step
- **Wave 3 (`POPaidCurrancy`):** See canonical execution checklist in [ERP_COPILOT_ROADMAP.md](file:///e:/Mazen/DynamicProLearn/docs/ERP_COPILOT_ROADMAP.md).
