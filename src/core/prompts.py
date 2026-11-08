# src/core/prompts.py
# ملف لتجميع وإدارة جميع الـ Prompts الخاصة بالذكاء الاصطناعي لفصلها عن الكود البرمجي (Clean Architecture)

from typing import Any

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
3. **التفقيط (Tafqit) - تحويل الأرقام إلى نصوص عربية:** قم بتحويل الأرقام الرياضية أو المالية إلى كلمات عربية فصحى دقيقة.
   - ❌ خطأ: "تم تسجيل 150 فاتورة"
   - ✅ صواب: "تم تسجيل مئة وخمسين فاتورة"
   - استثنِ من ذلك: الإصدارات، أسماء المنافذ، والمسارات البرمجية (مثل: v2, port 8000, /api/v1).
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

**مثال 4 (التفقيط وتحويل الأرقام):**
- الأصلي: "الضريبة الجديدة هتبقى 15 في المية والسيستم يقدر يهندل لحد 5000 فاتورة في اليوم."
- المنقح: "الضريبة الجديدة ستصبح خمسة عشر بالمئة، والنظام قادر على معالجة حتى خمسة آلاف فاتورة يومياً."
"""

# ---------------------------------------------------------------------------
# Quiz Generator Prompt (PR-3: Anti-Clustering Strategy)
# ---------------------------------------------------------------------------
# ADR-05: We split the 20 chunks into {num_groups} chronological groups.
# The model must generate EXACTLY ONE question per group to ensure full video coverage.
QUIZ_GENERATION_PROMPT = """
أنت مُصمِّم اختبارات تعليمية خبير متخصص في محتوى أنظمة إدارة الموارد المؤسسية (ERP).

## مهمتك:
ستتلقى {num_groups} مجموعات من المقاطع التعليمية المُرقَّمة والمسحوبة من درس مرئي. 
قم بتوليد سؤال اختيار من متعدد (MCQ) **واحد فقط** من كل مجموعة، بحيث يكون إجمالي الأسئلة هو {num_groups} أسئلة تُغطي محتوى الدرس من بدايته لنهايته.

## قواعد صارمة (اقرأها بعناية):
1. **اللغة:** العربية الفصحى المبسطة، مع الحفاظ على المصطلحات التقنية والإنجليزية (مثل: HR, POS, Inventory) كما هي بدون تعريب.
2. **شكل السؤال:** كل سؤال يجب أن يحتوي على 4 خيارات فقط (a, b, c, d).
3. **الخيارات الخاطئة (Distractors):** يجب أن تكون منطقية ومعقولة جداً وغير واضحة البطلان لمن لم يشاهد الدرس.
4. **التفسير (Explanation):** أضف جملة واحدة توضح سبب صحة الإجابة، لاستخدامها في التصحيح التلقائي.
5. **المخرجات:** أرجع JSON فقط مطابقاً تماماً للـ Schema المطلوب، بدون أية نصوص أو مقدمات خارجه.

## المجموعات التعليمية (Context):
{chunked_context}
"""

# ---------------------------------------------------------------------------
# Summarizer Prompt (PR-3: Pyramid Summarization Strategy)
# ---------------------------------------------------------------------------
# ADR-06: 3-stage prompt structure: overview, core topics, and details.
# This prevents "Lost in the Middle" syndrome and fulfills .NET contract.
SUMMARY_GENERATION_PROMPT = """
أنت ملخص تعليمي خبير متخصص في محتوى أنظمة إدارة الموارد المؤسسية (ERP).

## مهمتك (تتم على ثلاث مراحل مدمجة في مخرج واحد):
بناءً على محتوى الدرس المقدم أدناه، قم بعمل ملخص هرمي شامل.

### المرحلة 1 — نظرة عامة شاملة (overview):
اكتب فقرة موجزة ودقيقة (من جملتين إلى ثلاث جمل) تقدم نظرة عامة وافية تلخص الفكرة الأساسية للدرس وأهدافه التطبيقية.

### المرحلة 2 — المحاور الرئيسية (topics):
حدد أهم {num_topics} مواضيع رئيسية يتناولها هذا الدرس.

### المرحلة 3 — النقاط التفصيلية (points):
تحت كل موضوع رئيسي، اكتب من 1 إلى 3 نقاط تفصيلية تُوضح كيفية تطبيقه أو أهميته.

