import json, re
from pathlib import Path

logs_dir = Path("e:/Mazen/EgyDynamic/LMS_CO_Pilot/logs/erp_sessions")
session_logs = sorted(logs_dir.glob("session_*.log"), key=lambda p: p.stat().st_mtime)

unique_cases = {}

for p in session_logs:
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    tmap = {}
    last_rec = None
    last_schema = None
    seq = 0

    for ln, l in enumerate(lines, 1):
        trc_m = re.search(r"\[trc:(trc_[a-z0-9]+)\]", l)
        trc = trc_m.group(1) if trc_m else None

        if "[USER_QUERY]" in l:
            seq += 1
            m_q = re.search(r'User:\s*"([^"]+)"', l)
            q_text = m_q.group(1) if m_q else ""
            rec = {
                "file": p.name,
                "line": ln,
                "trc": trc or f"q{seq}",
                "query": q_text,
                "schema": None,
                "extract": None,
                "fill_ok": None,
            }
            if trc:
                tmap[trc] = rec
            last_rec = rec
            continue

        rec = tmap.get(trc) if trc else last_rec
        if "[SCAN]" in l and "Collected form schema" in l:
            idx = l.find(" | {")
            if idx != -1:
                try:
                    sc = json.loads(l[idx + 3 :]).get("fields", [])
                    last_schema = sc
                    if rec is not None and (rec["schema"] is None or len(sc) > len(rec["schema"])):
                        rec["schema"] = sc
                except Exception:
                    pass
        elif "[AI_EXTRACT]" in l and "AI extracted form fill proposal" in l:
            idx = l.find(" | {")
            if idx != -1 and rec is not None:
                try:
                    ex = json.loads(l[idx + 3 :])
                    rec["extract"] = ex
                    if rec["schema"] is None and last_schema:
                        rec["schema"] = last_schema
                    if rec["schema"] and len(rec["schema"]) > 0:
                        # Prefer latest run with non-empty schema & extract (or keep list)
                        unique_cases.setdefault(rec["query"], []).append(rec)
                except Exception:
                    pass
        elif "applyFormFill finished" in l and rec is not None:
            rec["fill_ok"] = "success=true" in l

print(f"Found {len(unique_cases)} unique queries:")
for i, (q, runs) in enumerate(unique_cases.items(), 1):
    # pick best run (latest non-empty schema)
    best = runs[-1]
    for r in reversed(runs):
        if len(r["schema"]) >= 15:
            best = r
            break
    print(f"\n=== CASE {i} (from {best['file']}:L{best['line']} [{best['trc']}]) ===")
    print(f"Query: {q}")
    print(f"Screen: {best['extract'].get('screenKey')} (pageId={best['extract'].get('pageId')})")
    print(f"Schema ({len(best['schema'])} fields): {[f.get('key') + ':' + f.get('label','') for f in best['schema']]}")
    print(f"Logged Extract fields: {best['extract'].get('fields')}")
    print(f"Logged Extract rows: {best['extract'].get('rows')}")
    print(f"Fill OK: {best['fill_ok']}")

