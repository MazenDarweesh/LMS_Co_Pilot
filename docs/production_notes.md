---
document_type: "Architectural Decision Registry (ADR) & Post-Production Notes"
last_updated_commit: "e02f7d1"
last_updated_date: "2026-09-10"
adrs_count: 12
status: "Active"
---

# ملاحظات ما بعد الإنتاج (Post-Production & Scaling Notes)
## LMS AI Co-Pilot

هذا الملف مخصص لتوثيق التحسينات المعمارية التي يجب النظر فيها مستقبلاً (بعد الإنتاج).

---

## 🏛️ قرارات معمارية معتمدة (Architectural Decision Records - ADR)

### ADR-01: استبعاد Redis في مرحلة الـ MVP
**القرار:** تم اتخاذ قرار واعٍ بعدم استخدام Redis كطبقة تخزين مؤقت أو طابور مهام في هذه المرحلة (MVP).
**السبب (Context):** 
1. **الوكلاء (LangGraph):** نعتمد على `AsyncPostgresSaver` مع `Connection Pool` متين في قاعدة بيانات PostgreSQL لحفظ حالة الوكلاء والأحداث (Event Sourcing) بدلاً من `RedisSaver`.
2. **صلاحيات الـ LMS:** استخدام `cachetools.TTLCache` (في الذاكرة العشوائية لمدة 5 دقائق) يكفي حالياً ولا يسبب ضغطاً على الـ ERP.
3. **طوابير المهام (Background Jobs):** استخدام `asyncio.Semaphore` و `TaskGroup` داخل `pipeline_orchestrator.py` يكفي لإدارة معالجة الملفات الصوتية دون تعقيد البنية التحتية.

### ADR-09: إدارة أقفال المزامنة للدروس (Per-Lesson Lock) والتوسع الأفقي (Multi-Pod Deployment)
**القرار:** استخدام `asyncio.Lock` محلي في الذاكرة مع حماية TOCTOU وتقييد الذاكرة (Bounded Pruning) لمرحلة الإنتاج الحالية (Single-Replica).
**السبب (Context):**
1. **طبيعة العملية:** معالجة الفيديو والـ Ingestion قد تستغرق من 30 إلى 120 ثانية (تنزيل، تقطيع، تفريغ صوتي، وتضمين متجهات).
2. **خطورة Postgres Advisory Locks في العمليات الطويلة:** استخدام `pg_advisory_xact_lock` يقتضي حجز اتصال نشط من `db_pool` طوال مدة المعالجة (حتى دقيقتين)، مما يؤدي سريعاً إلى استنزاف مجمع الاتصالات (Connection Pool Starvation) وتوقف طلبات الـ API الأخرى.
3. **استبعاد Redis في الـ MVP (وفقاً لـ ADR-01):** لا توجد حالياً بنية تحتية لـ Redis في بيئة الـ MVP.
**خطة الترقية عند الانتقال إلى Multi-Pod (Replicas > 1):**
عند تشغيل أكثر من Pod في Kubernetes أو وراء Load Balancer، يتم اعتماد أحد الخيارين:
- **الخيار المفضل (بدون Redis):** إنشاء جدول عقود تأجير مؤقتة في PostgreSQL باسم `lesson_ingest_leases` (بأعمدة: `lesson_id`, `pod_id`, `lease_expires_at`). يتم حجز القفل باستعلام ذري مدته 5 دقائق (`INSERT ... ON CONFLICT DO UPDATE WHERE lease_expires_at < NOW()`) ثم تحرير الاتصال فوراً للـ Pool دون حبس الاتصال.
- **خيار Redis Distributed Lock:** عند إدخال Redis في البنية التحتية طبقاً لمراجعة ADR-01، يتم استخدام `Redlock` أو `redis.lock(f"ingest:lesson:{lesson_id}", timeout=300)`.
**قيد التشغيل الحالي:** يُمنع نشر أكثر من نسخة Pod واحدة (`replicas: 1`) حتى يتم تطبيق جدول عقود التأجير أو Redis.

