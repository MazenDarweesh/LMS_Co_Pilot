import glob, re

logs = glob.glob('e:/Mazen/EgyDynamic/LMS_CO_Pilot/logs/erp_sessions/*.log')
messages = set()
for p in logs:
    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
        for l in f:
            if 'submitActiveForm' in l and 'message' in l:
                m = re.search(r'"message":\s*"([^"]+)"', l)
                if m:
                    messages.add(m.group(1))

print('All submitActiveForm messages in logs:')
for msg in messages:
    print(f' - {msg}')

