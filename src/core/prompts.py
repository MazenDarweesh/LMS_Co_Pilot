# src/core/prompts.py
# ملف لتجميع وإدارة جميع الـ Prompts الخاصة بالذكاء الاصطناعي لفصلها عن الكود البرمجي (Clean Architecture)

# The prompt for Whisper should NOT contain instructions.
# It should contain a sample of the expected text or a list of jargon (Max 224 tokens).
WHISPER_ERP_DOMAIN_PROMPT = "DynamicProLearn, ERP System, HR, Payroll, Dashboard, Frontend, Backend, Database, Modules, API, منصة دايناميك برو ليرن، نظام إتش آر، داتا بيز، سيستم."