### ADR-10: تشغيل نموذج ArabGuard (0.2B) عبر ONNX Runtime كـ Secondary ML Classifier
**القرار:** الاعتماد حالياً في سياج المدخلات على مصفوفة العامية المصرية + SemGuard Triple-Anchor بمحرك BGE-M3، مع تأجيل تشغيل نموذج `ArabGuard` أو `MARBERTv2` المصغر إلى مرحلة ما بعد الإنتاج.
**السبب (Context):**
1. دمج نموذج تصنيف عصبي مستقل (حتى لو كان 0.2B) يتطلب تضمين `onnxruntime` وتجهيز حزم أوزان إضافية وزيادة استهلاك الذاكرة العشوائية بمقدار 300-500MB.
2. محرك BGE-M3 المحمل بالفعل في الذاكرة + تقنية المراسي الدلالية الثلاثية (Triple-Anchor Relative Margin) يحققان دقة فائقة في كشف الهجمات بالعامية والفصحى بدون أي مكتبات جديدة أو زمن استجابة إضافي (<0.3ms).
**خطة الترقية مستقبلاً:**
بناء واجهة `MLClassifierHook` في `guardrails_service.py` لاستدعاء حاوية ONNX مصغرة اختيارياً للحالات الحدودية المشبوهة.

### ADR-11: تدقيق الهلوسة بنموذج خارجي (Cross-Model Dual-LLM Audit) في عمليات الـ Batch والمراجعة الدورية
**القرار:** عدم استدعاء نماذج LLM خارجية (كـ Claude 3.5 Sonnet أو GPT-4o) في المسار الحي اللحظي (Real-Time Search Ingress)، وحصر الفحص اللحظي على الفحص الحتمي للكيانات (Deterministic EAEV).
**السبب (Context):**
1. استدعاء API خارجي على كل إجابة في الـ Real-Time يضيف من 1.5 إلى 2.5 ثانية تأخير لكل طالب، ويضاعف تكلفة الاستهلاك السحابي، ويدخل نقطة فشل خارجية إضافية.
2. الفحص الحتمي EAEV يمسك 100% من اختلاق الأرقام والتواريخ والأكواد في أقل من 1ms بصفر تكلفة.
**خطة الترقية مستقبلاً:**
تفعيل نموذج LLM مستقل كـ External Judge في الـ Background Pipelines والـ Batch Auditing الدوري لسجلات المحادثات لتطهير الكاش وتقييم دقة النموذج الأساسي دون التأثير على زمن استجابة الطالب.

### ADR-12: كشف الهجمات السلوكية متعددة الجولات (Multi-Turn Behavioral Anomaly Detection)
**القرار:** تأجيل تعقب أنماط الاستدراج التدريجي متعدد الجولات (Multi-turn progressive jailbreaking) إلى حين دمج Redis في النظام.
**السبب (Context):**
1. كشف الهجمات الموزعة على عدة رسائل يتطلب تخزين حالة تراكمية سريعة وموزعة (Distributed Session State) مع احتساب درجات ريبة تراكمية (Suspicion Anomaly Scores) عبر جلسة الطالب.
2. تطبيقها محلياً في ذاكرة الـ Pod غير مجدٍ مع التوسع الأفقي، ويتعارض مع ADR-01 بتأجيل Redis.
**خطة الترقية مستقبلاً:**
عند توفر Redis، يُنشأ مسار تتبع سلوكي يسجل أحداث الالتفاف لكل مستخدم ويفرض حظراً تصاعدياً تلقائياً.

---

## 1. استبدال الـ In-Memory Cache بـ Redis وإبطاله لحظياً
**المشكلة الحالية:**
الـ TTL لمدة دقيقة أو 5 دقائق للكاش المحلي يعني أن تغيير صلاحيات المستخدم لن ينعكس فوراً (Stale Data).
**الحل (Post-Production):**
استخدام خادم Redis كطبقة كاش مركزية. والأهم، بناء مسار `POST /webhooks/invalidate-cache` يستدعيه الـ .NET فور تعديل صلاحيات أي مستخدم لإبطال الكاش الخاص به (Cache Invalidation) فوراً.

## 2. نظام النسخة الاحتياطية عند توقف الـ LMS (Graceful Degradation)
**المشكلة الحالية:**
النظام مصمم كـ `Fail-Closed`، فإذا سقط اتصال الـ LMS، يتوقف الـ Co-Pilot كلياً ويرجع 503.
**الحل (Post-Production):**
أرشفة آخر صلاحيات معروفة للمستخدمين في Redis بدون مدة انتهاء. عند سقوط الـ LMS، يعتمد الـ Co-Pilot على هذه النسخة مع تسجيل تحذير (Warning) للمشرفين، بدلاً من إيقاف الخدمة عن الطلاب.

## 3. مستقبل المحتوى المستقل للطلاب (Future Standalone Content)
**الوضع الحالي:**
المحتوى المستقل (Standalone) وقوائم التشغيل (Playlists) محصورة برمجياً للمشرفين (`Admin`) فقط عن طريق وسم `content:standalone`.
**المطلوب مستقبلاً إذا أردنا إتاحته للطلاب:**
يجب تعديل `auth_service.py` ليقوم بالاستعلام من قاعدة بيانات محلية (PostgreSQL) لمعرفة الفيديوهات المخصصة لدور الطالب (`target_roles`) وشركته (`tenant_id`)، ثم إضافة `video:vid_guid` لقائمة الـ Entities الخاصة به بدلاً من منحه وسم الـ Content المفتوح.

