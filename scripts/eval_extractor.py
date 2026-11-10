"""Live Gemini Baseline Evaluator with Hard/Soft Split & Run-Stability Detection.

Evaluates each Golden Set case 3 times at temperature=0.0 against Gemini without
altering production extraction code. Prints a table with separate Hard and Soft
pass rates plus cross-run stability diagnostics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google import genai

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.config import settings
from src.services.cognitive_search.search.erp_action_extractor import (
    build_form_fill_payload,
    extract_form_fields_if_needed,
    resolve_and_enrich_erp_action_schema,
)

DEFAULT_CASES_PATH = ROOT_DIR / "tests" / "golden" / "cases.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "downloads" / "eval_extractor_results.json"

TREASURY_KEYS_LOWER = {"safeaccounid", "safeaccount", "safeaccountid"}
ROW_PRODUCT_ALIASES = ["اسم المنتج", "product", "ProductID", "ProName", "item"]
ROW_QTY_ALIASES = ["الكمية", "الكميه", "Qty", "productQty", "Quntity", "quantity"]
ISO_CODES = {"EGP", "USD", "EUR", "EURO", "SAR"}

INSTRUCTION_LEAK_PHRASES = [
    "بجوار المنتج",
    "مع المنتج فقط",
    "مطلوب نقله",
    "إلى السطر",
    "الى السطر",
    "تحت مع",
    "من فوق",
    "تم السداد بالكامل",
    "حسب الفاتورة",
    "انظر الجدول",
]


def _norm_arabic(text: Any) -> str:
    s = str(text or "").strip().lower()
    s = re.sub(r"[إأآا]", "ا", s)
    s = re.sub(r"ى", "ي", s)
    s = re.sub(r"ة", "ه", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _soft_name_match(expected_val: Any, actual_val: Any) -> bool:
    """Normalized exact or bi-directional substring match ('خامات' <-> 'مخزن خامات')."""
    if expected_val is None:
        return actual_val is None
    if expected_val == "$TOTAL":
        return str(actual_val or "").strip().upper() == "$TOTAL"
    if isinstance(expected_val, (int, float)):
        try:
            return float(actual_val) == float(expected_val)
        except (TypeError, ValueError):
            return False
    exp_str = str(expected_val).strip()
    if exp_str.upper() in ISO_CODES:
        return str(actual_val or "").strip().upper() == exp_str.upper()
    # Date string exact match
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp_str):
        return str(actual_val or "").strip() == exp_str

    exp_n = _norm_arabic(exp_str)
    act_n = _norm_arabic(actual_val)
    if not exp_n or not act_n:
        return False
    if exp_n == act_n:
        return True
    if len(exp_n) >= 2 and len(act_n) >= 2:
        return exp_n in act_n or act_n in exp_n
    return False


def _find_matching_field(
    fields: dict[str, Any],
    canon_key: str,
    aliases: list[str],
) -> tuple[str | None, Any]:
    candidates = [canon_key] + [a for a in aliases if a != canon_key]
    lower_map = {str(k).strip().lower(): (k, v) for k, v in fields.items()}
    for cand in candidates:
        hit = lower_map.get(cand.strip().lower())
        if hit is not None:
            return hit
    return None, None


def _collect_allowed_schema_keys(case: dict[str, Any], effective_schema: list[dict] | None) -> set[str]:
    allowed: set[str] = set()
    for sf in (effective_schema or case.get("form_schema") or []):
        if isinstance(sf, dict):
            for kfield in ("key", "name"):
                v = sf.get(kfield)
                if v:
                    allowed.add(str(v).strip().lower())
    return allowed


def _detect_instruction_leaks(
    act_fields: dict[str, Any],
    act_rows: list[Any],
    extra_placeholders: list[str],
) -> list[str]:
    leaks: list[str] = []
    phrases = [_norm_arabic(p) for p in INSTRUCTION_LEAK_PHRASES + extra_placeholders if p]

    for k, v in act_fields.items():
        nv = _norm_arabic(v)
        if any(p in nv for p in phrases):
            leaks.append(f"leak_field:{k}={v!r}")
    for idx, r in enumerate(act_rows, 1):
        if isinstance(r, dict):
            for k, v in r.items():
                nv = _norm_arabic(v)
                if any(p in nv for p in phrases):
                    leaks.append(f"leak_r{idx}:{k}={v!r}")
    return leaks


def evaluate_single_run(
    case: dict[str, Any],
    raw_extracted: dict[str, Any],
    effective_schema: list[dict] | None,
) -> tuple[bool, bool, bool, list[str], list[str], str | None]:
    """
    Evaluate one run into independent Hard, Soft, and Action-Intent outcomes:
    - Hard: valid JSON, batch_mode, allowed schema keys (no unallowed/forbidden keys, no $TOTAL on safe),
            row count, numeric quantities/amounts, and zero instruction-text leakage.
    - Soft: entity/enum/currency name matching using Arabic normalization + containment.
    - Intent: raw_extracted.get("intent") matches expected["action_intent"] ('new' | 'edit_current').
    """
    expected = case["expected"]
    hard_issues: list[str] = []
    soft_issues: list[str] = []

    expected_intent = expected.get("action_intent")
    if expected_intent:
        act_intent = (
            str(raw_extracted.get("action_intent") or raw_extracted.get("intent") or "").strip().lower()
            if isinstance(raw_extracted, dict)
            else ""
        )
        intent_ok = act_intent == expected_intent
        intent_issue = None if intent_ok else f"intent:{act_intent or 'MISSING'}!={expected_intent}"
    else:
        intent_ok = True
        intent_issue = None

    if not isinstance(raw_extracted, dict) or not raw_extracted:
        return False, False, intent_ok, ["empty_or_invalid_json"], ["empty_or_invalid_json"], intent_issue

    act_batch = bool(raw_extracted.get("batch_mode", False))
    act_fields = raw_extracted.get("fields") if isinstance(raw_extracted.get("fields"), dict) else {}
    act_rows = raw_extracted.get("rows") if isinstance(raw_extracted.get("rows"), list) else []

    placeholders = expected.get("reject_literal_placeholders", [])

    # Expected failure cases (e.g., stateful header-to-grid edit commands)
    if case.get("expected_failure"):
        leaks = _detect_instruction_leaks(act_fields, act_rows, placeholders)
        target_col = expected.get("actionable_grid_column", "المشـــروع")
        has_clear_header = any(
            str(k).strip().lower() == "projectid" and v is None
            for k, v in act_fields.items()
        )
        has_clean_grid_project = bool(act_rows) and all(
            isinstance(r, dict)
            and target_col in r
            and r[target_col] not in (None, "")
            and not _detect_instruction_leaks({}, [r], placeholders)
            for r in act_rows
        )
        if not leaks and has_clear_header and has_clean_grid_project:
            return True, True, intent_ok, [], [], intent_issue
        hard_issues.extend(leaks)
        if not has_clear_header or not has_clean_grid_project:
            hard_issues.append(f"unactionable_edit(fields={list(act_fields.keys())},rows={len(act_rows)})")
        soft_issues.append("unactionable_edit")
        return False, False, intent_ok, hard_issues, soft_issues, intent_issue

    # ─── HARD CHECKS ─────────────────────────────────────────────────────────────
    if act_batch != bool(expected.get("batch_mode", False)):
        hard_issues.append(f"batch_mode={act_batch}")

    allowed_schema_keys = _collect_allowed_schema_keys(case, effective_schema)
    forbidden_lower = {fk.strip().lower() for fk in expected.get("forbidden_keys", [])}

    for k, v in act_fields.items():
        kl = str(k).strip().lower()
        if kl in forbidden_lower:
            hard_issues.append(f"forbidden_key:{k}")
        elif allowed_schema_keys and kl not in allowed_schema_keys:
            hard_issues.append(f"off_schema_key:{k}")
        if kl in TREASURY_KEYS_LOWER and str(v).strip().upper() == "$TOTAL":
            hard_issues.append(f"$TOTAL_on_treasury:{k}")

    # Instruction leakage check
    hard_issues.extend(_detect_instruction_leaks(act_fields, act_rows, placeholders))

    aliases_map = expected.get("field_aliases", {})
    allow_either = set(expected.get("allow_header_or_row_keys", []))

    for exp_k, exp_v in expected.get("fields", {}).items():
        aliases = aliases_map.get(exp_k, [])
        found_k, found_v = _find_matching_field(act_fields, exp_k, aliases)
        if found_k is None and exp_k in allow_either and act_rows and isinstance(act_rows[0], dict):
            found_k, found_v = _find_matching_field(act_rows[0], exp_k, aliases)

        if found_k is None:
            hard_issues.append(f"missing_key:{exp_k}")
            soft_issues.append(f"missing_val:{exp_k}")
        else:
            if isinstance(exp_v, (int, float)):
                try:
                    if float(found_v) != float(exp_v):
                        hard_issues.append(f"num_mismatch:{found_k}={found_v!r}!={exp_v!r}")
                except (TypeError, ValueError):
                    hard_issues.append(f"non_numeric:{found_k}={found_v!r}")
            elif exp_v == "$TOTAL" and str(found_v or "").strip().upper() != "$TOTAL":
                hard_issues.append(f"expected_$TOTAL:{found_k}={found_v!r}")
            elif not _soft_name_match(exp_v, found_v):
                soft_issues.append(f"soft_mismatch:{found_k}={found_v!r}!={exp_v!r}")

    # Row checks
    exp_rows = expected.get("rows", [])
    allowed_row_keys = allowed_schema_keys | {k.lower() for k in ROW_PRODUCT_ALIASES + ROW_QTY_ALIASES}

    if len(act_rows) != len(exp_rows):
        hard_issues.append(f"rows_count:{len(act_rows)}!={len(exp_rows)}")
        if exp_rows:
            soft_issues.append(f"rows_count:{len(act_rows)}!={len(exp_rows)}")
    else:
        for idx, (er, ar) in enumerate(zip(exp_rows, act_rows), 1):
            if not isinstance(ar, dict):
                hard_issues.append(f"r{idx}:not_dict")
                soft_issues.append(f"r{idx}:not_dict")
                continue

            for rk in ar.keys():
                if rk.strip().lower() not in allowed_row_keys:
                    hard_issues.append(f"r{idx}:off_schema_row_key:{rk}")

            for ek, ev in er.items():
                if ek in ROW_PRODUCT_ALIASES:
                    r_aliases = ROW_PRODUCT_ALIASES
                elif ek in ROW_QTY_ALIASES:
                    r_aliases = ROW_QTY_ALIASES
                else:
                    r_aliases = [ek]

                fk, fv = _find_matching_field(ar, ek, r_aliases)
                if fk is None and ek in allow_either:
                    fk, fv = _find_matching_field(act_fields, ek, r_aliases)

                if fk is None:
                    if isinstance(ev, (int, float)) or ek in ROW_QTY_ALIASES:
                        hard_issues.append(f"r{idx}:missing_qty_or_num:{ek}")
                    else:
                        hard_issues.append(f"r{idx}:missing_row_key:{ek}")
                        soft_issues.append(f"r{idx}:missing_row_val:{ek}")
                else:
                    if isinstance(ev, (int, float)):
                        try:
                            if float(fv) != float(ev):
                                hard_issues.append(f"r{idx}:qty_mismatch:{fk}={fv!r}!={ev!r}")
                        except (TypeError, ValueError):
                            hard_issues.append(f"r{idx}:non_numeric:{fk}={fv!r}")
                    elif not _soft_name_match(ev, fv):
                        soft_issues.append(f"r{idx}:soft_mismatch:{fk}={fv!r}!={ev!r}")

    return len(hard_issues) == 0, len(soft_issues) == 0, intent_ok, hard_issues, soft_issues, intent_issue


async def _throttled_extract(
    client: genai.Client,
    case: dict[str, Any],
    effective_fields: list[str] | None,
    effective_schema: list[dict[str, Any]] | None,
    call_timestamps: list[float],
    rate_lock: asyncio.Lock,
    max_rpm: int = 12,
    window_sec: float = 63.0,
) -> tuple[dict[str, Any], float]:
    """Invoke live Gemini extraction respecting RPM limits (429/503 retries run inside extract_form_fields_if_needed)."""
    async with rate_lock:
        now = time.monotonic()
        call_timestamps[:] = [ts for ts in call_timestamps if now - ts < window_sec]
        if len(call_timestamps) >= max_rpm:
            wait_for = window_sec - (now - call_timestamps[0]) + 0.5
            if wait_for > 0:
                print(f"[rate-limit guard] sleeping {wait_for:.1f}s to respect {max_rpm} RPM...", flush=True)
                await asyncio.sleep(wait_for)
            now = time.monotonic()
            call_timestamps[:] = [ts for ts in call_timestamps if now - ts < window_sec]
        call_timestamps.append(time.monotonic())

    t0 = time.perf_counter()
    raw = await extract_form_fields_if_needed(
        gemini_client=client,
        query=case["query"],
        visible_fields=effective_fields,
        form_schema=effective_schema,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return raw, elapsed_ms


async def run_evaluation(
    cases_path: Path,
    runs: int,
    max_rpm: int = 12,
    output_path: Path | None = DEFAULT_OUTPUT_PATH,
) -> int:
    data = json.loads(cases_path.read_text(encoding="utf-8"))
    cases = data["cases"]
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    call_timestamps: list[float] = []
    rate_lock = asyncio.Lock()

    print(
        f"Model: {settings.GEMINI_MODEL} | Temperature: 0.0 | Runs/Case: {runs} | "
        f"Cases: {len(cases)} | Throttle: <= {max_rpm} RPM\n",
        flush=True,
    )

    results_rows: list[dict[str, Any]] = []
    raw_cases_results: list[dict[str, Any]] = []
    for idx, case in enumerate(cases, 1):
        effective_fields, effective_schema, resolved_key, resolved_pid, resolved_doc = resolve_and_enrich_erp_action_schema(
            query=case["query"],
            visible_fields=None,
            form_schema=case["form_schema"],
            erp_key=case["erp_key"],
        )

        hard_pass = 0
        soft_pass = 0
        intent_pass = 0
        latencies: list[float] = []
        hard_notes: list[str] = []
        soft_notes: list[str] = []
        intent_notes: list[str] = []
        raw_fingerprints: set[str] = set()
        run_entries: list[dict[str, Any]] = []

        run_results = await asyncio.gather(
            *[
                _throttled_extract(
                    client=client,
                    case=case,
                    effective_fields=effective_fields,
                    effective_schema=effective_schema,
                    call_timestamps=call_timestamps,
                    rate_lock=rate_lock,
                    max_rpm=max_rpm,
                )
                for _ in range(runs)
            ]
        )

        for run_idx, (raw, elapsed_ms) in enumerate(run_results, 1):
            latencies.append(elapsed_ms)
            payload = build_form_fill_payload(
                raw_extracted=raw,
                screen_key=resolved_key,
                page_id=resolved_pid,
                document_name=resolved_doc,
                schema=effective_schema,
            )
            eval_obj = (
                {
                    "intent": payload["action_intent"],
                    "batch_mode": payload["batch_mode"],
                    "fields": payload["fields"],
                    "rows": payload["rows"],
                }
                if payload is not None
                else raw
            )
            raw_fingerprints.add(json.dumps(eval_obj, ensure_ascii=False, sort_keys=True))
            h_ok, s_ok, i_ok, h_issues, s_issues, i_issue = evaluate_single_run(case, eval_obj, effective_schema)
            run_entries.append({
                "run": run_idx,
                "latency_ms": round(elapsed_ms, 2),
                "hard_ok": h_ok,
                "soft_ok": s_ok,
                "intent_ok": i_ok,
                "hard_issues": h_issues,
                "soft_issues": s_issues,
                "intent_issue": i_issue,
                "raw_llm": raw,
                "payload": payload,
            })
            if h_ok:
                hard_pass += 1
            else:
                for x in h_issues:
                    if x not in hard_notes:
                        hard_notes.append(x)
            if s_ok:
                soft_pass += 1
            else:
                for x in s_issues:
                    if x not in soft_notes:
                        soft_notes.append(x)
            if i_ok:
                intent_pass += 1
            elif i_issue and i_issue not in intent_notes:
                intent_notes.append(i_issue)

        raw_cases_results.append({
            "id": case["id"],
            "origin": "synthetic" if case.get("synthetic") else "log",
            "expected_failure": bool(case.get("expected_failure")),
            "erp_key": case["erp_key"],
            "page_id": case.get("page_id"),
            "query": case["query"],
            "expected": case["expected"],
            "runs": run_entries,
        })

        is_exp_fail = bool(case.get("expected_failure"))
        variants_cnt = len(raw_fingerprints)
        is_score_flaky = (0 < hard_pass < runs) or (0 < soft_pass < runs) or (0 < intent_pass < runs)
        is_unstable = is_score_flaky or variants_cnt > 1

        if is_exp_fail:
            stability = f"XFAIL ({variants_cnt}v)" if variants_cnt > 1 else "XFAIL (stable)"
        elif is_unstable:
            stability = f"UNSTABLE ({variants_cnt} variants)"
        else:
            stability = "STABLE"

        avg_ms = round(sum(latencies) / len(latencies)) if latencies else 0
        diag_parts = []
        if hard_notes:
            diag_parts.append("Hard: " + ", ".join(hard_notes))
        if soft_notes:
            diag_parts.append("Soft: " + ", ".join(soft_notes))
        if intent_notes:
            diag_parts.append("Intent: " + ", ".join(intent_notes))
        diag_str = " | ".join(diag_parts) if diag_parts else "OK"

        row = {
            "idx": idx,
            "id": case["id"],
            "origin": "synthetic" if case.get("synthetic") else "log",
            "exp_fail": "YES" if is_exp_fail else "NO",
            "hard_score": f"{hard_pass}/{runs}",
            "soft_score": f"{soft_pass}/{runs}",
            "intent_score": f"{intent_pass}/{runs}",
            "hard_pass": hard_pass,
            "soft_pass": soft_pass,
            "intent_pass": intent_pass,
            "stability": stability,
            "is_unstable": is_unstable,
            "variants": variants_cnt,
            "avg_ms": avg_ms,
            "diag": diag_str,
        }
        results_rows.append(row)
        print(
            f"Done [{idx}/{len(cases)}] {row['id']} -> Hard {row['hard_score']} | Soft {row['soft_score']} | Intent {row['intent_score']} | {row['stability']} ({row['avg_ms']}ms)",
            flush=True,
        )

    print("\n| # | Case ID | Origin | ExpFail | Hard | Soft | Intent | Stability | Avg ms | Diagnostics |")
    print("| :-: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |")
    for row in results_rows:
        print(
            f"| {row['idx']} | {row['id']} | {row['origin']} | {row['exp_fail']} "
            f"| {row['hard_score']} | {row['soft_score']} | {row['intent_score']} | {row['stability']} | {row['avg_ms']} | {row['diag']} |"
        )

    normal_rows = [r for r in results_rows if r["exp_fail"] == "NO"]
    hard_fail_targets = [r for r in normal_rows if r["hard_pass"] < runs]
    intent_fail_targets = [r for r in results_rows if r["intent_pass"] < runs]
    unstable_cases = [r for r in results_rows if r["is_unstable"]]

    print("\n=== Hard / Soft / Intent Baseline Summary ===")
    print(f"Normal cases Hard 3/3: {sum(1 for r in normal_rows if r['hard_pass'] == runs)}/{len(normal_rows)}")
    print(f"Normal cases Soft 3/3: {sum(1 for r in normal_rows if r['soft_pass'] == runs)}/{len(normal_rows)}")
    print(f"All cases Intent 3/3: {sum(1 for r in results_rows if r['intent_pass'] == runs)}/{len(results_rows)}")
    print(f"Normal Hard run-level pass rate: {sum(r['hard_pass'] for r in normal_rows)}/{len(normal_rows) * runs}")
    print(f"Normal Soft run-level pass rate: {sum(r['soft_pass'] for r in normal_rows)}/{len(normal_rows) * runs}")
    print(f"All Intent run-level pass rate: {sum(r['intent_pass'] for r in results_rows)}/{len(results_rows) * runs}")
    print(f"Unstable cases across 3 runs (score flaky or >1 JSON variant): {len(unstable_cases)}/{len(results_rows)}")
    for u in unstable_cases:
        print(f"  - {u['id']}: Hard={u['hard_score']}, Soft={u['soft_score']}, Intent={u['intent_score']}, variants={u['variants']}")
    print(f"Hard failure improvement targets ({len(hard_fail_targets)}):")
    for hf in hard_fail_targets:
        print(f"  - {hf['id']}: Hard={hf['hard_score']} -> {hf['diag']}")
    print(f"Intent failure targets ({len(intent_fail_targets)}):")
    for itf in intent_fail_targets:
        print(f"  - {itf['id']}: Intent={itf['intent_score']} -> {itf['diag']}")

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_bundle = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "model": settings.GEMINI_MODEL,
            "temperature": 0.0,
            "runs_per_case": runs,
            "cases_count": len(cases),
            "summary": {
                "normal_cases": len(normal_rows),
                "normal_hard_3_of_3": sum(1 for r in normal_rows if r["hard_pass"] == runs),
                "normal_soft_3_of_3": sum(1 for r in normal_rows if r["soft_pass"] == runs),
                "all_intent_3_of_3": sum(1 for r in results_rows if r["intent_pass"] == runs),
                "normal_hard_run_pass": sum(r["hard_pass"] for r in normal_rows),
                "normal_hard_run_total": len(normal_rows) * runs,
                "normal_soft_run_pass": sum(r["soft_pass"] for r in normal_rows),
                "normal_soft_run_total": len(normal_rows) * runs,
                "all_intent_run_pass": sum(r["intent_pass"] for r in results_rows),
                "all_intent_run_total": len(results_rows) * runs,
            },
            "rows": results_rows,
            "cases": raw_cases_results,
        }
        output_path.write_text(json.dumps(raw_bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nSaved raw evaluation JSON to: {output_path}", flush=True)
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    parser = argparse.ArgumentParser(description="Live Baseline Evaluator (Hard/Soft split) for ERP Action Extractor.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH, help="Path to cases.json")
    parser.add_argument("--runs", type=int, default=3, help="Number of evaluations per case")
    parser.add_argument("--rpm", type=int, default=12, help="Max requests per minute throttle")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Path to write raw JSON results")
    args = parser.parse_args()
    return asyncio.run(run_evaluation(args.cases, max(1, args.runs), max(1, args.rpm), args.output))


if __name__ == "__main__":
    raise SystemExit(main())
