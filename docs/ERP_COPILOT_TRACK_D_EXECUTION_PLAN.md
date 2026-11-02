# خطة التنفيذ التفصيلية — Track D (D.1 → D.6)

**الحالة:** مسودة بانتظار موافقة المستخدم — لم يتم تعديل أي كود.
**الفرع:** `vision-agent` في المشروعين.
**قاعدة:** لا جداول. لا commit/push إلا بأمر صريح. لا تثبيت مكتبات جديدة دون إخبارك.

---

## 0. ما اكتشفته في المراجعة الثانية (يغيّر الخطة السابقة)

### 0.1 اكتشافات من لوج الجلسة `y6p6` ومن الكود
1. **فشل "المحصل نقداً" له سببان مستقلان وليس سبباً واحداً:**
   - **مسار الشات (in-DOM):** سكيما الشاشة المجمّعة 23 حقلاً وكلها `ng-select` — لا يوجد ولا حقل رقمي أو نصي (لا محصل نقداً، لا خصم، لا متبقي). الدالة المسؤولة: `collectFormSchema` في `form-inspector.ts:154`. لذلك لا يستطيع الـ AI ربط "المحصل نقداً" بأي حقل حتى لو كانت قاعدة `$TOTAL` موجودة في البرومت (وهي موجودة فعلاً في `prompts.py:271-272`).
   - **مسار الوكيل البصري (CDP):** استخرج `target_page_id: 290` (شاشة تحويلات المخازن) بدل 244 بسبب الـ aliases الخاطئة، ثم بنى الـ payload من مخطط عام لا يعرف شيئاً عن السداد: `PaymentType: "نقدا"`. وفي `extraction_prompt` داخل `agentic_stepper_service.py:350` لا توجد أي قاعدة سداد أو `$TOTAL`.
2. **مخطط 244 في `forms_metadata.json:23754` عام ومُولّد آلياً (`is_auto_scaled`)**:
   - الهيدر: `EntityName, DocDate, StoreID, Notes, RefNo` فقط، والجريد: `ItemName, Qty, Price, Notes`.
   - لا يحتوي `customerID, ContractType, CostItemId, SalesMan` ولا أي حقل سداد، رغم أن الشاشة الحقيقية فيها هذه الحقول.
3. **عدم تطابق مفاتيح:** الـ payload في CDP أنتج `CustomerID` بينما المفتاح الحقيقي في الشاشة `customerID`. الجسر قال `success: true` لكن لا نعرف كم حقل تم ملؤه فعلاً. **لازم نتحقق منه في المرحلة 0 قبل أي إصلاح.**
4. **سطر الـ `submitActiveForm`:** الاستدعاء في `erp-bridge.service.ts:102` داخل `try/catch` (السطر 121 يلتقط الخطأ)، فالمشكلة ليست انهياراً بل غياب فحص `typeof` قبل الاستدعاء، ورسالة خطأ غير واضحة للمستخدم.
5. **مسار البحث لا يمر عبر .NET:** `copilot.service.ts` يرسل `streamSearch` مباشرة إلى `aiBaseUrl` (FastAPI :8000). .NET يخدم فقط `copilot-filters` والمصادقة. **إذن مشروع .NET لا يحتاج أي تعديل.**
6. **الحوكمة في الباك إند موجودة بالفعل:** `_classify_form_action_intent` (`search_service.py:666`) يرجع `False` فوراً لو `erp_intent == "question"`. فإرسال `erp_intent='question'` من الواجهة يعطّل المسار السريع. **إذن D.6 في الباك إند أقل بكثير مما كتبته سابقاً.**
7. **كود ميت:** `extracted_form_fields` في `search_service.py:905` دائماً `None`، فهيدر `## 🚨 ERP Form Filling Action Context` في `get_rag_system_prompt` لا يُحقن أبداً.
8. **زر 👁️ موجود:** `isVisionAgentMode` + `toggleVisionAgentMode()` في الواجهة (`copilot-chat.component.html:519-525`). الزر الجديد ⚡ لازم يتعايش معه.