## 4. استراتيجية الذكاء الاصطناعي الصوتي (Speech AI Strategy)
المشروع حالياً يستخدم `Whisper-large-v3` عبر API (مثل Groq). هذا الخيار ممتاز وسريع ومجاني للبداية. ولكن مع زيادة الضغط (Traffic)، يجب اتباع خريطة الطريق التالية:

**أ. الترتيب الاستراتيجي للانتقال (ASR Alternatives):**
1. **Hamsa API:** الانتقال الأول والأسهل. منصة عربية تتعرف على اللهجات تلقائياً (Dialect Detection) وممتازة في الـ Code-switching.
2. **Munsit API:** الخيار التجاري الأقوى في دقة اللهجات الصعبة.
3. **NVIDIA FastConformer Arabic (Self-Hosted):** الانتقال النهائي للـ Open Source للتخلص من تكلفة الـ API.

**ب. متطلبات استضافة FastConformer (إنتاج فعلي):**
* **البنية التحتية (Hardware):** سيرفر GPU مثل AWS EC2 (g4dn / g5) أو RunPod مزود بـ A10/A100 وذاكرة 32GB كحد أدنى.
* **البرمجيات (Software):** لا يمكن تشغيله عبر `transformers` عادية. يجب وضعه داخل حاوية **NVIDIA Triton Inference Server** مع `nemo_toolkit[asr]` لإدارة طوابير الطلبات والاتصال عبر `gRPC`.
* **العزل (Microservice):** يجب أن يُعزل FastConformer في سيرفر مستقل. في `transcription_service.py`، سيتم بناء "Adapter" يحول مخرجات Triton إلى صيغة `TranscriptionSegment` المتوافقة مع النظام.
* **جودة الصوت المسبقة:** النماذج المحلية صارمة. تأكد من أن الـ `audio_downloader` يخرج الصوت بدقة **16kHz Mono** بمقاطع من 15-30 ثانية لتجنب `OOM`.

## 5. التعرف على اللهجات والوكيل الصوتي (Voice Tutor & Dialect ID)
* **Dialect ID Routing:** مستقبلاً، يمكن إضافة مصنف (Classifier) مثل `ArTST v2` يكتشف اللهجة، ثم يمررها لـ Gemini Prompt ليزيد من دقة تنقيح النص وتطهيره.
* **Interactive Voice Tutor:** بعد استقرار النظام، يمكن إضافة VAD (Voice Activity Detection) ومولد صوتي (TTS) مثل Habibi-TTS لبناء مدرس صوتي تفاعلي كامل.
* **Audio Gates:** تطبيق فلاتر طاقة (RMS/Energy) في `audio_downloader` لرفض المقاطع الفارغة أو المزعجة قبل إهدار موارد الـ GPU عليها.

## 6. سجل التراخيص التجاري (License Registry)
لحماية المشروع تجارياً في بيئة الإنتاج، هذه هي تراخيص النماذج الحالية:
* `whisper-large-v3` (OpenAI): **MIT License** ✅ (مسموح تجارياً)
* `BAAI/bge-m3` (Dense Embeddings): **MIT License** ✅ (مسموح تجارياً)
* `BAAI/bge-reranker-v2-m3`: **MIT License** ✅ (مسموح تجارياً)
* `Gemini API` (Google): **Google ToS** ✅ (مسموح تجارياً عبر السحابة)
* `Qdrant` (Vector DB): **Apache 2.0** ✅ (مسموح تجارياً)

## 7. مهام يجب استكمالها بناءً على Master Plan V2 (الخطوات المتخطاة)
أثناء اندفاعنا في تأمين محرك البحث، قمنا بتخطي مرحلتين أساسيتين يجب العودة لهما:

**أ. (الأسبوع 6) الـ PDF Ingestion:**
نحن نعالج ملفات اليوتيوب بنجاح (Audio -> Whisper)، لكن مسار معالجة الـ PDF لم يتم كتابته بعد في `src/services/pdf_service.py`.
* **⚠️ تحذير ترخيص (Felo Insight):** مكتبة `marker-pdf` التي خططنا لها تحمل ترخيص **GPL-3.0**. إذا كان هذا المشروع تجارياً مغلق المصدر، **يُمنع استخدام Marker** إلا بشراء رخصة تجارية.
* **البديل المقترح:** استخدام `MinerU` (دقيق للـ Layouts) أو `MarkItDown` (سريع وممتاز للـ Markdown) أو الاعتماد على `PyMuPDF` (ترخيص مزدوج AGPL/Commercial) بحذر. يجب أخذ قرار تجاري هنا قبل برمجة الخدمة.

