import json, re
from pathlib import Path

logs_dir = Path('e:/Mazen/EgyDynamic/LMS_CO_Pilot/logs/erp_sessions')
session_logs = sorted(logs_dir.glob('session_*.log'), key=lambda p: p.stat().st_mtime)

total_real_unique_with_schema = {}

for p in session_logs:
    lines = p.read_text(encoding='utf-8', errors='ignore').splitlines()
    last_schema = None
    cmds = []
    tmap = {}
    last = None
    for i, l in enumerate(lines, 1):
        trc_m = re.search(r'\[trc:(trc_[a-z0-9]+)\]', l)
        trc = trc_m.group(1) if trc_m else None
        if '[USER_QUERY]' in l:
            m = re.search(r'User:\s*"([^"]+)"', l)
            rec = {'l': i, 'trc': trc, 'q': m.group(1) if m else '', 'sc': None, 'ext': False, 'fill': None, 'save': None}
            cmds.append(rec)
            if trc: tmap[trc] = rec
            last = rec
            continue
        rec = tmap.get(trc) if trc else last
        if '[SCAN]' in l and 'Collected form schema' in l:
            idx = l.find(' | {')
            if idx != -1:
                try:
                    last_schema = json.loads(l[idx+3:]).get('fieldsCount', 0)
                    if rec: rec['sc'] = last_schema
                except Exception: pass
        elif '[AI_EXTRACT]' in l and 'proposal' in l and rec:
            rec['ext'] = True
            if rec['sc'] is None: rec['sc'] = last_schema
        elif 'applyFormFill finished' in l and rec:
            rec['fill'] = 'success=true' in l
        elif 'submitActiveForm()' in l and rec:
            idx = l.find(' | {')
            if idx != -1:
                try:
                    res = json.loads(l[idx+3:]).get('result')
                    if isinstance(res, dict):
                        rec['save'] = res.get('outcome') or res.get('success')
                    else:
                        rec['save'] = res
                except Exception: pass
    print(f'=== {p.name} ({len(cmds)} queries) ===')
    for c in cmds:
        print(f"  L{c['l']} [{c['trc']}] sc={c['sc']} ext={c['ext']} fill={c['fill']} save={c['save']} | {c['q'][:70]}")