### 0.2 تصحيح لبنود في الخطة السابقة (YAGNI)
- **حذف D.6.3.4** (حراسة `ErpNavigatorService`): الـ navigator لا يُستدعى إلا من المكوّن، فالحراسة عند مواضع الاستدعاء تكفي. يتأكد منها بـ grep في المرحلة 5.
- **حذف D.6.2.4** كخطوة إخفاء كروت: في Q&A لا تُنتج كروت أصلاً (لا حقول تُرسل). تبقى الكروت القديمة في المحادثة كما هي. نحجب فقط `canEscalateToVisionAgent`.
- **تعديل D.6.1.2:** حذف الكود الميت بدل "تحصينه".
- **D.6.1.4 (`_FORM_FILL_CONFIRMATION`):** لا يحتاج تعديل — يتعطل تلقائياً.

---

## 1. خريطة المشاريع والملفات

### المشروع A — `LMS_CO_Pilot` (FastAPI / Python) — `e:\Mazen\EgyDynamic\LMS_CO_Pilot`
سيتم تعديل:
- `src/data/screens_metadata.json` (D.5)
- `src/data/forms_metadata.json` (D.5 + D.2)
- `src/core/prompts.py` (D.2 + D.6)
- `src/services/agentic_stepper_service.py` (D.2)
- `src/services/forms_catalog_service.py` (D.5، فقط إن لزم التحقق من الـ alias lookup)
- `src/services/search_service.py` (D.6: حذف كود ميت فقط)
- `tests/unit/` (ملفات اختبار جديدة)

لن يتم تعديل: `vision_grounding_service.py`، `intent_router.py`، باقي برومتات الـ LMS (Whisper/Quiz/Summary/Normalization).

### المشروع B — `DynamicProLearn/learn-dynamic-pro-ui` (Angular 19) — `e:\Mazen\DynamicProLearn\learn-dynamic-pro-ui`
سيتم تعديل:
- `src/app/core/services/form-driver/control-interactor.ts` (D.1: `setNgSelect` سطر 208)
- `src/app/core/services/form-driver/form-inspector.ts` (D.2: `collectFormSchema` سطر 154)
- `src/app/core/services/erp-form-driver.service.ts` (D.2 hook الإجمالي سطر ~400، D.4 تصفير الصفوف)
- `src/app/core/services/form-driver/grid-driver.ts` (D.4، بعد قراءته في المرحلة 3)
- `src/app/core/services/erp-bridge.service.ts` (D.3: سطر 96-122)
- `src/app/shared/components/copilot-chat/copilot-chat.component.ts` (D.6)
- `src/app/shared/components/copilot-chat/copilot-chat.component.html` (D.6: سطر 518-537)
- `src/app/shared/components/copilot-chat/copilot-chat.component.css` (D.6: ستايل زر ⚡ والشارة)
- `public/lms-copilot.bundle.js` (يُولّد بالبناء فقط، لا يُحرّر يدوياً)

لن يتم تعديل: `copilot.service.ts` (الحمولة تعمل كما هي)، `erp-navigator.service.ts`.

### المشروع C — `DynamicProLearn/src/LearnDynamicPro.API` (.NET 10)
**لا تعديل.** (تأكدت: لا يمر عبره طلب البحث.)

### المشروع D — نظام الـ ERP المضيف (خارج نطاقنا)
**لا تعديل.** اعتماد خارجي: الجسر `window.DynamicERP` لا يوفر `submitActiveForm` في هذه النسخة، وسنتعامل مع غيابه بأمان.

### المشروع E — التوثيق
- `docs/ERP_COPILOT_MASTER_CHECKLIST.md` (تحديث الحالة بعد كل مرحلة)
- هذا الملف (يتحدّث بالنتائج الفعلية)

---

## 2. المراحل (كل مرحلة لها بوابة نجاح قبل الانتقال للتالية)