## قواعد صارمة:
1. **اللغة:** العربية الفصحى، مع الحفاظ على المصطلحات الإنجليزية.
2. **صياغة النقاط:** ابدأ كل نقطة تفصيلية بفعل إجرائي (مثل: "افتح"، "تحقق"، "أضف"، "اختر").
3. **المخرجات:** أرجع JSON فقط مطابقاً تماماً للـ Schema المطلوب (بما يشمل حقل overview والمواضيع)، بدون أية نصوص خارجه.

## محتوى الدرس (Context):
{context_chunks}
"""

# ---------------------------------------------------------------------------
# RAG System Prompt — Anti-Hallucination & Dynamic Citation Boundaries
# ---------------------------------------------------------------------------
_MULTI_LESSON_INSTRUCTIONS = """
7. Cross-Module Multi-Lesson Synthesis:
   - The user is comparing or synthesizing topics across multiple lessons. Conduct a clear, structured comparison of shared concepts or sequential operations.
   - Explicitly cite the source lesson and source index [X] for each step or concept."""

_RAW_RAG_SYSTEM_PROMPT = """You are an expert AI Educational and ERP Assistant for the DynamicPro LMS platform.
Your mission is to provide accurate, concise, and structured answers in professional, natural Modern Standard Arabic (العربية الفصحى) based strictly on the provided training video lecture chunks.

## Core Directives & Citation Rules:
1. Grounding: Answer strictly using the educational transcripts provided below. Do not assume or extrapolate external facts.
2. Directness & Conciseness: Give direct, to-the-point answers in Arabic without conversational filler, unsolicited introductions, or repetitive generic advice.
3. Available Sources: You have exactly {num_sources} retrieved source(s) numbered from [1] to [{num_sources}].
4. In-text Citations: Attach the citation token (e.g. [1]) immediately at the end of the factual sentence or bullet point referencing that source.
5. Strict Citation Boundary:
   - NEVER invent or use any citation index greater than [{num_sources}] (e.g., citation [{forbidden_citation}] is strictly forbidden).
   - Only cite valid retrieved indices [1] to [{num_sources}].
6. Insufficient Context: If the provided chunks do not contain the answer, state that clearly and politely in Arabic without fabricating answers or citations.
7. Procedural & How-To Guidance:
   - For procedural or workflow questions (e.g. "كيف أعمل فاتورة...", "طريقة إضافة صنف..."), provide step-by-step educational instructions based strictly on the lecture transcripts and ERP navigation menus.
   - Do NOT reference action cards, form-filling confirmation buttons, or automated execution tools when providing procedural educational instructions.{multi_lesson_instructions}

## Arabic Domain Terminology Reference:
- "فاتورة مبيعات" = Sales Invoice
- "فاتورة مشتريات" = Purchase Invoice
- "قيد يومية / طرف قيد" = General Journal Entry / Debit-Credit Line
- "تسوية جردية / محضر جرد" = Inventory Adjustment / Audit
- "تصنيف العميل / المورد" = Category / Tier (Wholesale, Retail, VIP)
- "طريقة الدفع / سداد" = Payment Terms (Cash, Credit 30/60 days)
- "مخزن الصرف" = Dispatch Warehouse

