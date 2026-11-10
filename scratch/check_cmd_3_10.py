import glob, re

logs = sorted(glob.glob('e:/Mazen/EgyDynamic/LMS_CO_Pilot/logs/erp_sessions/session_*.log'))
cmd_count = 0
for path in logs:
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    for idx, line in enumerate(lines):
        if '[USER_QUERY]' in line:
            cmd_count += 1
            if 3 <= cmd_count <= 10:
                print(f"CMD {cmd_count} | {path.split('/')[-1].split(chr(92))[-1]} L{idx+1} | {line.strip()[:160]}")

