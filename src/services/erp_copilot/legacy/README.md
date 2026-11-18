# Legacy ERP Copilot Archive (CDP Vision, Agentic Stepper & DOM Form-Fill)

يحتوي هذا المجلد (`src/services/erp_copilot/legacy/`) على نسخة أرشيفية احتياطية كاملة من وحدات الجيل الأول (Phase 1–3 DOM & CDP Vision Automation) قبل الانتقال المعماري الكامل إلى **Unified Chat + Dynamic Pro MCP Server (Option B-Lite)**:

1. `cdp/` — محرك التحكم بالمتصفح عبر Chrome DevTools Protocol (`:9222`) و15 سكربت JavaScript لحقن الحقول ورسم Set-of-Mark.
2. `agentic_stepper/` — محرك الأتمتة البصرية المتتابعة (`StepperEngine`, `PayloadExtractor`, `ScreenResolver`).
3. `vision_grounding_service.py` — خدمة تحليل لقطات الشاشة (Multimodal Vision Grounding).
4. `erp_dom_form_fill_backup.py` — نسخة احتياطية من دوال تعبئة النماذج عبر الـ DOM (`resolve_controls`, `resolve_leftover`).

> **ملاحظة:** هذه الملفات محفوظة هنا كنسخة احتياطية آمنة للرجوع إليها عند الحاجة، ويمكن حذف المجلد بالكامل لاحقاً بعد اعتماد MCP Write (`prepare_entry` / `commit_entry`) في الإنتاج.