### المرحلة 0 — خط الأساس والاكتشاف (بدون أي تعديل في الكود)
**الهدف:** نعرف الوضع الحقيقي قبل أن نلمس أي شيء.
- [ ] 0.1 تشغيل `pytest` الحالي وتسجيل النتيجة كـ baseline (النجاح/الفشل الحالي).
- [ ] 0.2 قراءة `package.json` لتحديد أمر البناء `build:element` وأمر الاختبار الأمامي إن وجد.
- [ ] 0.3 `git status` + `git log -3` في المشروعين، وأخذ نسخة احتياطية لـ `screens_metadata.json` و`forms_metadata.json` (فهما ضخمان وتعديلهما حساس).
- [ ] 0.4 اكتشاف حي لشاشة 244 على الجهاز الثاني (CDP عبر الـ tunnel): تفريغ كل controls الفوتر (المحصل نقداً، الخصم، المتبقي، الإجمالي): الاسم، النوع، `formcontrolname`، قابل للتعديل أم لا. نتائجه تُكتب في الملف `docs/` كمرجع.
- [ ] 0.5 فحص سبب غياب الحقول الرقمية من `collectFormSchema` (هل تُستبعد عمداً؟ هل هي داخل container مستبعد؟).
- [ ] 0.6 إعادة تشغيل سيناريو الفاتورة الحالي وتسجيل: كم حقل تم ملؤه فعلاً مقابل ما قاله الجسر، لحسم موضوع `CustomerID` مقابل `customerID`.
- [ ] 0.7 قراءة `retryMessage` (`copilot-chat.component.ts:1206+`) و`executeGoalInCurrentDom` و`selectAskOption` وتحديد من يستدعي `streamQuery`.

**بوابة النجاح:** وثيقة نتائج المرحلة 0 جاهزة، وكل افتراض غير مؤكد في هذه الخطة أصبح حقيقة أو تم تعديل الخطة.

#### نتائج المرحلة 0 (نُفّذت بتاريخ 2026-11-01 — بدون أي تعديل كود)
- **0.1 pytest (baseline قبل أي تعديل):** `tests/unit` = **79 ناجح، 5 فاشل (قائمة مسبقاً، ليست من عملنا)**:
  - `test_citations_and_sources.py::test_rag_prompt_dynamic_boundaries`
  - `test_citations_and_sources.py::test_safe_rag_prompt_backwards_compatibility`
  - `test_multi_lesson_search.py::test_get_rag_system_prompt_multi_lesson`
    (الثلاثة تتوقع نصوصاً عربية قديمة، والبرومت الحالي إنجليزي → اختبارات متقادمة تُحدَّث في المرحلة 5 لأننا نعدّل نفس البرومت)
  - `test_forms_catalog.py::test_dynamic_scaling_and_fallback` (`page_id` يرجع 0 بدل 9999 في `get_prompt_schema_for_gemini` → يُفحص في المرحلة 1/4 لأنه نفس الدالة)
  - `test_erp_endpoints.py::test_erp_endpoints_validation_limits_422` (غير مرتبط؛ يُوثَّق ولا يُلمس)
  - **قاعدة:** معيار النجاح بعد كل مرحلة = لا فشل جديد فوق هذه الخمسة، وما نلمسه منها يُصلح.
- **0.2 أدوات الواجهة:** `build:element` = `ng run learn-dynamic-pro-ui:build-element && node scripts/bundle-element.js`. الاختبار `ng test` (Karma + Jasmine) متاح، فاختبار `pickBestOption` ممكن كوحدة.
- **0.3 Git:** الفرع `vision-agent` في المشروعين، شجرة العمل نظيفة عدا ملفي الـ docs. نسخ احتياطية لـ `screens_metadata.json` و`forms_metadata.json` محفوظة في مجلد `scratch/backup` ضمن مجلد artifacts.
- **0.4 اكتشاف حي لشاشة 244 (مؤكد من الجهاز الثاني):**
  - **"المحصل نقدا" = حقل `POPaid`** (number، قابل للتعديل). مؤكد بربط التسمية `.dp-edit__totlbl` بالحقل المجاور.
  - "اجمالي بعد الضرائب" = `TotalOrderBeforCurrancy` (معطّل، محسوب).
  - "خصم مسموح به" = `DiscountPercent`، و"مصاريف الشحن" = `shippingPrice`، و"عدد الأقساط" = `ISNumber`.
  - "الخزينة" و"الاجل على العميل" ليسا حقول رقمية بنفس النمط (الخزينة ng-select؛ والأجل عرض فقط).
  - **لا يوجد حقل `remind` ظاهر:** المتبقي محسوب ولا يُكتب يدوياً. سيُتحقق من تحدّثه تلقائياً في الاختبار الحي (المرحلة 4).
  - واجهة الجسر `window.DynamicERP` تحتوي: `listUserPages, getActiveScreen, getActiveFormContext, fillFormData, listScreens, navigateToScreen, triggerAddNew` — **لا `submitActiveForm`** (يؤكد D.3).
