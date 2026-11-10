import json
import re
from collections import Counter
from pathlib import Path

logs_dir = Path("e:/Mazen/EgyDynamic/LMS_CO_Pilot/logs/erp_sessions")
session_logs = sorted(logs_dir.glob("session_*.log"), key=lambda p: p.stat().st_mtime)

toast_error_counter = Counter()
dom_missing_counter = Counter()
missing_field_records = []

# Sequential query records
all_queries = []


def extract_json(line: str):
    idx = line.find(" | {")
    if idx == -1:
        return None
    try:
        return json.loads(line[idx + 3 :])
    except Exception:
        return None


for p in session_logs:
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    current_trace_map = {}
    last_q_rec = None
    last_schema_global = None
    seq_in_file = 0

    for line_no, line in enumerate(lines, 1):
        trc_m = re.search(r"\[trc:(trc_[a-z0-9]+)\]", line)
        trc = trc_m.group(1) if trc_m else None

        # 1. Toast & Save Validation Errors + missingFields
        if "submitActiveForm()" in line or '"outcome": "failed"' in line or "missingFields" in line:
            data = extract_json(line)
            if isinstance(data, dict):
                res = data.get("result", data)
                if isinstance(res, dict):
                    errs = res.get("errors", [])
                    msg = res.get("message", "")
                    mf = res.get("missingFields", [])
                    if isinstance(errs, list) and errs:
                        for e in errs:
                            for part in str(e).split(" — "):
                                clean_p = part.strip()
                                if clean_p:
                                    toast_error_counter[clean_p] += 1
                    elif msg and (res.get("success") is False or res.get("outcome") == "failed"):
                        toast_error_counter[str(msg).strip()] += 1
                    if isinstance(mf, list) and mf:
                        for m in mf:
                            missing_field_records.append(f"{m.get('key')}|{m.get('label')}|{m.get('kind')}")
                elif res is False:
                    toast_error_counter["submitActiveForm_returned_false"] += 1

        # 2. DOM Field Missing / Ambiguous during form filling
        if "-> not_found:" in line or "-> ambiguous:" in line:
            m_fill = re.search(r"Field '([^']+)' -> (not_found|ambiguous):", line)
            if m_fill:
                dom_missing_counter[f"{m_fill.group(2)}:{m_fill.group(1)}"] += 1
        if "Cash settlement skipped" in line:
            dom_missing_counter["CashSettlement:total_zero"] += 1

        # 3. Query / Golden Set tracking
        if "[USER_QUERY]" in line:
            seq_in_file += 1
            m_q = re.search(r'User:\s*"([^"]+)"', line)
            q_text = m_q.group(1) if m_q else ""
            rec = {
                "file": p.name,
                "line": line_no,
                "trace": trc or f"{p.name}_q{seq_in_file}",
                "query": q_text,
                "screen": None,
                "pageId": None,
                "schemas": [],
                "ai_extract": None,
                "fill_success": False,
                "filled_count": 0,
                "saved": False,
                "recovery_turn_saved": False,
                "save_errors": [],
            }
            all_queries.append(rec)
            if trc:
                current_trace_map[trc] = rec
            last_q_rec = rec
            continue

        # Target record for non-query lines
        rec = current_trace_map.get(trc) if trc else last_q_rec

        if "[SCAN]" in line and "Collected form schema" in line:
            s_data = extract_json(line)
            if isinstance(s_data, dict):
                fields = s_data.get("fields", [])
                last_schema_global = fields
                if rec is not None:
                    rec["schemas"].append(fields)
        elif "[AI_EXTRACT]" in line and "AI extracted form fill proposal" in line:
            ex_data = extract_json(line)
            if isinstance(ex_data, dict) and rec is not None:
                rec["ai_extract"] = ex_data
                rec["screen"] = ex_data.get("screenKey")
                rec["pageId"] = ex_data.get("pageId")
                if not rec["schemas"] and last_schema_global:
                    rec["schemas"].append(last_schema_global)
        elif "applyFormFill finished with success=" in line and rec is not None:
            d = extract_json(line)
            if isinstance(d, dict):
                if d.get("success") is True:
                    rec["fill_success"] = True
                rec["filled_count"] = d.get("filledCount", 0)
        elif "submitActiveForm()" in line:
            d = extract_json(line)
            if isinstance(d, dict):
                res = d.get("result")
                is_saved = res is True or (
                    isinstance(res, dict) and (res.get("outcome") == "saved" or res.get("success") is True)
                )
                if is_saved:
                    if rec is not None:
                        rec["saved"] = True
                        # If this was a recovery reply ('1', 'سعر الصرف = 1', etc.), credit the immediately preceding failed command!
                        if rec["query"].strip() in ("1", "سعر الصرف 1", "سعر الصرف = 1"):
                            idx = all_queries.index(rec)
                            for prev_idx in range(idx - 1, -1, -1):
                                if all_queries[prev_idx]["file"] == rec["file"] and all_queries[prev_idx]["ai_extract"]:
                                    all_queries[prev_idx]["recovery_turn_saved"] = True
                                    break
                elif isinstance(res, dict) and res.get("errors") and rec is not None:
                    rec["save_errors"].extend(res.get("errors", []))

