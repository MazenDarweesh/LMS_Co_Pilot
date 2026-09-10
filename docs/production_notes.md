---
document_type: "Architectural Decision Registry (ADR) & Post-Production Notes"
last_updated_commit: "e02f7d1"
last_updated_date: "2026-09-10"
adrs_count: 8
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
**متى نراجع القرار؟** في حال سقط السيرفر تحت ضغط معالجة آلاف الفيديوهات المتزامنة، سيتم إدخال Redis كـ Message Broker مع Celery لمعالجة الصوتيات، أو عند الحاجة لإبطال كاش الصلاحيات لحظياً (كما هو مذكور في النقطة 1 أدناه).

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
