import glob, json, re
from pathlib import Path

logs = sorted(Path('e:/Mazen/EgyDynamic/LMS_CO_Pilot/logs/erp_sessions').glob('session_*.log'), key=lambda p: p.stat().st_mtime)

commands = []
for p in logs:
    lines = p.read_text(encoding='utf-8', errors='ignore').splitlines()
    curr_query = None
    curr_screen = None
    outcome = 'pending'
    reason = ''
    
    for line in lines:
        if '[USER_QUERY]' in line:
            if curr_query:
                commands.append((curr_query, curr_screen, outcome, reason, p.name))
            m = re.search(r'User:\s*"([^"]+)"', line)
            curr_query = m.group(1) if m else line
            brackets = re.findall(r'\[([^\]]+)\]', line)
            curr_screen = brackets[3].strip() if len(brackets) > 3 else (brackets[2].strip() if len(brackets) > 2 else 'Purchases')
            outcome = 'pending'
            reason = ''
        elif 'submitActiveForm()' in line or '"outcome": "' in line:
            if '"outcome": "saved"' in line or '"success": true' in line:
                outcome = 'نجاح (Saved)'
                reason = 'تم الحفظ بنجاح وتأكيد السيرفر'
            elif '"outcome": "failed"' in line or '"success": false' in line:
                outcome = 'فشل (Failed)'
                m_err = re.search(r'"errors":\s*(\[[^\]]+\])', line)
                reason = m_err.group(1) if m_err else 'خطأ تحقق (Validation)'
        elif 'Applying conversational missing-field recovery' in line and outcome != 'نجاح (Saved)':
            outcome = 'استرجاع حواري (Recovery)'
        elif '[Vision Step 15] max_steps_reached' in line:
            outcome = 'فشل (Failed)'
            reason = 'تجاوز حد خطوات الرؤية (15)'
        elif 'ClientConnection\' object has no attribute \'closed\'' in line and outcome != 'نجاح (Saved)':
            reason = 'انهيار WebSocket (.closed)'
            outcome = 'فشل (Failed)'
        elif 'applyFormFill finished with success=true' in line and outcome == 'pending':
            outcome = 'تعبئة ناجحة (Fill OK)'
            reason = 'تمت التعبئة بانتظار الحفظ'
    if curr_query:
        commands.append((curr_query, curr_screen, outcome, reason, p.name))

# Print markdown table
print("| # | أمر المستخدم (User Query) | الشاشة المستهدفة | النتيجة | سبب الفشل / الملاحظات | نوع الأمر (استقلالية/تتابع) |")
print("|---|---|---|---|---|---|")

# Take representative 30 commands across early, mid and recent logs
selected = commands[-30:] if len(commands) >= 30 else commands
for idx, (q, s, out, r, fname) in enumerate(selected, 1):
    clean_q = q.strip().replace("\n", " ")
    if len(clean_q) > 60:
        clean_q = clean_q[:57] + "..."
    clean_r = r.replace("\n", " ").replace("[\"'", "").replace("'\"]", "").replace("[\"", "").replace("\"]", "")
    if len(clean_r) > 40:
        clean_r = clean_r[:37] + "..."
    if not clean_r:
        clean_r = "-" if out != 'pending' else "انتظار تأكيد المستخدم"
    
    is_contextual = bool(re.match(r'^(1|سعر الصرف.*|عدل.*|احذف.*|شيل.*|نقداً|كاش|\d+)$', clean_q))
    cmd_type = "🔄 متتابع (يعتمد على سياق سابق)" if is_contextual else "🆕 أمر مستقل"
    print(f"| {idx} | {clean_q} | {s} | {out} | {clean_r} | {cmd_type} |")