- **0.5 سبب غياب الحقول الرقمية من السكيما:**
  - في الـ DOM الحي الآن، تحت جذر النموذج 16 حقل إدخال غير select خارج الجدول، ودالة `collectFormSchema` الحالية (المصدر والبندل كلاهما يحتوي حلقة الإدخال) **كان ينبغي أن تجمعها**.
  - **سبب غيابها في لوج `y6p6` غير محسوم بعد.** أحتمالان: الشاشة كانت في حالة جذر مختلفة وقت الجمع (مثل مودال إضافة صف)، أو توقيت رسم الفوتر.
  - **مشكلة مؤكدة ثانية:** `findLabelForElement` يرجع تسمية فارغة لحقول الفوتر، لأن تسمياتها `.dp-edit__totlbl` وليست `label` داخل `.form-group`. فالـ AI يرى `POPaid` بلا أي دلالة عربية، فلا يربطه بعبارة "المحصل نقدا". **هذا سبب جذري كافٍ بذاته.**
  - **الإجراء:** (أ) إضافة بحث عن `.dp-edit__totlbl` في `findLabelForElement`، (ب) إضافة تتبع تشخيصي دائم في `collectFormSchema` يسجل عدد الحقول المفحوصة/المتخطاة وسبب التخطي، لحسم سبب الغياب في أول اختبار حي.
- **0.6 مفاتيح CDP (`CustomerID` مقابل `customerID`):** لم تُحسم بعد لأن حسمها يتطلب تنفيذ ملء حقيقي على الشاشة (تعديل بيانات حية). **يُؤجّل إلى اختبار المرحلة 4 الحي بموافقتك** على إنشاء مسودة فاتورة تجريبية دون حفظ.
- **0.7 مسارات استدعاء `streamQuery`:** ثلاثة فقط: `sendMessage` (668)، `executeGoalInCurrentDom` (796)، `selectAskOption` (1032). **`retryMessage` لا تستدعي `streamQuery` ولا تمرر حقولاً أو نية** (تستدعي `streamSearch` مباشرة)، فهي تعمل أصلاً كـ Q&A ولا تحتاج تعديلاً (يُلغى البند 5.4 الخاص بها).

#### تغييرات على الخطة بناءً على نتائج المرحلة 0
- **المرحلة 4 (D.2) أبسط وأدق:** حقل السداد معروف (`POPaid`). الهوك الحالي في `erp-form-driver.service.ts` (~سطر 421-433) يملك fallback `input[name*="paid" i]` الذي يطابق `POPaid` أصلاً، فلا حاجة لإعادة كتابته. العمل الفعلي: تسمية الفوتر في `findLabelForElement`، وتشخيص التتبع، وقاعدة السداد في برومت CDP، وإضافة `POPaid` لمخطط 244.
- **المرحلة 5:** إلغاء بند `retryMessage` (5.4).


### المرحلة 1 — D.5: إصلاح تعارض 244 / 290 (Python + JSON فقط)
- [ ] 1.1 `screens_metadata.json` (قرب سطر 13070): إزالة `sales`, `salesdetails`, `فواتير المبيعات`, `فاتورة مبيعات` من شاشة 290 فقط، مع إبقاء بقية aliases تحويلات المخازن.
- [ ] 1.2 `forms_metadata.json` (قرب سطر 36657): توجيه `"فاتورة مبيعات"`, `"فاتورة المبيعات"`, `"فواتير المبيعات"`, `"تسجيل مبيعات"` إلى `244`.
- [ ] 1.3 فحص أن لا alias آخر لـ "مبيعات" يشير لشاشات أخرى (بحث شامل بدل افتراض).
- [ ] 1.4 اختبار `tests/unit/test_forms_resolution.py` (جديد): جمل مثل "دخل فاتورة مبيعات جديدة..." تعيد 244، و"تحويل مخزن" تعيد 290.
- [ ] 1.5 اختبار `resolve_target_screen` في `agentic_stepper_service.py` بنفس الجمل.

**بوابة النجاح:** الاختبارات خضراء، وlog جديد يظهر `target_page_id: 244`.
**التراجع:** استعادة النسختين الاحتياطيتين.