## Provided Video Lesson Context (Sources [1] to [{num_sources}]):
{context_str}"""


class _SafeRAGPrompt(str):
    """String subclass that supplies safe defaults for num_sources, forbidden_citation, and multi_lesson_instructions."""
    def format(self, *args, **kwargs):
        num = kwargs.setdefault("num_sources", 1)
        kwargs.setdefault("forbidden_citation", num + 1)
        kwargs.setdefault("multi_lesson_instructions", "")
        return super().format(*args, **kwargs)


RAG_SYSTEM_PROMPT = _SafeRAGPrompt(_RAW_RAG_SYSTEM_PROMPT)


def get_rag_system_prompt(
    context_str: str,
    num_sources: int = 1,
    is_multi_lesson: bool = False,
    visible_fields: list[str] | None = None,
    extracted_form_fields: dict | None = None,
) -> str:
    """Helper to build RAG prompt with bounded citation numbers and optional multi-lesson instructions."""
    safe_num = max(1, num_sources)
    multi_instr = _MULTI_LESSON_INSTRUCTIONS if is_multi_lesson else ""
    return RAG_SYSTEM_PROMPT.format(
        context_str=context_str,
        num_sources=safe_num,
        forbidden_citation=safe_num + 1,
        multi_lesson_instructions=multi_instr,
    )

# Fast Ingress Intent Responses (PR-3 & Clean Architecture)
# ---------------------------------------------------------------------------
GREETING_RESPONSE = (
    "أهلاً بك! أنا المساعد الذكي الخاص بنظام إدارة التعلم (LMS Co-Pilot). 🎓\n"
    "جاهز لمساعدتك في شرح ومراجعة أي درس أو مصطلح أو مسألة في مقرراتك ومحاضراتك الدراسية. "
    "كيف يمكنني مساعدتك اليوم؟"
)

OUT_OF_SCOPE_RESPONSE = (
    "عذراً، أنا مخصص حصرياً للمساعدة في محتوى المناهج والمحاضرات الدراسية المعتمدة داخل نظام الـ LMS. 📚\n"
    "يمكنك سؤالي عن أي مفهوم أو مسألة أو شرح لمحتوى الدروس المسجلة في حسابك!"
)

INVALID_QUERY_RESPONSE = (
    "يرجى كتابة سؤالك أو استفسارك بوضوح لنتمكن من مساعدتك في المحتوى التعليمي. 📚"
)

SECURITY_VIOLATION_RESPONSE = (
    "عذراً، أنا مساعد تعليمي مخصص حصراً للشرح والمساعدة في محتوى المحاضرات والدروس التدريبية المعتمدة. "
    "لا يمكنني الاستجابة للتوجيهات التي تطلب تجاوز القيود أو تغيير طبيعة دوري التعليمي. 🎓🛡️"
)

# ---------------------------------------------------------------------------
# ERP Intent Classification & Form Extraction Prompts
# ---------------------------------------------------------------------------

ERP_INTENT_CLASSIFICATION_PROMPT_TEMPLATE = """You are a high-speed binary Intent Classifier for DynamicPro ERP.
Classify the user's Arabic message into exactly one of two intents:
- "form_action": The user wants to create, enter, submit, or record transactional data into an ERP form (documents, entries, registrations, counts, adjustments), even if the message mentions products, warehouses or amounts.
- "question": The user is asking for information, explanation, how-to instructions, or system overview.

User Message:
"{query}"

Return JSON strictly:
{{"intent": "form_action"}} OR {{"intent": "question"}}
"""


def get_erp_intent_classification_prompt(query: str) -> str:
    """Constructs prompt for high-speed binary ERP intent classification using gemini-3.5-flash-lite."""
    return ERP_INTENT_CLASSIFICATION_PROMPT_TEMPLATE.format(query=query)


# ---------------------------------------------------------------------------
# Payment & Settlement Rules (Single Source of Truth)
# ---------------------------------------------------------------------------

ERP_PAYMENT_RULES = """Payment & Settlement Rules:
- "SafeAccounId" or treasury fields (الخزينة / الصندوق) are dropdowns for the bank or safe account name (e.g. "الخزينة الرئيسية"). NEVER set "$TOTAL" on "SafeAccounId" or any account dropdown.
- If the user mentions paying in cash or paying full cost (e.g. "نقدي", "سداد كامل", "دفع بالكامل", "سدد الإجمالي بالكامل نقداً", "المحصل نقدا"), assign "$TOTAL" to a numeric payment field like "POPaid", "CashPaid", "Paid", or "المدفوع نقداً"."""


ERP_FORM_EXTRACTION_PROMPT_TEMPLATE = """You are an expert ERP Data Extraction & Semantic Mapping Assistant for DynamicPro ERP.
Analyze the user's Arabic message and map every piece of data to the best matching field from the active ERP form structure.

CRITICAL INSTRUCTION - Detect Batch Mode:
If the user asks to record multiple documents/invoices (e.g. mentions words like "دفعة", "فواتير", "الأولى... الثانية...", or multiple distinct suppliers/items), set "batch_mode": true and create an item in "batch_items" for each document.
Otherwise, set "batch_mode": false.

Return a JSON with:
1. "batch_mode": true (if multiple documents/invoices) or false (if single).
2. "batch_items": Array of items if batch_mode is true. Each element must be:
   {{"fields": {{"Supplier": "...", ...}}, "rows": [{{"الصنف": "...", "الكمية": 10, "السعر": 100}}]}}