print("=== 1. ALL TOAST / SAVE VALIDATION ERRORS (ALL LOGS) ===")
for err, count in toast_error_counter.most_common():
    print(f"  {count}x | {err}")

print("\n=== 2. DOM FIELD FILL FAILURES (NOT_FOUND / AMBIGUOUS) ===")
for err, count in dom_missing_counter.most_common():
    print(f"  {count}x | {err}")

if missing_field_records:
    print("\n=== 2b. EXPLICIT missingFields OBJECTS IN LOGS ===")
    for k, c in Counter(missing_field_records).most_common():
        print(f"  {c}x | {k}")

print("\n=== 3. GOLDEN SET INVENTORY (45 TOTAL USER QUERIES) ===")
recovery_replies = [q for q in all_queries if q["query"].strip() in ("1", "سعر الصرف 1", "سعر الصرف = 1")]
real_cmds = [q for q in all_queries if q["query"].strip() not in ("1", "سعر الصرف 1", "سعر الصرف = 1")]

with_extract = [q for q in real_cmds if q["ai_extract"]]
with_extract_and_schema = [q for q in real_cmds if q["ai_extract"] and q["schemas"]]
fill_ok = [q for q in with_extract_and_schema if q["fill_success"]]
saved_total = [q for q in with_extract_and_schema if q["saved"] or q["recovery_turn_saved"]]
saved_direct = [q for q in with_extract_and_schema if q["saved"]]

print(f"Total [USER_QUERY] runs: {len(all_queries)} (Real commands: {len(real_cmds)}, Recovery replies: {len(recovery_replies)})")
print(f"Real commands with AI_EXTRACT: {len(with_extract)}")
print(f"Real commands with AI_EXTRACT + Collected form_schema: {len(with_extract_and_schema)}")
print(f"  -> Of those, applyFormFill succeeded: {len(fill_ok)}")
print(f"  -> Of those, Saved (Direct OR after 1-turn recovery): {len(saved_total)} (Direct: {len(saved_direct)}, Via Recovery: {len(saved_total) - len(saved_direct)})")

by_unique_q = {}
for q in with_extract_and_schema:
    by_unique_q.setdefault(q["query"], []).append(q)

print(f"\n=== 4. UNIQUE QUERIES WITH AI_EXTRACT + SCHEMA ({len(by_unique_q)} unique prompts) ===")
for i, (qtext, items) in enumerate(by_unique_q.items(), 1):
    f_ok = sum(1 for x in items if x["fill_success"])
    s_ok = sum(1 for x in items if x["saved"] or x["recovery_turn_saved"])
    screens = sorted(set(f"{x['screen']}(p:{x['pageId']})" for x in items))
    sc_counts = sorted(set(len(s) for x in items for s in x["schemas"]))
    print(f"  {i}. runs={len(items)} (fill_ok={f_ok}, saved={s_ok}) | screens={screens} | schema_fields={sc_counts}")
    print(f"     Query: {qtext}")

# Also inspect real_cmds that had NO AI_EXTRACT (e.g. navigation or early logs)
no_ext = [q for q in real_cmds if not q["ai_extract"]]
print(f"\n=== 5. REAL COMMANDS WITHOUT AI_EXTRACT ({len(no_ext)}) ===")
for q in no_ext:
    print(f"  * {q['file']} L{q['line']} [{q['trace']}]: {q['query'][:80]} (schemas={len(q['schemas'])}, fill_ok={q['fill_success']}, saved={q['saved']})")
