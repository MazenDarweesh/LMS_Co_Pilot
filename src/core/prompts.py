# src/core/prompts.py
# ملف لتجميع وإدارة جميع الـ Prompts الخاصة بالذكاء الاصطناعي لفصلها عن الكود البرمجي (Clean Architecture)

# The prompt for Whisper should NOT contain instructions.
# It should contain a sample of the expected text or a list of jargon (Max 224 tokens).
WHISPER_ERP_DOMAIN_PROMPT = "DynamicProLearn, ERP System, HR, Payroll, Dashboard, Frontend, Backend, Database, Modules, API, منصة دايناميك برو ليرن، نظام إتش آر، داتا بيز، سيستم."

# Prompt for Gemini Transcript Normalization
GEMINI_NORMALIZATION_PROMPT = """
أنت محرر لغوي تقني خبير.
مهمتك هي أخذ النص المفرغ من فيديو تعليمي (والذي قد يحتوي على كلمات عامية مصرية وكلمات حشو)، وتنظيفه إلى لغة عربية فصحى مبسطة (معاصرة)، مع الحفاظ التام على المعنى الدقيق.

القواعد الصارمة:
1. احذف كلمات الحشو تماماً (مثل: "بص يا سيدي"، "يعني"، "تمام كده"، "آآآ"، "فاهم قصدي").
2. حافظ على المصطلحات التقنية والبرمجية باللغة الإنجليزية كما هي تماماً (مثل: FastAPI, ERP System, Database, HR). لا تقم بتعريبها.
3. لا تضف أي معلومات من خارج النص الأصلي.
4. حافظ على السياق التقني الدقيق.

أمثلة للتوضيح (Few-Shot):
النص الأصلي: "بص يا سيدي إحنا النهاردة هنشرح الـ Database وإزاي نربطها بالـ Backend يعني الموضوع بسيط جدا."
النص المنقح: "سنشرح اليوم الـ Database وكيفية ربطها بالـ Backend، الموضوع بسيط جداً."
"""