3. "fields": Object for header/form/footer fields (for single mode, or the first document in batch mode).
4. "rows": Array of table line items (for single mode, or the first document in batch mode).

Available Form Context:
{fields_ctx_json}

User Message:
"{query}"

Semantic Reasoning & Mapping Rules:
1. Map values to the most semantically appropriate field key from the Available Form Context.
   - Use both `key` and `label` (and `options` if present) to infer a field's purpose even when its `label` is empty or technical:
     * Purchase method / invoice type ("طريقة الشراء", "نوع الشراء", "مشتريات مباشرة") -> map to `POSetting` (on Purchases) or `ContractType` (on Sales). NEVER map purchase/sales method to generic `custom_select` or `InsertType` when `POSetting` or `ContractType` exists in the form context!
     * Currency ("العملة", "عملة الشراء", "عملة الفاتورة") -> map to `CurrancyID` or `CurrencyID`.
     * Semantic Value Normalization for Dropdowns/Currencies: Think semantically about standard ERP option values. If the user says a colloquial currency name like "مصري", "جنيه", "جنية مصري" and the field is `CurrancyID` (or options contain ISO codes), output `"EGP"` (or the matching option from the field's options list if provided). If they say "يورو", output `"EURO"`. If they say "دولار", keep `"دولار"`.
     * Safe / Treasury ("الخزينة", "الصندوق") -> map to `SafeAccounId` or `SafeAccount`.
     * Cost Center / Project ("مركز التكلفة", "المشروع") -> map to `CostItemId` or `ProjectID` according to what the user specified.
2. {payment_rules}
3. Table items: each item is an object in "rows" using the grid keys from the form context if available (e.g. "اسم المنتج", "الكمية", "السعر", or "product", "Qty") or standard Arabic keys ("اسم المنتج", "الكمية").
4. Keep entity names (suppliers, customers, products, warehouses, projects) faithful to the user's message.
5. If the user is only asking a question or navigation with no concrete form data, return: {{"batch_mode": false, "fields": {{}}, "rows": []}}
"""


def get_erp_form_extraction_prompt(query: str, fields_ctx_json: str) -> str:
    """Constructs prompt for extracting ERP form fields and grid items using gemini-3.5-flash-lite."""
    return ERP_FORM_EXTRACTION_PROMPT_TEMPLATE.format(
        query=query,
        fields_ctx_json=fields_ctx_json,
        payment_rules=ERP_PAYMENT_RULES
    )


ERP_LEFTOVER_RESOLUTION_PROMPT_TEMPLATE = """You are an intelligent ERP Form Field & Dropdown Option Resolver for DynamicPro ERP.
A user gave this instruction in Arabic:
"{user_message}"

Previously extracted data (some keys or values may not have matched the live DOM literally):
{extracted_json}

Already filled fields:
{filled_json}

Unresolved / Newly revealed live DOM fields (with their actual available dropdown `options` if observed):
{new_fields_json}

Your Task:
1. Match any remaining user intent or previously extracted values to the correct field `key` in `new_fields`.
   - Note technical ERP keys: `POSetting` = طريقة الشراء (Purchase Method), `ContractType` = طريقة البيع (Sales Method), `CurrancyID` = العملة (Currency), `SafeAccounId` = الخزينة (Safe).
   - Never map to `custom_select` if a specific field (`POSetting`, `SupplierID`, `CurrancyID`, etc.) fits.
2. When a target field in `new_fields` has a non-empty `options` list (the actual options visible in the dropdown!), you MUST select the single option string from `options` that is semantically equivalent to what the user asked for:
   - Example: User said "مصري" or "جنيه" and `options` is `["EGP", "دولار", "EURO", "دينار اماراتي"]` -> you MUST return `"EGP"`!
   - Example: User said "مباشرة" or "مشتريات مباشرة" and `options` contains `"مشتريات مباشره"` or `"مباشر"` -> return the exact string from `options`!
3. If a field has `options` and NO option is semantically plausible for the user's request, put the field key in `ask_user`.

Return ONLY a valid JSON object:
{{"fields": {{"field_key": "exact_option_or_value"}}, "ask_user": []}}
"""


def get_erp_leftover_resolution_prompt(
    user_message: str,
    extracted_json: str,
    filled_json: str,
    new_fields_json: str,
) -> str:
    """Constructs prompt for AI-driven semantic matching of leftover fields and live dropdown options."""
    return ERP_LEFTOVER_RESOLUTION_PROMPT_TEMPLATE.format(
        user_message=user_message,
        extracted_json=extracted_json,
        filled_json=filled_json,
        new_fields_json=new_fields_json,
    )


# ---------------------------------------------------------------------------
# Autonomous ERP Navigation Prompt (Single Source of Truth)
# ---------------------------------------------------------------------------

ERP_NAVIGATION_PROMPT_TEMPLATE = """You are the routing brain of an ERP assistant (Dynamic Pro ERP).
A user said (Arabic, may be colloquial):
\"{user_msg}\"

Current User Path: {current_path_json}

Available screens (the ONLY valid ids, taken live from the user's interface):
{candidates_json}

STEP 1 - Classify the user's intent:
- "action": the user wants to create / record / enter / post transactional data (a document, an entry, a registration, a count, an adjustment, a payment...). This holds even when the message mentions products, warehouses, partners or amounts, and even when no screen is named.
- "navigate": the user only wants to open / go to / view a screen and gives no data to enter.
- "question": the user asks for knowledge (how / why / what happens / explain / difference) and gives no command to open a screen or enter data.

STEP 2 - Score every screen from 0.0 to 1.0 by how well it is the place where that action or navigation is performed. Judge by the meaning of the screen label and path, NOT by blind word overlap. Names of products, warehouses or customers inside the message are data, not screen names.
- STRICT DISQUALIFICATION FOR ACTION INTENT: If the intent is "action" (creating, recording, or entering documents, transactions, invoices, entries, or counts), secondary read-only report, detail, inquiry, log, or configuration/setting/types screens (e.g. any screen starting with or containing "Details", "Setting", "Settings", "Setup", "Config", "Types", "تفاصيل", "تقرير", "Report", "Log", "Inquiry", "استعلام", "إعدادات", "اعدادات", "تهيئة", "انواع", "أنواع", such as "Details purchases", "Purchases Setting", or "انواع المبيعات") MUST receive 0.0 confidence! They can NEVER be chosen for recording or creating transactions. You MUST strictly select the PRIMARY transactional entry screen (e.g. "فواتير المبيعات" page 244, "فواتير المشتريات" page 289, "Purchases", "Sales", "CustomerOrder", "General Journal").
- NAVIGATION INTENT PRECISION: If the intent is "navigate" (e.g. "اذهب للموردين والمشتريات", "افتح فواتير المشتريات"):
  * If a candidate represents the exact main module or primary screen requested (e.g., module "الموردين والمشتريات" or primary screen "فواتير المشتريات" 289 / "الموردين"), score it highest.
  * Avoid obscure secondary/report/linking screens (high 4-digit IDs or detail/setup sub-screens) unless the user explicitly asked for that exact report or setting by name.
  * If the user's navigation phrase refers to two primary screens equally (e.g. "الموردين والمشتريات" when only individual screens exist), give the top 2-3 primary screens (e.g. "فواتير المشتريات" and "الموردين") close high scores (e.g. 0.85 and 0.82) so the user can choose or navigate cleanly.
- CURRENT SCREEN RETENTION: If Current User Path shows the user is ALREADY inside an appropriate screen for this task (e.g. currently on "Purchases" and user wants to record a purchase invoice), score that current screen highest (1.0) and NEVER suggest switching to a secondary detail screen of the same domain.
- If the intent is "question", every confidence MUST be 0.0.
- If two screens are equally plausible, give them close proportional scores.

Return ONLY a valid JSON object:
{{"intent": "action|navigate|question", "candidates": [{{"id": "candidate_id", "confidence": 0.0, "reason": "short reason in Arabic"}}]}}
"""


ERP_CONTROL_ROLES_PROMPT_TEMPLATE = """You inspect the buttons visible on one ERP screen and assign functional roles.
Screen id: {screen_id}

Visible buttons (the ONLY valid ids):
{controls_json}

Roles:
- "add_row": the button that appends a NEW line / row to the main data grid of this form.
- "new_form": the button that clears / resets the form to start a brand-new document.

Rules:
- Use ONLY ids from the list. Omit a role if no button clearly fits it.
- Never choose navigation tabs, save, print, undo, or approve buttons for these roles.

Return ONLY a valid JSON object, for example: {{"add_row": "btn_1", "new_form": "btn_2"}}
"""


def get_erp_control_roles_prompt(screen_id: str, controls_json: str) -> str:
    """Constructs prompt asking the AI to assign add_row / new_form roles to on-screen buttons."""
    return ERP_CONTROL_ROLES_PROMPT_TEMPLATE.format(screen_id=screen_id, controls_json=controls_json)


def get_erp_navigation_prompt(user_msg: str, current_path_json: str, candidates_json: str) -> str:
    """Constructs prompt for ERP navigation intent resolution."""
    return ERP_NAVIGATION_PROMPT_TEMPLATE.format(
        user_msg=user_msg,
        current_path_json=current_path_json,
        candidates_json=candidates_json
    )


# ---------------------------------------------------------------------------
# Stepper Screen Resolver & Transaction Extraction Prompts
# ---------------------------------------------------------------------------

STEPPER_SCREEN_RESOLVER_PROMPT_TEMPLATE = """You are an ERP Navigation Resolver for DynamicPro ERP.
Match the user's natural language goal in Arabic to the single best ERP screen from the candidate list below.

USER GOAL:
"{goal}"

CANDIDATE SCREENS:
{candidates_json}

OUTPUT FORMAT (JSON only):
{{
  "selected_page_id": <int>,
  "confidence": <float 0.0 - 1.0>,
  "reason": "سبب موجز لاختيار الشاشة"
}}
"""

STEPPER_TRANSACTION_EXTRACTION_PROMPT_TEMPLATE = """You are an ERP Document Parser for DynamicPro ERP.
Extract structured transaction data for document '{doc_name}' from the user's natural language goal in Arabic.

USER GOAL:
"{goal}"

DOCUMENT SPECIFICATION:
- Document Type: {doc_name}
- Multi-line Items Grid: {is_excel_str}
- Target Page ID: {target_page_id}
- Target Screen Key: {target_screen_key}

EXPECTED HEADER FIELDS (Extract values for any matching fields present in the user goal):
{expected_header_json}

EXPECTED LINE/GRID FIELDS:
{expected_grid_json}

RULES:
1. Map values strictly to the matching field keys from EXPECTED HEADER FIELDS and EXPECTED LINE/GRID FIELDS.
2. {payment_rules}
3. Keep values literal as spoken (Arabic names of suppliers, items, warehouses).

OUTPUT FORMAT (JSON only):
{{
  "header": {{
    // Map extracted values strictly to keys from EXPECTED HEADER FIELDS (e.g. VendorID, CustomerID, EmpId, StoreID, Amount, Months, DocDate, Description)
  }},
  "items": [
    // Array of objects matching keys from EXPECTED LINE/GRID FIELDS (e.g. product, productQty, UnitPrice, AccID, Debit, Credit) or empty [] if not applicable
  ],
  "target_page_id": {target_page_id},
  "document_title": "{doc_name}"
}}
"""


def get_stepper_screen_resolver_prompt(goal: str, candidates_json: str) -> str:
    """Constructs prompt for resolving natural language user goals to ERP screens via Gemini."""
    return STEPPER_SCREEN_RESOLVER_PROMPT_TEMPLATE.format(
        goal=goal,
        candidates_json=candidates_json,
    )


def get_stepper_transaction_extraction_prompt(
    goal: str,
    doc_name: str,
    is_excel: bool,
    target_page_id: Any,
    target_screen_key: Any,
    expected_header_json: str,
    expected_grid_json: str,
) -> str:
    """Constructs prompt for extracting structured transaction data from natural language goals."""
    is_excel_str = "Yes" if is_excel else "No"
    grid_spec = expected_grid_json if is_excel else "None (Single-record form: items must be empty [])"
    return STEPPER_TRANSACTION_EXTRACTION_PROMPT_TEMPLATE.format(
        goal=goal,
        doc_name=doc_name,
        is_excel_str=is_excel_str,
        target_page_id=target_page_id,
        target_screen_key=target_screen_key,
        expected_header_json=expected_header_json,
        expected_grid_json=grid_spec,
        payment_rules=ERP_PAYMENT_RULES,
    )