**ب. (الأسبوع 9) إدارة المحتوى المستقل (Standalone & Playlists):**
لم نقم بإنشاء جداول `standalone_videos` و `playlists` في قاعدة بيانات PostgreSQL ولم نبنِ الـ Admin API الخاصة بها في `router.py`.
* **Felo Insight:** هيكلة الـ Qdrant التي بنيناها بـ `is_tenant=True` مثالية لهذا الغرض. يكفينا حفظ الفيديوهات وقوائم التشغيل كمتجهات في نفس الـ Collection `learning_content` مع استخدام `playlist_id` أو `video_id` في الـ Payload للتصفية.

## 8. أدوات القراءة الخارجية الحية (External Read Tools / APIs)
* **المشكلة الحالية:**
  النظام معزول عن أي مصادر خارجية؛ لا يمتلك أدوات قراءة مثل (Web Search API) للبحث عن أحدث التحديثات، أو استعلامات قواعد البيانات الحية (Text-to-SQL) للاستعلام عن درجات الطالب الحالية، أو مواعيد تسليم الواجبات، أو حالة الحضور في نظام الـ LMS.
* **الحل والتطوير المستقبلي (Post-Production):**
  تزويد الوكيل الذكي (LangGraph Agent) بأدوات قراءة متخصصة (`External Read Tools`) يتم تفعيلها ديناميكياً عند حاجة استفسار الطالب لبيانات حية من خارج المحتوى المؤرشف في Qdrant.

## 9. حدود EAEV الحتمي وخارطة طريق كشف الهلوسة الدلالية (Paraphrased Hallucination Detection)
* **الحدود الحالية (Boundaries):**
  محرك EAEV المعتمد حتمي وسريع جداً (<1ms)، وهو متخصص بنسبة 100% في التقاط الاختلاق الصريح للأرقام، التواريخ، الأكواد، والنسب المئوية التي لم ترد في مقاطع الدرس (`text_msa`). لكنه **لا يكتشف** التناقضات المنطقية الدقيقة المعاد صياغتها بنفس الكلمات (Semantic Paraphrasing / Reasoning Fallacies).
* **الحل المستقبلي (Post-Production):**
  دمج نماذج NLI (Natural Language Inference) متخصصة ومصغرة (مثل MiniLM-L6-MNLI) أو تشغيل Decomposed Atomic Claims في خط معالجة غير متزامن (Async Offline Pipeline) لتقييم الروابط المنطقية دون تعطيل الـ Real-Time Ingress.

## 10. عقد سحب البث اللحظي مع الـ Frontend (Streaming Partial-Withdrawn Contract)
* **المشكلة الحالية:**
  محول البث SentGuard يفحص الجمل لحظياً، لكن إذا بدأت جملة مشبوهة أو حدث تسريب أمني بعد تسليم جمل أولى سليمة، يجب عدم ترك الجزء الأول معلقاً في واجهة الطالب.
* **العقد المتفق عليه مستقبلاً مع فريق Angular:**
  عند رصد انتهاك أمني أو هلوسة حرجة أثناء الـ SSE Streaming:
  1. يقوم السيرفر بقطع التدفق فوراً وإرسال حدث خاص بصيغة SSE:
     `data: {"type": "stream_revoked", "reason": "security_violation", "message": "تم سحب الرد لمخالفته معايير الأمان"}`
  2. يقوم كود الـ Frontend (Angular) بمحو الـ Buffer المحلي فوراً من شاشة المحادثة وعرض بطاقة تنبيه آمنة بديلة.

## 11. سياسة الحظر التصاعدي للـ DoS في SecurityBlacklistCache (Progressive Banning)
* **السياسة المعتمدة لمرحلة ما بعد الإنتاج:**
  بدلاً من مجرد TTL ثابت بـ 60 ثانية للمهاجمين، يتم تحويل الكاش المحلي إلى نظام حظر متدرج:
  - المخالفة الأولى: رفض فوري بـ TTL 60 ثانية.
  - 3 إلى 5 مخالفات متتالية خلال 5 دقائق: حظر مؤقت للمستخدم أو الـ IP لمدة 15 دقيقة (`HTTP 429 Too Many Requests`).
  - 20 مخالفة خلال ساعة: عزل لمدة 24 ساعة مع إرسال إشعار فوري (Prometheus Alert / Webhook) لمسؤولي النظام.