### المرحلة 2 — D.1: أولوية المطابقة التامة في ng-select (Angular)
**الملف:** `control-interactor.ts` دالة `setNgSelect` (سطر 208).
- [ ] 2.1 استخراج دالة نقية `pickBestOption(options, term)` (قابلة للاختبار بدون DOM) بالترتيب: تطابق تام بعد التطبيع ← يبدأ بالمصطلح ← يحتويه، مع عقوبة على الخيار الذي يبدأ بـ "غير" إذا لم يحتوِ المصطلح "غير".
- [ ] 2.2 استبدال منطق الاختيار الحالي بها دون تغيير باقي سلوك الكتابة والانتظار.
- [ ] 2.3 اختبار وحدة (إن وجدت أداة اختبار في 0.2؛ وإلا سكربت تحقق منفصل): "مباشرة" تختار "مباشرة" لا "مبيعات غير مباشرة".
- [ ] 2.4 اختبار حي: ملء `ContractType = مباشرة`.

**بوابة النجاح:** الحالة المسجلة في `tnkf.log:16` لا تتكرر.
**التراجع:** `git checkout` للملف.

### المرحلة 3 — D.3 + D.4: الجسر وإعادة الملء النظيف (Angular)
- [ ] 3.1 `erp-bridge.service.ts:96-122`: فحص `typeof window.DynamicERP?.submitActiveForm === 'function'` قبل الاستدعاء، وإرجاع `ErpSaveResult` برسالة عربية واضحة ("الحفظ التلقائي غير مدعوم في هذه النسخة، اضغط حفظ يدوياً") دون رمي خطأ.
- [ ] 3.2 الحفاظ على سياسة المسودة: لا حفظ تلقائي إلا بنقر المستخدم أو بخيار `autoSaveAfterFill` الاختياري الموجود أصلاً.
- [ ] 3.3 D.4: قبل إدراج الأصناف، اكتشاف الصفوف غير الفارغة، وعرض تأكيد أو تصفير مسودة الجدول قبل الإضافة. **قرار مطلوب منك:** هل تفضل (أ) تصفير تلقائي بدون سؤال، أم (ب) سؤال المستخدم؟ توصيتي: (ب) لأن التصفير التلقائي قد يمحو عمل المستخدم.
- [ ] 3.4 قراءة `grid-driver.ts` أولاً لتحديد آلية الصفوف (`dataObject.rows` عبر الجسر أم DOM).

**بوابة النجاح:** إعادة تنفيذ نفس الأمر مرتين لا تضاعف الأصناف، ولا ظهور `TypeError` في اللوج.

### المرحلة 4 — D.2: التسوية النقدية (أخطر مرحلة)
**يبدأ بنتائج المرحلة 0.4 و0.5. لا يُنفّذ بدونها.**

**(أ) مسار الشات (Angular):**
- [ ] 4.1 `form-inspector.ts`: إدراج الحقول الرقمية/النصية الظاهرة (خاصة الفوتر) في السكيما إذا كان استبعادها غير مقصود، بدون إدخال حقول مخفية أو للقراءة فقط كمدخلات.
- [ ] 4.2 `erp-form-driver.service.ts` (~سطر 400): الإبقاء على هوك `$TOTAL`، وتحديث قائمة selectors بأسماء الحقل الحقيقية المكتشفة في 0.4 بدل التخمين (`paid/cash/pay/madfou`).
- [ ] 4.3 التحقق هل الـ ERP يحدّث `remind` تلقائياً بعد تغيير المحصل، فلا نكتبه يدوياً إلا إن لم يحدث.

**(ب) مسار CDP (Python):**
- [ ] 4.4 `prompts.py`: ثابت مشترك جديد `ERP_PAYMENT_RULES` يحمل قاعدة السداد/`$TOTAL` (مصدر واحد — DRY) ويُستخدم داخل `ERP_FORM_EXTRACTION_PROMPT_TEMPLATE` وداخل `extraction_prompt` في الـ stepper.
- [ ] 4.5 `agentic_stepper_service.py:350`: حقن `ERP_PAYMENT_RULES` في `extraction_prompt`.
- [ ] 4.6 `forms_metadata.json` المدخل 244: استبدال المخطط العام بمخطط حقيقي يشمل `customerID, ContractType, CostItemId, StoreID, SalesMan` وحقل السداد، وجريد `product, productQty, UnitPrice` بالمفاتيح الفعلية. **لا أخمّنها — تؤخذ من المرحلة 0.4.**
- [ ] 4.7 اختبار `tests/unit/test_extraction_prompts.py` (جديد): يتحقق أن البرومت يحتوي قاعدة `$TOTAL`، وأن مخطط 244 يحتوي حقل السداد.
- [ ] 4.8 اختبار حي للجملة: "وتم دفع الاجمالي حط قيمة الاجمالي في خانة المحصل نقدا".

