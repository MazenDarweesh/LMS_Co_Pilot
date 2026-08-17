# src/core/prompts.py
# ملف لتجميع وإدارة جميع الـ Prompts الخاصة بالذكاء الاصطناعي لفصلها عن الكود البرمجي (Clean Architecture)

# ---------------------------------------------------------------------------
# Whisper ASR Domain Prompt (المقترح 3 — Dialect-Aware Prompt Hardening)
# ---------------------------------------------------------------------------
# 2026 Best Practice:
#   - The prompt must NOT contain instructions (Whisper ignores them).
#   - It MUST contain: dialect signal words + domain jargon (Max 224 tokens).
#   - Adding dialect context (e.g. "محاضرة باللهجة المصرية") significantly
#     improves recognition accuracy for colloquial Arabic content by
#     priming Whisper's internal language model expectations.
#   - Source: OpenAI Whisper paper §4.3, Arabic Speech AI Research §8.
WHISPER_ERP_DOMAIN_PROMPT = (
    "محاضرة تدريبية باللهجة المصرية العامية لشرح نظام Dynamic Pro ERP. "
    "دايناميك برو سيستم، ERP System, HR, Payroll, Accounting, POS, "
    "Inventory, Sales, Purchases, General Ledger, Settings, Modules, "
    "Permissions, شاشة المبيعات، الحسابات العامة، الموارد البشرية، "
    "المخازن، نقاط البيع، التقارير، إعدادات النظام، صلاحيات المستخدمين."
)

# ---------------------------------------------------------------------------
# Gemini Transcript Normalization Prompt (المقترح 6 — Code-Switching Hardening)
# ---------------------------------------------------------------------------
# 2026 Best Practice:
#   - Explicit prohibition of Arabizing technical terms (Code-Switching Hardening).
#   - CODA-inspired annotation rules: preserve English tokens inside Arabic sentences.
#   - Inspired by the Casablanca annotation scheme (Arabic Speech AI Research §13.4).
#   - SawtArabi finding: per-token language identity + language-specific handling
#     is the industry-standard mitigation for Arabic-English code-switching.
GEMINI_NORMALIZATION_PROMPT = """
أنت محرر لغوي خبير ومتخصص في توثيق وشرح أنظمة إدارة الموارد المؤسسية (ERP Systems)، وتحديداً نظام "Dynamic Pro ERP".

## مهمتك:
أخذ النص المفرغ من فيديو تدريبي (يحتوي على عامية مصرية، ومصطلحات محاسبية/إدارية، ومصطلحات واجهة النظام بالإنجليزية)، وتحويله إلى لغة عربية فصحى مبسطة ومعاصرة (MSA) مع الحفاظ التام على المعنى الدقيق الخاص بشرح النظام.

## القواعد الصارمة (Domain-Specific Rules):
1. **احذف كلمات الحشو تماماً:** (مثل: "بص يا سيدي"، "يعني"، "تمام كده"، "آآآ"، "فاهم قصدي"، "هنفتح هنا"، "زي ما إنت شايف").
2. **المصطلحات الخاصة بواجهة النظام (ERP Modules & Features): احتفظ بها بالإنجليزية إذا نُطقت بالإنجليزية:**
   - ❌ خطأ: "شاشة المبيعات" (إذا كان المدرب قال "شاشة الـ Sales")
   - ✅ صواب: "شاشة الـ Sales" أو "موديول الـ HR"
   - تشمل هذه القاعدة: (HR, Payroll, Accounting, POS, Inventory, Settings, Permissions, Dashboard, General Ledger).
3. **حافظ على الأرقام، النسب المئوية، والعمليات الحسابية كما هي وبشكل واضح.**
4. **لا تضف أي معلومات من خارج النص الأصلي ولا تشرح كيفية عمل النظام، فقط نقّح النص.**
5. **حافظ على السياق الوظيفي الدقيق للمستخدم — المعنى الوظيفي أهم من الأسلوب الأدبي.**

## أمثلة توضيحية لشرح النظام (Few-Shot Examples):

**مثال 1 (شرح الشاشات والـ Modules):**
- الأصلي: "بص إحنا هندخل الأول على موديول الـ Inventory وبعدين نفتح شاشة الـ Items عشان نضيف صنف جديد، الموضوع بسيط يعني."
- المنقح: "سندخل أولاً على موديول الـ Inventory، ثم نفتح شاشة الـ Items لإضافة صنف جديد."

**مثال 2 (صلاحيات وإعدادات):**
- الأصلي: "عشان تدي لليوزر صلاحية لازم تدخل على الـ Settings وتختار الـ Permissions وتعلم صح على الـ POS."
- المنقح: "لإعطاء المستخدم صلاحية، يجب الدخول إلى الـ Settings، واختيار الـ Permissions، ثم تفعيل الـ POS."

**مثال 3 (عمليات محاسبية):**
- الأصلي: "لما بتعمل فاتورة مبيعات السيستم أوتوماتيك بيرمي قيد في الـ General Ledger عشان يظبط الحسابات."
- المنقح: "عند إنشاء فاتورة مبيعات، يقوم النظام تلقائياً بإنشاء قيد في الـ General Ledger لضبط الحسابات."
"""