**بوابة النجاح:** بعد تنفيذ الجملة، المحصل نقداً = الإجمالي والمتبقي = 0، في المسارين.
**خطر:** تعديل مخطط 244 قد يغيّر سلوك فواتير أخرى مولّدة آلياً. نختبر 3 شاشات أخرى من نفس النمط كانحدار.

### المرحلة 5 — D.6: فصل Q&A عن Action (الأغلب في Angular)

**قرارات التصميم المقترحة (تحتاج موافقتك):**
- ثلاثة أنماط متنافية: 💬 Q&A (افتراضي) ، ⚡ Action (in-DOM) ، 👁️ Vision (CDP، موجود).
- **لا حفظ للنمط في LocalStorage:** يبدأ دائماً Q&A (أمان: لا تنفيذ مفاجئ بعد إعادة التحميل). بديل: حفظه.
- **لا اكتشاف أوامر بالكلمات المفتاحية** في Q&A (يخالف سياسة "AI-only" في المشروع). نكتفي بشارة ثابتة تذكّر: "فعّل ⚡ للتنفيذ التلقائي".

**Angular — `copilot-chat.component.ts`:**
- [ ] 5.1 إضافة `isActionMode = false`، وتعديل `toggleVisionAgentMode` و`toggleActionMode` ليكونا متنافيين.
- [ ] 5.2 `sendMessage`: لا تغيير في تفرّع الوكيل البصري.
- [ ] 5.3 `streamQuery` (سطر 1048): في Q&A:
  - تخطي كتلة الملاحة (سطر 1055-1110) و`prepareFreshForm` (1112-1125) و`collectFormSchema` (1127-1132).
  - `resolvedIntent = 'question'` يُمرَّر لـ `streamSearch`، وتمرير `visibleFields`/`formSchema` بـ `undefined`، و`canEscalateToVisionAgent = false`.
- [ ] 5.4 الأنماط التي تستدعي `streamQuery` مباشرة:
  - `executeGoalInCurrentDom`: يضبط `isActionMode = true`.
  - `selectAskOption`: لا تحتاج تعديلاً (تظهر من تدفق Action).
  - `retryMessage`: تخزين `mode` داخل `ChatMessage` وإعادة استخدامه (بعد قراءتها في 0.7).
- [ ] 5.5 تسجيل `mode` في `telemetry.log('USER_QUERY', ...)` لتسهيل تتبع اللوجات الميدانية.

**Angular — `copilot-chat.component.html` (سطر 518-537):**
- [ ] 5.6 زر ⚡ بجانب 👁️ مع `title` واضح، وclass `active`.
- [ ] 5.7 `placeholder` ثلاثي: Q&A / Action / Vision (الموجود).
- [ ] 5.8 شارة نمط صغيرة فوق حقل الإدخال.

**Angular — `copilot-chat.component.css`:**
- [ ] 5.9 ستايل زر ⚡ والشارة، متناسق مع `.copilot-mode-toggle-btn` الموجود (تجنّب CSS مكرر).

**Python — `prompts.py`:**
- [ ] 5.10 `_RAW_RAG_SYSTEM_PROMPT`: إضافة بند إرشادي: للأسئلة الإجرائية، شرح تسلسلي نصي من محتوى المحاضرات مع مسار القوائم، دون الإشارة إلى كروت أو تعبئة تلقائية. (الملاحظة: البرومت مبني على {num_sources} و{forbidden_citation}، فالإضافة تُراعي الأقواس المزدوجة `{{ }}`.)
- [ ] 5.11 `get_rag_system_prompt`: حذف فرع `extracted_form_fields` الميت والمعاملين غير المستخدمين، مع تعديل مواضع الاستدعاء في `search_service.py:354-358` و`915-921`.

**Python — `search_service.py`:**
- [ ] 5.12 حذف تمرير `extracted_form_fields` (سطر 905 و920) وتحديث المتغير `visible_fields` غير المستخدم في `get_rag_system_prompt` (سطور 353-358).
- [ ] 5.13 **لا تغيير** في المسار السريع (يتعطل بـ `erp_intent='question'`).

**الاختبارات:**
- [ ] 5.14 `tests/unit/test_rag_prompt.py` (جديد): البرومت لا يحتوي "ERP Form Filling Action Context"، ويحتوي توجيه الشرح الإجرائي.
- [ ] 5.15 `tests/test_search_stream_and_feedback.py` الموجود: تشغيله كاملاً (قد يتأثر بتغيير التوقيعات).
- [ ] 5.16 اختبار تكاملي: طلب بـ `erp_intent='question'` + `form_schema` لا يُنتج حدث `form_fill`.

**بوابة النجاح:**
- "كيف أعمل فاتورة مبيعات؟" في Q&A: شرح نصي، لا تنقل، لا كارت، وزمن أسرع.
- نفس الجملة بصيغة أمر في ⚡: تنقل وتعبئة.

### المرحلة 6 — البناء والتحقق الميداني
- [ ] 6.1 `npm run build:element` (الأمر يُؤكَّد في 0.2) وتحديث `public/lms-copilot.bundle.js`.
- [ ] 6.2 كسر الكاش على الجهاز الثاني: تحميل البندل بمعامل نسخة أو Hard Refresh، مع التحقق من الإصدار المحمّل (ظهور زر ⚡).
- [ ] 6.3 سيناريوهات القبول الكاملة (القسم 3).
- [ ] 6.4 تحديث `ERP_COPILOT_MASTER_CHECKLIST.md` بالحالة الفعلية وتصحيح بنود D.6 وفق القسم 0.2.
- [ ] 6.5 اقتراح رسالة commit تقليدية (بدون تنفيذ).

---

## 3. سيناريوهات القبول النهائية

1. **Q&A:** "كيف أسجل فاتورة مبيعات؟" ← شرح نصي تسلسلي، لا تنقل، لا `form_fill`، لا كارت.
2. **Q&A + أمر:** "اذهب للمبيعات" ← يجيب نصياً/يشرح، ولا ينتقل (والشارة تذكّر بـ ⚡).
3. **Action:** أمر فاتورة مبيعات كامل ← ينتقل لـ 244، يملأ العميل وطريقة البيع "مباشرة" (لا "غير مباشرة")، الأصناف، المحصل نقداً = الإجمالي، المتبقي 0، **بدون حفظ تلقائي**.
4. **إعادة نفس الأمر** في نفس الشاشة ← لا تضاعف أصناف.
5. **Vision 👁️:** نفس الأمر ← `target_page_id: 244` ونفس النتيجة.
6. **ضغط حفظ تلقائي** مع جسر بلا `submitActiveForm` ← رسالة واضحة، لا خطأ.
7. **انحدار:** ثلاث شاشات أخرى (مشتريات، قيد يومية، شاشة تحويل مخزن) تعمل كما كانت.

---

## 4. المخاطر المتبقية (بصراحة)

- لا أستطيع تأكيد اسم حقل "المحصل نقداً" الحقيقي قبل المرحلة 0.4. إن كان محسوباً أو للقراءة فقط فسنحتاج بديلاً.
- تعديل مخطط 244 يؤثر على كل المسارات التي تعتمد `forms_metadata.json` (يُعالج بالاختبارات والانحدار).
- لا أداة اختبار أمامية مؤكدة؛ إن لم توجد فالتحقق الأمامي حي ويدوي وسأوثقه صراحة.
- أي تغيير في الجسر المضيف أو إصدار الـ ERP خارج سيطرتنا.
- البناء قد يكشف أخطاء TypeScript في أماكن لم نلمسها.

## 5. قرارات مطلوبة منك قبل البدء

1. D.4: تصفير الصفوف تلقائياً أم بسؤال المستخدم؟ (التوصية: بسؤال)
2. D.6: هل يبدأ الشات دائماً في Q&A أم يتذكر آخر نمط؟ (التوصية: دائماً Q&A)
3. هل أبدأ بالمرحلة 0 فقط (اكتشاف بلا تعديل كود) ثم أعرض عليك نتائجها قبل المرحلة 1؟ (التوصية: نعم)
