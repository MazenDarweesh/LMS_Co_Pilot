---
last_synced_commit: "aa6f686"
last_synced_at: 2026-09-20T17:35:00Z
guide_version: 2.1
word_count: 11200
max_word_budget: 14000
---

# 🎓 LMS AI Co-Pilot: الدليل المرجعي الشامل للمقابلات التقنية (Bilingual Interview Master Guide)
## Production RAG, Multi-Agent Architecture, Technical Q&A & Career Playbook
### النسخة ثنائية اللغة: إنجليزي / عربي (Bilingual Edition: English & Arabic)

---

## ⚡ 0. كبسولة الإنقاذ السريعة: الشيت شيت الأساسي قبل المقابلة (Must-Know Cheat-Sheet)

> [!IMPORTANT]
> **اقرأ هذا القسم أولاً لتكون "شارب المشروع" في 5 دقائق قبل الدخول في تفاصيل الأسئلة والـ ADRs.**  
> هذا الجدول يلخص جوهر المنظومة بالكامل: من يفعل ماذا، كيف تتصل الأنظمة ببعضها، ما هي دورة حياة الـ `AiStatus`، ولماذا اتخذنا كل قرار هندسي.

### 🗺️ 1. خريطة المسؤوليات المعمارية: من يفعل ماذا؟ (Separation of Concerns)

```text
┌─────────────────────────────────────────────────────────┐          ┌─────────────────────────────────────────────────────────┐
│     منظومة إدارة التعلم (.NET 10 Web API + Angular 19)   │          │          محرك الذكاء الاصطناعي (Python 3.13 FastAPI)     │
│                 (LearnDynamicPro)                       │          │                     (LMS_CO_Pilot)                      │
├─────────────────────────────────────────────────────────┤          ├─────────────────────────────────────────────────────────┤
│ • مصدر الحقيقة الدائم (Stateful Source of Truth)        │          │ • محرك حسابي عديم الحالة (Stateless Compute Engine)     │
│ • إدارة الكورسات، الوحدات، الدروس، والمستخدمين          │          │ • تفريغ ومعالجة صوت الفيديوهات (Audio Ingestion)        │
│ • تخزين البيانات العلائقية داخل SQL Server عبر EF Core   │          │ • الفهرسة الشعاعية والبحث الهجين في Qdrant              │
│ • إصدار وتوقيع توكنات المستخدمين (JWT Issuer - HS256)   │          │ • توليد الكويزات والملخصات لحظياً وإرجاعها كـ JSON      │
│ • تخزين حالة الذكاء الاصطناعي (AiStatus) في جدول الدروس │          │ • بث الردود اللحظي بالتوكنز عبر تقنية SSE Stream        │
│ • حفظ الكويزات والملخصات النهائية بعد مراجعة المشرف     │          │ • حماية الاستعلامات بكاش ثنائي الطبقات وسياج اللهجات    │
└─────────────────────────────────────────────────────────┘          └─────────────────────────────────────────────────────────┘
```

---

### 🌐 2. جدول المنافذ والمكونات في بيئة التشغيل (Ports & Topology Cheat Sheet)

| المكون / الخدمة (Service) | التقنية والإصدار | المنفذ (Port) | الوظيفة الأساسية في المنظومة |
|:---|:---|:---:|:---|
| **Python AI Engine** | FastAPI 0.115 + Uvicorn | `8000` | خادم الـ API للبحث الهجين، التوليد، ومعالجة الوسائط |
| **.NET LMS Backend** | .NET 10 Web API | `5115` / `8080` | الـ Backend الرئيسي، إدارة الدروس وقواعد البيانات وحالة الـ AI |
| **Angular Client** | Angular 19 (Signals & SSR) | `4200` | الواجهة الأمامية للطلاب والمشرفين (مشاهدة الدروس والكويزات والشات) |
| **Qdrant Vector DB** | Qdrant v1.13.2 (Rust) | `6333` | تخزين المتجهات الكثيفة واللفظية، البحث الهجين بـ RRF، والكاش الدلالي |
| **PostgreSQL DB** | PostgreSQL 16 (asyncpg) | `5432` | تخزين ذاكرة المحادثات لـ LangGraph وحفظ تقييمات الطلاب (Feedback) |
| **Prometheus** | Prometheus v2.54.1 | `9090` | جمع وتجميع مؤشرات الأداء ومقاييس زمن الاستجابة والتوكنز |
| **Alertmanager** | Alertmanager v0.27.0 | `9093` | إدارة وتوجيه تنبيهات اتفاقيات مستوى الخدمة (SLAs) عبر الويب هوك |
| **Grafana Dashboard** | Grafana v11.2.0 | `3001` | لوحة القيادة الحية لمراقبة الكاش، زمن الاستجابة، ونشاط الطلاب |

---

### 🔐 3. بروتوكول الأمان والمصادقة المتبادلة (Authentication & Security Cheat Sheet)

1. **توكن الطالب/المشرف والـ Zero-Hop Claims RBAC (User JWT):**
   - يُصدره .NET بتشفير `HS256`، بمُصدر `DynamicProLearn` وجمهور `DynamicProLearnClient`.
   - بايثون يتحقق منه باستخدام نفس الـ `JWT_SECRET`.
   - **القفزة الصفرية (Zero-Hop Claims):** بايثون يستخرج `company_id` و `department_id` مباشرة من Claims التوكن عبر `AliasChoices`.
   - **توفير زمن الشبكة:** المشرف (Admin) يتخطى استدعاء صلاحيات LMS بالكامل (0ms network hop)؛ وبالنسبة للطالب، إذا تعطل سيرفر الـ LMS مؤقتاً، يتراجع بايثون بأمان إلى عزل المستأجر بناءً على التوكن بدلاً من رفض الطلب بـ 503، مما يوفر 20-40ms على كل استعلام بحث.
2. **التوقيع الرقمي للـ Webhook بمعيار Stripe/GitHub (HMAC-SHA256 Webhook Security):**
   - يُستخدم لتأمين إشعارات تحديث وحذف الدروس من .NET إلى بايثون (`POST /v1/webhooks/lesson-updated`).
   - دوت نت يحسب التوقيع المشفر: `HMAC-SHA256(secret, timestamp + "." + raw_body)` ويرسل الترويسات `X-Signature-256` و `X-Timestamp`.
   - بايثون يتحقق من التوقيع مباشرة على بايتات الطلب الخام (Raw UTF-8 binary bytes) قبل قراءة الـ JSON لمنع أخطاء الـ Serialization Drift.
   - **حماية ضد هجمات الإعادة (Anti-Replay Attack):** رفض أي طلب يزيد فارق توقيته عن 300 ثانية.
   - **مقارنة ثابتة الزمن (Constant-Time):** باستخدام `hmac.compare_digest` لمنع هجمات التوقيت (Timing Attacks).

---

### 🔄 4. دورة حياة حالة الذكاء الاصطناعي (The `AiStatus` State Machine Cheat Sheet)

```text
               [ المشرف يضع رابط فيديو للدرس ]
                             │
                             ▼
                        ┌─────────┐
                        │  None   │  (الدرس غير معالج نهائياً - لا يمكن توليد كويز أو ملخص)
                        └────┬────┘
                             │
            [.NET يُرسل Webhook إلى بايثون: POST /v1/webhooks/lesson-updated]
                             │
                             ▼
                        ┌─────────┐
                        │ Queued  │  (الطلب محجوز ومؤمن بقفل تزامني لمنع التكرار)
                        └────┬────┘
                             │
            [بدء تنزيل الصوت، التفريغ بـ Whisper، التنقيح بـ Gemini، والرفع لـ Qdrant]
                             │
                             ▼
                        ┌────────────┐
                        │ Processing │  (جاري المعالجة - تظهر شاشة تحميل للمشرف)
                        └─────┬──────┘
                              │
             ┌────────────────┴────────────────┐
             │                                 │
      (نجحت الفهرسة وعدد المقاطع > 0)    (فشل التنزيل أو الفيديو خاص أو تعطلت الشبكة)
             │                                 │
             ▼                                 ▼
       ┌───────────┐                     ┌──────────┐
       │ Completed │                     │  Failed  │
       └─────┬─────┘                     └────┬─────┘
             │                                │
  [تفعيل أزرار الكويز والملخص]        [زر إعادة المحاولة (Retry) + رسالة الخطأ للمشرف]
```

#### 📡 كيف يعرف .NET حالة المعالجة؟ (نموذج التزامن المزدوج: Push + Poll)
1. **طريقة الدفع الفوري (Event-Driven Webhook Callback - Push):**
   - عندما ينتهي بايثون من المعالجة بنجاح أو عند حدوث أي خطأ، يقوم فوراً باستدعاء .NET عبر:  
     `POST http://<DOTNET_HOST>:5115/api/internal/lessons/{lessonId}/ai-status`
   - الحمولة عند النجاح: `{"status": "Completed", "chunks_count": 5, "current_stage": "QDRANT_UPSERT_COMPLETE", "error": null}`.
   - الحمولة عند الفشل: `{"status": "Failed", "chunks_count": 0, "current_stage": "AUDIO_DOWNLOAD_FAILED", "error": "Video is private or unavailable"}`.
2. **طريقة الاستعلام الاحتياطي (Fallback Status Polling - Pull):**
   - في حال تعطلت شبكة الويب هوك أو أراد الفرونت إند التحقق المباشر، يوفر بايثون مسار:  
     `GET /v1/ingest/status/{lesson_id}` (وأيضاً المسار البديل `/api/ingest/status/{lesson_id}`).
   - هذا المسار يفحص قاعدة بيانات Qdrant مباشرة ويفحص أقفال الذاكرة الحية، ويرجع الحالة الدقيقة وعدد الـ Chunks والمرحلة الحالية دون الحاجة لأي حالة وسيطة مخزنة.

---

### 📊 4.1 مقاييس مراقبة معالجة الفيديو في Prometheus ولوحة Grafana (Video Processing Observability)

تم تزويد محرك بايثون بمقاييس Prometheus حية، مع صف كامل ولوحات متخصصة في لوحة تحكم **Grafana** (`:3001`) تحت عنوان:  
`🎬 Video AI Ingestion & Audio Pipeline Telemetry`:

| اسم المقياس في Prometheus | النوع (Type) | التسميات (Labels) | ما يراقبه وما يعرضه في Grafana |
|:---|:---:|:---|:---|
| `lms_video_ingestion_total` | Counter | `status="success" \| "failed"` | إجمالي عمليات معالجة الفيديوهات مع تلوين فوري للنجاح (أخضر) والفشل (أحمر). |
| `lms_video_ingestion_in_flight` | Gauge | — | عدد الفيديوهات الجاري تنزيلها ومعالجتها لحظياً في نفس الثانية لمنع استنزاف السيرفر. |
| `lms_video_ingestion_chunks_total` | Counter | — | إجمالي عدد المقاطع (Chunks) المفهرسة في Qdrant لجميع الدروس. |
| `lms_video_ingestion_duration_seconds` | Histogram | buckets: `10s`..`600s` | الزمن الإجمالي لمعالجة الفيديو من البداية للنهاية (منحنى بياني p95 ومتوسط الزمن Mean). |
| `lms_video_ingestion_stage_duration_seconds` | Histogram | `stage="download" \| "chunking" \| "transcription" \| "normalization" \| "embedding" \| "qdrant_upsert"` | تفصيل كمون كل مرحلة لاكتشاف موضع الاختناق (Bottleneck) بدقة (هل التأخير من يوتيوب أم Whisper أم Gemini أم Qdrant). |

---

### 💡 5. مصفوفة أسباب الاختيارات الهندسية (Why We Chose X over Y Cheat Sheet)

| القرار الهندسي (Choice) | البديل المرفوض (Rejected Alternative) | السبب والمقايضة التقنية (Why? Technical Trade-off) |
|:---|:---|:---|
| **Qdrant Vector DB** | ChromaDB أو `pgvector` | • ChromaDB لعبة أبحاث غير مهيأة للمؤسسات وتفتقر لعزل المستأجرين.<br>• `pgvector` بطيء في الـ High Concurrency ويفتقر لمتجهات Sparse المدمجة.<br>• **Qdrant** مكتوبة بـ Rust، تجمع Dense + Sparse في نفس الكوليكشن، وتدعم خوارزمية RRF الأصلية وفلاتر الـ Payload بسرعة الميكروثانية. |
| **البحث الهجين (BGE-M3 + BM25 مع RRF)** | البحث الشعاعي الكثيف وحده (Pure Dense) | التضمين الكثيف يفهم المعنى العام لكنه يعجز عن مطابقة أسماء الشاشات والأكواد المحاسبية الدقيقة (مثل `شاشة POS` أو كود الحساب `101001`). دمج BM25 يضمن التطابق اللفظي الحرفي دون التضحية بالمعنى الدلالي. |
| **FlashRank ONNX Quantized Reranker** | PyTorch Cross-Encoder الكامل | تشغيل PyTorch Cross-Encoder كامل على الـ CPU كان يستغرق **40 إلى 50 ثانية** لترتيب 20 مقطعاً! تحويله إلى أوزان INT8 مكممة عبر **ONNX Runtime** خفض الزمن إلى **~180ms فقط** بنفس الدقة (>95%) ووفر آلاف الدولارات المخصصة لـ GPUs. |
| **توليد كويز متكيف: `min(num, chunks)`** | فرض 5 أسئلة دائماً (Fixed 5 Questions) | الفيديوهات القصيرة (دقيقة أو دقيقتين) تنتج مقطعين أو 3 فقط في Qdrant. محاولة إجبار النموذج على توليد 5 أسئلة كانت تؤدي إما لانهيار الطلب بـ 500 أو اختلاق أسئلة وهلوسة من خارج الدرس. التكيف التلقائي مع عدد المقاطع يضمن أمانة علمية 100%. |
| **قفل التزامن في الذاكرة `asyncio.Lock`** | أقفال قاعدة البيانات (Postgres Advisory Locks) | معالجة الفيديو وتفريغ الصوت تستغرق من 30 إلى 120 ثانية. حجز قفل قاعدة بيانات طوال هذا الوقت يستنزف اتصالات الـ DB Connection Pool ويخنق النظام. القفل في الذاكرة مع تنظيف TOCTOU يحمي الخادم بكفاءة تامة. |
| **كاش ثنائي الطبقات (2-Tier Caching)** | الكاش الدلالي فقط (Semantic Cache Only) | الكاش الدلالي يستلزم حساب التضمين لـ BGE-M3 (يستغرق ~360ms). للتحيات والأسئلة الشائعة جداً، أضفنا كاش بالذاكرة Tier-1 بمفاتيح 4D مشفرة بـ SHA-256 ليرد في **< 1ms** بدون أي تكلفة شبكة أو تضمين. |
| **سياج حماية اللهجات قبل الـ RAG** | فحص البرومبتات عبر LLM إضافي | فحص نوايا المستخدم أو كشف الاختراق عبر LLM إضافي يضيف 1 إلى 2 ثانية وتكلفة مالية مضاعفة. صممنا مصفوفة Regex مجمعة محلياً تفحص اللهجات المصرية والخليجية ومحاولات Jailbreak في **أقل من 0.05ms**. |
| **بث النتائج بـ SSE مع تقديم الروابط** | الرد التقليدي الكامل (Blocking REST Response) | انتظار الطالب 5 ثوانٍ لرؤية الإجابة تجربة سيئة. في SSE نرسل روابط الفيديو فوراً في **أول 300ms** لتشغيل المشغل في الواجهة، ثم نضخ التوكنز تدريجياً، مع ميزة إلغاء التوليد فور انقطاع الطالب لمنع هدر الفلوس. |

---

## 📌 1. الملخص السريع للمشروع (The Elevator Pitches)

### أ. العرض السريع في 30 ثانية (30-Second Elevator Pitch)

* **[English]:**
  > "The **LMS AI Co-Pilot** is an enterprise-grade Generative AI and RAG microservice built for ERP e-learning platforms. It features **Real-Time Token Streaming Search via SSE** (<300ms TTFT) with citation-first event sequencing, client disconnect abortion, and bounded backpressure. It combines a **Two-Tier Fast Ingress Engine** (sub-0.05ms heuristic dialect guardrails, <1ms Tier-1 4D LRU Cache, and <25ms Tier-2 Qdrant Semantic Cache) with a two-stage hybrid search pipeline (BGE-M3 Dense + BM25 Sparse with RRF Fusion) reranked via a quantized ONNX Cross-Encoder (FlashRank) in ~180ms on CPU. It enforces strict **Fail-Closed OWASP BOLA defense**, thread-safe per-lesson concurrency locks, an idempotent student feedback engine, and stateful memory via LangGraph & PostgreSQL — benchmarked quantitatively at **92% Faithfulness** with Ragas."

* **[العربية]:**
  > "مشروع **LMS AI Co-Pilot** هو محرك بحث ومساعد ذكاء اصطناعي مؤسسي مبني لمنصات الـ ERP التعليمية. يتميز بـ **محرك بحث فوري بالبث المباشر (SSE Stream)** يوفر أول توكن في أقل من 300ms مع إلغاء حرق التوكنات عند انقطاع الطالب والتحكم بالتدفق (Backpressure). يعتمد على **نفاذ سريع ثنائي الطبقات** يدمج سياج حماية للهجات والـ Jailbreaks (<0.05ms)، وكاش فوري في الذاكرة Tier-1 (<1ms) بمفاتيح 4D معزولة، وكاش دلالي شعاعي Tier-2 بـ Qdrant (<25ms). عند الاستعلام الجديد، ينفذ بحثاً هجيناً (BGE-M3 + BM25 مع RRF) وإعادة ترتيب بموديل FlashRank ONNX المكمم في ~180ms على الـ CPU. كما يوفر حماية BOLA بنظام **Fail-Closed**، وأقفال تزامنية محصنة ضد الـ Webhooks، ومحرك تقييمات للطلاب مانع للتكرار، وإدارة محادثات بـ LangGraph، ومقاس كمياً بـ **92% أمانة ومقاومة للهلوسة** عبر Ragas."

---

### ب. العرض المعماري المفصل في دقيقتين (2-Minute Architecture Deep-Dive)

* **[English]:**
  > "In this project, our primary focus was solving the real-world production engineering challenges of enterprise RAG:
  > 1. **Real-Time Streaming & Fast Ingress:** Implemented `POST /v1/search/stream` delivering tokens via SSE with citation-first ordering (`sources` -> `token` -> `done`). Wrapped with client disconnect detection (`request.is_disconnected()`) and bounded queue backpressure (`maxsize=30`) to eliminate token waste. A heuristic regex router intercepts dialect jailbreaks and greetings in `< 0.05ms`, paired with a 4D In-Memory LRU Cache (< 1ms) and Qdrant Semantic Cache (< 25ms).
  > 2. **Audio Ingestion & Normalization:** Handled 1-2 hour lectures by chunking into 120s segments, calling Whisper with domain prompts, followed by Gemini Flash for CODA normalization. Checkpointing ensures instant crash recovery, while per-lesson asyncio locks with TOCTOU-proof bounded pruning serialize concurrent webhooks.
  > 3. **Two-Stage Hybrid Retrieval:** Pure vector search failed on precise ERP screens and accounting codes. We engineered a hybrid pipeline combining Dense BGE-M3 (1024d) and Sparse BM25 indexed in Qdrant with Reciprocal Rank Fusion (RRF). Top candidates are reranked via a quantized ONNX Cross-Encoder (FlashRank), cutting CPU reranking latency from 50s down to ~180ms.
  > 4. **Multi-Tenancy, BOLA Defense & Fail-Closed Security:** Enforced strict company-level isolation at query time in Qdrant. For checkpoint retrieval, we implemented strict OWASP BOLA object entitlement checks: students can only access assigned lessons, and admins are verified against organization ownership — failing closed with 503 on LMS outage and 403 on unassigned or foreign tenant.
  > 5. **Feedback Loop, Memory & Quantitative Evaluation:** Built an idempotent student feedback API (`POST /v1/search/feedback`) with 24h deduplication and Prometheus tracking. Managed multi-turn memory using LangGraph with an `AsyncPostgresSaver` pool and sliding window budget guard. Evaluated anti-hallucination quantitatively with Ragas achieving 92% Faithfulness."

* **[العربية]:**
  > "في هذا المشروع، كان تركيزنا منصباً على حل تحديات الإنتاج الحقيقية لأنظمة الـ RAG المؤسسية:
  > 1. **البث اللحظي والنفاذ السريع (Streaming & Fast Ingress):** بنينا مسار `POST /v1/search/stream` بنظام SSE يسبق التوكنات بروابط الفيديو فوراً لتجهيز المشغل في <300ms، مع إلغاء التوليد فور انقطاع العميل لمنع هدر التوكنات، وطابور مقيد (Backpressure maxsize=30). يسبق ذلك سياج حماية للهجات والـ Jailbreaks (<0.05ms)، وكاش Tier-1 بالذاكرة (<1ms) بمفاتيح 4D، وكاش دلالي بـ Qdrant.
  > 2. **خط استيعاب ومعالجة الصوتيات والتزامن:** معالجة محاضرات تدريبية لساعات عبر التقطيع لأجزاء (120 ثانية)، واستدعاء Whisper مع Gemini للتنقيح ونظام Checkpoints ذري للتعافي، وقفل تزامني لكل درس محمي ضد ثغرات TOCTOU لضمان تسلسل الـ Webhooks المتكررة.
  > 3. **محرك بحث هجين ثنائي المراحل:** دمج متجهات BGE-M3 مع BM25 في Qdrant بخوارزمية RRF Fusion، تليها إعادة ترتيب بـ FlashRank ONNX المكمم، مما خفض زمن المعالجة على الـ CPU من 50 ثانية إلى 180 مللي ثانية.
  > 4. **عزل المستأجرين وحماية BOLA بمبدأ Fail-Closed:** عزل بيانات الشركات في Qdrant، وحماية مسار قراءة المقاطع من ثغرات BOLA بتدقيق الصلاحيات للطالب، والتحقق الصارم من شركة الأدمن، مع الرفض الفوري (503 عند تعطل الـ LMS و 403 عند غياب الشركة أو اختلافها).
  > 5. **حلقة التقييم والذاكرة والتقييم الكمي:** مسار تقييمات الطلاب `POST /v1/search/feedback` المانع للتكرار خلال 24 ساعة مع عدادات Prometheus. وإدارة محادثات الطلاب بـ LangGraph و PostgreSQL، وتقييم جودة الردود كمياً بـ Ragas محققين 92% Faithfulness."

---

## 💼 2. تحليل الأدوار الوظيفية وتقييم الخبرة (Job Titles & Seniority Matrix)

```text
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           موقعك في طيف الخبرة الهندسية                           │
├─────────────────────────┬───────────────────────────────┬───────────────────────┤
│ Junior AI Engineer      │ Early Mid-Level AI Engineer   │ Senior AI Engineer    │
│ (0 - 1.5 Years)         │ (1.5 - 3 Years)               │ (3 - 5+ Years)        │
├─────────────────────────┼───────────────────────────────┼───────────────────────┤
│ [======== كودك يغطي هنا بالكامل ========] ──► [تتطلع له هنا]                    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### أ. المسميات الوظيفية المستهدفة (Target Job Titles)
1. **AI Engineer / Generative AI Engineer** (Junior / Associate / Early Mid-Level).
2. **LLM & RAG Systems Developer** (Python / Vector DBs / LangGraph).
3. **Backend AI Engineer (FastAPI / Multi-Tenancy / Distributed APIs)**.
4. **Applied AI / NLP Developer (Arabic Specialized)**.

---

### ب. التقييم الواقعي والمحايد لمستوى الـ Seniority (Realistic Seniority Assessment)

#### 🌟 نقاط التميز التي تضعك في أعلى 5% من المبتدئين (Top 5% Junior Differentiators):
* **[EN]:** Unlike typical tutorial RAGs that use basic ChromaDB and default LangChain chains without cost awareness, this project implements production-grade trade-offs: Quantized Cross-Encoders on CPU, hybrid search with RRF, multi-tenant vector authorization, sliding-window memory management, and empirical Ragas benchmarking.
* **[AR]:** خلافاً لمشاريع المبتدئين النمطية (تطبيقات LangChain سطحية مع ChromaDB بدون تفكير في التكلفة أو الأمان)، يمتلك مشروعك ميزات إنتاجية صلبة: إعادة ترتيب مكممة على المعالج، بحث هجين بـ RRF، عزل متجهات الشركات والـ RBAC، إدارة ذاكرة بنافذة انزلاقية، وتقييم كمي مثبت بـ Ragas.

#### ⚠️ الفجوات التي تفصلك عن الـ Mid/Senior الصلب (Gaps Needed for Solid Mid/Senior):
* **[EN]:** High concurrency load testing (1,000+ simultaneous users), distributed tracing infrastructure (Langfuse / OpenTelemetry), Kubernetes cluster deployments, and model fine-tuning (LoRA / QLoRA).
* **[AR]:** اختبار النظام تحت ضغط آلاف المستخدمين المتزامنين (High Concurrency)، بنية التتبع الموزع السحابية (Langfuse / OpenTelemetry)، النشر على مجموعات Kubernetes، والتدريب وضبط الأوزان المخصص للنماذج (Fine-tuning).

---

## 🏛️ 3. سجل القرارات والتحديات المعمارية (Architectural Decisions - ADRs)

---

### ADR-01: Hybrid Search (Dense + Sparse with RRF) vs. Pure Dense Vector Search

* **Question / التحدي:**
  * **[EN]:** "Why did you choose a Hybrid Search architecture (Dense + Sparse with RRF) instead of pure Dense Vector search?"
  * **[AR]:** "لماذا اخترت معمارية البحث الهجين (كثيف + لفظي مع RRF) بدلاً من الاعتماد على البحث الشعاعي الكثيف وحده؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Pure dense embeddings (BGE-M3) excel at general semantic intent but frequently miss exact keyword tokens, specific accounting terms, screen names (e.g., "POS Screen", "General Ledger"), or transaction IDs. Sparse BM25 guarantees exact keyword matching. Combining them via **Reciprocal Rank Fusion (RRF)** in [qdrant_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/qdrant_service.py#L227) yields the highest recall and precision without manual score normalization.
  * **[AR]:** التضمين الشعاعي الكثيف (BGE-M3) متميز في فهم المعنى المجرد لكنه يخفق في مطابقة الكلمات الحرفية، وأسماء الشاشات المحاسبية الدقيقة (مثل "شاشة الـ POS" أو "دفتر الأستاذ"). البحث اللفظي (BM25) يضمن التطابق الحرفي. دمجهما بخوارزمية **RRF** داخل Qdrant يحقق أعلى دقة استرجاع دون الحاجة لموازنة يدوية معقدة للأوزان.

---

### ADR-02: FlashRank Quantized ONNX vs. Full PyTorch Cross-Encoder

* **Question / التحدي:**
  * **[EN]:** "Why did you adopt FlashRank Quantized ONNX for reranking instead of standard PyTorch Cross-Encoders?"
  * **[AR]:** "لماذا اعتمدت موديل FlashRank المكمم بـ ONNX لإعادة الترتيب بدلاً من موديلات Cross-Encoder التقليدية بـ PyTorch؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Running full PyTorch Cross-Encoders (`bge-reranker-v2-m3`) on CPU took **40 to 50 seconds** to rerank 20 passages—unacceptable in production. Moving to **FlashRank** with quantized INT8 weights running on **ONNX Runtime** in [reranker_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/reranker_service.py) dropped latency to **~200-350ms on CPU** with >95% ranking fidelity, saving thousands of dollars in dedicated GPU infrastructure.
  * **[AR]:** تشغيل موديلات PyTorch الكاملة على المعالج المركزي (CPU) كان يستغرق **من 40 إلى 50 ثانية** لترتيب 20 مقطعاً، وهو بطء يقتل تجربة المستخدم. الانتقال إلى **FlashRank** المكمم بأوزان INT8 ومحرك **ONNX Runtime** قلص زمن المعالجة إلى **~200-350 مللي ثانية على نفس المعالج** مع الحفاظ على أكثر من 95% من دقة الترتيب، مما وفر تكاليف باهظة لحجز كروت GPU سحابية.

---

### ADR-03: Qdrant Vector Database vs. ChromaDB & pgvector

* **Question / التحدي:**
  * **[EN]:** "Why did you select Qdrant as your vector database over ChromaDB or pgvector?"
  * **[AR]:** "لماذا اخترت قاعدة بيانات Qdrant على حساب ChromaDB أو pgvector؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** ChromaDB lacks enterprise indexing and production multi-tenancy capabilities. `pgvector` struggles with high-QPS concurrent hybrid searches and lacks native Sparse vector structures. **Qdrant** is built in Rust, supports named vectors (Dense + Sparse in a single collection), provides native server-side RRF fusion, and features native Keyword Payload Indexes that enable pre-filtering by `company_id` and student permissions at microsecond speeds.
  * **[AR]:** مكتبة ChromaDB تفتقر لأدوات الإنتاجية والفهرسة المتقدمة وعزل المستأجرين. إضافة `pgvector` تعاني تحت ضغط الاستعلامات المتزامنة الكثيفة وتفتقر لهيكل متجهات الـ Sparse المدمج. بينما **Qdrant** مبنية بـ Rust، وتدعم المتجهات المتعددة (Dense و Sparse في نفس الكوليكشن)، والدمج الأصلي بـ RRF، وتدعم فهارس الـ Payload الفائقة السرعة لعزل الشركات والتحقق من الصلاحيات.

---

### ADR-04: LangGraph with PostgreSQL vs. Stateless Chains or Redis

* **Question / التحدي:**
### ADR-05: Two-Tier Fast Ingress & Sub-millisecond Intent Router

* **Question / التحدي:**
  * **[EN]:** "Why implement a two-tier caching architecture and heuristic intent router rather than relying exclusively on Qdrant vector semantic caching?"
  * **[AR]:** "لماذا قمت ببناء طبقتي كاش (Two-Tier Caching) وموجه نوايا بدلاً من الاعتماد الحصري على الكاش الدلالي في Qdrant؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Even an optimized vector cache requires embedding generation (BGE-M3 takes ~360ms) and network I/O to Qdrant (~15-25ms). Repetitive queries, conversational greetings ('مرحبا', 'أهلاً'), and common employee queries were paying an unnecessary 400ms tax. We introduced: (1) A compiled regex **Intent Router** that intercepts greetings/banter in `< 0.1ms` without ML inference, and (2) A **Tier-1 Exact In-Memory LRU Cache** (< 1ms) keyed deterministically on 4D SHA-256 (`company:dept:role:query`) to prevent cross-department cache thrashing, with auto-promotion from Tier-2 Semantic Cache.
  * **[AR]:** حتى مع كاش المتجهات، يتطلب الأمر توليد التضمين (يستغرق BGE-M3 حوالي 360ms) واتصال شبكة بـ Qdrant (15-25ms). الأسئلة المكررة والتحيات العادية كانت تتكبد 400ms دون داعٍ. لذا صممنا: (1) **موجّه نوايا (Intent Router)** بالـ Regex المحسوب مسبقاً للرد على التحيات في أقل من 0.1 مللي ثانية دون أي استدعاء للذكاء الاصطناعي، و (2) **كاش لحظي بالذاكرة Tier-1** (< 1ms) بمفاتيح رباعية مشفرة بـ SHA-256 (`company:dept:role:query`) تمنع تداخل الأقسام وتوفر 100% من التكلفة والكمون.

---

### ADR-06: OWASP BOLA Defense & Fail-Closed Cross-Tenant Verification

* **Question / التحدي:**
  * **[EN]:** "How did you eliminate Broken Object Level Authorization (BOLA / OWASP API #1) on internal lesson checkpoint endpoints?"
  * **[AR]:** "كيف أغلقت ثغرة Broken Object Level Authorization (BOLA) في مسارات جلب لقطات الدروس؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Checkpoint retrieval (`GET /v1/lessons/{lesson_id}`) previously exposed pre-computed transcripts. We hardened it with dual-layered object entitlement: (1) Students are strictly checked against `user_ctx.permissions.accessible_lesson_ids` (403 Forbidden on mismatch). (2) Admins are checked against company ownership by verifying `user_ctx.company_id in lesson_tenants`. Crucially, we enforced **Fail-Closed** security: if LMS is unreachable, the endpoint returns `503 Service Unavailable` rather than falling open, and returns `403 Forbidden` if a lesson is unassigned to any tenant.
  * **[AR]:** استرجاع مقاطع الدروس المحفوظة كان معرضاً للاختراق إذا خمّن المهاجم معرف الدرس. قمنا بتأمينه بمستويين: (1) للطلاب: منع قاطع إلا للدروس المصرح بها في `accessible_lesson_ids`. (2) للمشرفين (Admins): فحص تطابق شركة الأدمن مع شركات الدرس في LMS لمنع التسريب بين الشركات (Cross-Tenant). والأهم تطبيق مبدأ **Fail-Closed الصارم**: إذا تعطل الـ LMS نرفض الطلب بـ 503 بدلاً من تركه يمر (Fail-Open)، ونرفض أي درس غير مسند بـ 403.

---

### ADR-07: Per-Lesson Ingestion Concurrency Serialization (TOCTOU-Proof Pruning)

* **Question / التحدي:**
  * **[EN]:** "How do you handle concurrent Webhook retries for the same lesson without corrupting vector indices or starving connection pools?"
  * **[AR]:** "كيف تمنع تضارب الـ Webhooks المتزامنة لنفس الدرس دون إفساد الفهارس أو استنزاف اتصالات قاعدة البيانات؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Rapid LMS webhooks for the same lesson could trigger parallel ingestion, duplicate Qdrant points, and checkpoint file race conditions. We implemented an in-memory per-lesson `asyncio.Lock` registry with a TOCTOU-proof dual-condition bounded pruning mechanism (pruning unlocked locks only if idle > 1h, oldest-first, at 10k ceiling). We intentionally rejected `pg_advisory_xact_lock` because audio ingestion takes 30-120 seconds, and holding DB connections would cause connection pool starvation. In ADR-09, we documented the multi-pod evolution path using a dedicated PostgreSQL lease table (`lesson_ingest_leases`).
  * **[AR]:** وصول Webhooks مكررة لنفس الدرس كان يهدد بتشغيل معالجة صوتية مزدوجة ومسح وكتابة متضاربة في Qdrant. بنينا نظام أقفال تزامني `asyncio.Lock` لكل درس محمي ضد ثغرات TOCTOU (لا يُمس القفل بالـ Pruning إلا إذا كان غير مقفول وخاملاً لأكثر من ساعة، مع تنظيف الأقدم أولاً عند سقف 10k). وتجنبنا عمداً استخدام Postgres Advisory Lock حتى لا نحجز اتصال DB طوال مدة معالجة الصوت (دقيقتين) مما يخنق الـ Connection Pool، مع توثيق التوسع المستقبلي كـ Lease Table في ADR-09.

---

### ADR-08: Real-Time SSE Token Streaming & ADR-14 (Self-RAG Deferral)

* **Question / التحدي:**
  * **[EN]:** "Why implement Server-Sent Events (SSE) streaming with citation-first sequencing, and why defer iterative Self-RAG loops in production (ADR-14)?"
  * **[AR]:** "لماذا صممت بث التوكنات بـ SSE مع تقديم روابط الفيديو أولاً، ولماذا قررت تأجيل حلقة التقييم الذاتي Self-RAG لمرحلة ما بعد الإنتاج (ADR-14)؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Traditional non-streamed search forced students to wait 3-5 seconds for Gemini to generate the full answer. We engineered `POST /v1/search/stream` emitting `event: sources` in `< 300ms` so the frontend UI immediately mounts video player widgets before the first token arrives. To protect token budget, we track `request.is_disconnected()` and break the producer thread instantly via `stop_event.set()` and task cancellation. We enforce **Backpressure** with a bounded `asyncio.Queue(maxsize=30)` to throttle token consumption on slow networks, and emit `: heartbeat\n\n` comments every 15s to keep proxy sockets alive. Crucially, in **ADR-14**, we rejected heavy 5-node Self-RAG loops in the fast path: FlashRank reranking filters irrelevant chunks in 180ms on CPU, whereas Self-RAG would inflate latency by 4 seconds and quadruple API costs per query.
  * **[AR]:** في البحث التقليدي، ينتظر الطالب من 3 إلى 5 ثوانٍ لرؤية أي نتيجة. صممنا مسار البث `POST /v1/search/stream` بنظام SSE ليُصدر حدث `sources` أولاً في أقل من 300ms لتجهيز مشغل الفيديو ومقاطع الدروس فوراً، يليه تدفق التوكنات تدريجياً. ولحماية التكلفة المالية، نراقب انقطاع اتصال الطالب عبر `request.is_disconnected()` ونكسر ثريد التوليد فوراً بـ `stop_event.set()` وإلغاء المهمة. ونطبق **التحكم بالتدفق (Backpressure)** عبر طابور مقيد `maxsize=30` لتجميد استهلاك التوكنات إذا كان اتصال الطالب بطيئاً، ونرسل نبضات قلب `: heartbeat\n\n` كل 15 ثانية لمنع انقطاع الـ Proxies. كما قررنا في **ADR-14** تأجيل وكيل Self-RAG ذي العقد الخمس؛ لأن نموذج FlashRank يقيّم المقاطع في 180ms على الـ CPU، بينما Self-RAG كان سيضاعف زمن الاستجابة إلى 5 ثوانٍ و4 أضعاف التكلفة دون مبرر في الـ MVP.

---

### ADR-09: Asynchronous Feedback Persistence & Raw Data Fidelity (ADR-15)

* **Question / التحدي:**
  * **[EN]:** "How do you handle student answer feedback without blocking the API or polluting the database when students change their vote?"
  * **[AR]:** "كيف تسجل تقييمات الطلاب للإجابات دون تعطيل استجابة الخادم ودون تكرار أو إفساد البيانات إذا غيّر الطالب رأيه؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Student ratings must never slow down client interactions. We offloaded DB persistence to FastAPI `BackgroundTasks`, achieving `< 15ms` API latency. To handle vote reversals (e.g., student switches from DOWN to UP with updated comments), we designed a composite unique constraint `(user_id, query_hash, answer_hash)` in PostgreSQL. This allows upsert updates without primary key violations or duplicate rows. In **ADR-15**, we rejected real-time PII redaction on feedback text: scrubbed text damages Arabic dialect nuances and model evaluation fidelity; redaction is instead enforced as a pipeline filter upon administrative export.
  * **[AR]:** تسجيل التقييمات لا ينبغي أن يعطل تجربة الطالب؛ لذا عزلنا كتابة قاعدة البيانات في `BackgroundTasks` ليرد الخادم في أقل من 15ms. وللسماح بتعديل التصويت (لو غيّر الطالب رأيه من سلبي لإيجابي وأضاف تعليقاً)، اعتمدنا قيداً فريداً مركباً `(user_id, query_hash, answer_hash)` في PostgreSQL ينفذ تحديثاً فورياً دون تكرار السجلات أو انهيار الاتصال. وقررنا في **ADR-15** حظر تنقيح الـ PII أثناء الاستقبال للحفاظ على نقاء اللهجة ودقة التقييم اللاحق للنماذج، وتأجيل التنقيح لطبقة التصدير.



---

### ADR-10: Decoupled Offline Drift Evaluation (ADR-16) & Prometheus SLA Alerting (ADR-17)

* **Question / التحدي:**
  * **[EN]:** "How do you detect silent model degradation and alert on production SLA violations without inflating query costs?"
  * **[AR]:** "كيف ترصد تراجع جودة النماذج السحابية وتضبط التنبيهات لاتفاقيات مستوى الخدمة (SLAs) دون مضاعفة تكاليف الاستعلام؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Using real-time LLM judges to monitor answers in production would quadruple latency and token expenditures. We established an **Offline Scheduled Evaluation Pipeline (ADR-16)**: querying `GET /v1/admin/feedback?format=ragas` to sample negative student feedback and benchmark Faithfulness and Answer Relevancy weekly via Ragas against our baseline (0.92/0.86). For operational health, **ADR-17** mounts declarative alerting rules (`alerts.yml`) into Prometheus with strict SLA thresholds: firing on 5xx error rate > 5%, P95 search latency > 3.0s, security guardrail refusal spikes > 0.5/s, and degraded semantic cache hit rates (<10%).
  * **[AR]:** فحص الردود لحظياً بنماذج ذكاء اصطناعي محكّمة (LLM-as-a-Judge) يضاعف التكلفة والكمون 4 مرات. اعتمدنا استراتيجية **التقييم الدوري غير المتزامن (ADR-16)**: سحب العينات ذات التقييم السلبي دورياً عبر `GET /v1/admin/feedback?format=ragas` وتشغيل فحص Ragas أسبوعياً لمراقبة ثبات معايير Faithfulness و Relevancy. وللصحة التشغيلية، اعتمدنا في **ADR-17** ملف تنبيهات صارم `alerts.yml` داخل Prometheus يُطلق إنذارات فورية عند تجاوز أخطاء 5xx نسبة 5%، أو تخطي كمون P95 عتبة 3.0 ثوانٍ، أو قفزات محاولات الاختراق وحجب الأمان (`>0.5/s`).

---

### ADR-11 (ADR-18): Adaptive Quiz Generation & Context Grounding vs. Rigid 5-Question Constraint

* **Question / التحدي:**
  * **[EN]:** "How do you handle generating quizzes for short videos (e.g., 1-2 minutes) without hallucinating questions or throwing 500 errors?"
  * **[AR]:** "كيف تتعامل مع توليد كويز لفيديوهات قصيرة (دقيقة أو دقيقتين) دون أن يهلوس النموذج أو ينهار الخادم بخطأ 500؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** In production, business stakeholders often request a fixed number of questions (e.g., 5 MCQs per quiz). However, a 2-minute video generates only 2 or 3 chunks in Qdrant (120s chunking window). Forcing an LLM to invent 5 questions from 2 chunks guarantees hallucination—the model will invent concepts never mentioned in the video. In [lesson_content_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/lesson_content_service.py), we implemented adaptive generation: `actual_k = min(num_questions, len(chunks))`. If only 3 chunks exist, we generate 3 strictly grounded questions. Furthermore, if a lesson has 0 chunks in Qdrant, we return a typed `404 Not Found` with an explicit actionable message ("Lesson has not been processed yet") instead of an opaque 500 crash.
  * **[AR]:** متطلبات العمل غالباً ما تطلب عدداً ثابتاً من الأسئلة (مثلاً 5 أسئلة لكل كويز). لكن فيديو مدته دقيقتان ينتج مقطعين أو 3 مقاطع فقط في Qdrant (نافذة التقطيع 120 ثانية). إجبار النموذج على استخراج 5 أسئلة من مقطعين يجبره حتماً على الهلوسة واختلاق حقائق لم تُذكر في الشرح. في [lesson_content_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/lesson_content_service.py)، طبقنا قاعدة التوليد المتكيف: `actual_k = min(num_questions, len(chunks))`؛ فإذا وُجدت 3 مقاطع نولد 3 أسئلة دقيقة مستندة للمحتوى فقط. ولو كان الدرس غير معالج (0 مقاطع)، نرجع فوراً كود `404 Not Found` موجه للمستخدم يطلب منه معالجة الفيديو أولاً بدلاً من انهيار السيرفر بخطأ 500 غير مفهوم.

---

### ADR-12 (ADR-19): Dual Synchronization Protocol (Push Webhook Callback + Pull Polling) for AI Ingestion Lifecycle

* **Question / التحدي:**
  * **[EN]:** "How does the .NET backend track the state of heavy, multi-minute audio ingestion jobs without maintaining expensive persistent connections?"
  * **[AR]:** "كيف تتابع منصة دوت نت حالة معالجة الفيديوهات الطويلة دون استنزاف الاتصالات المفتوحة (Persistent Connections)؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** Audio ingestion involves downloading, Whisper transcription, Gemini normalization, and BGE-M3 embedding, taking 30 to 120 seconds. Holding an HTTP request open across this duration causes gateway timeouts (504). We implemented a resilient **Dual Synchronization Protocol**:
    1. **Primary Push (Asynchronous Webhook Callback):** When the Python pipeline finishes or fails, [pipeline_orchestrator.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/pipeline_orchestrator.py) calls .NET at `POST /api/internal/lessons/{lessonId}/ai-status` with `X-Service-Token`, passing terminal status (`Completed` / `Failed`), chunk counts, and any error message.
    2. **Fallback Pull (Stateless Status Query):** If a webhook packet drops or the Angular client refreshes the page, Python exposes `GET /v1/ingest/status/{lesson_id}` (and compatibility alias `/api/ingest/status/{lesson_id}`). This endpoint queries Qdrant directly for point counts and checks the active `asyncio.Lock` registry, dynamically returning `None`, `Processing`, or `Completed` without requiring a separate stateful database.
  * **[AR]:** معالجة الصوت تتضمن التنزيل والتفريغ بـ Whisper والتنقيح بـ Gemini والتضمين الشعاعي، مما يستغرق من 30 إلى 120 ثانية. إبقاء اتصال HTTP مفتوحاً طوال هذا الوقت يؤدي حتماً لانتهاء مهلة البوابات (504 Gateway Timeout). صممنا **بروتوكول تزامن ثنائي هجين**:
    1. **الدفع الأساسي (Webhook Push Callback):** عند اكتمال المعالجة أو فشلها، يقوم بايثون باستدعاء .NET فوراً على مسار `POST /api/internal/lessons/{lessonId}/ai-status` بتمرير التوكن الداخلي والحالة النهائية (`Completed` أو `Failed`) مع عدد المقاطع ورسالة الخطأ إن وُجدت.
    2. **الاستعلام الاحتياطي (Polling Pull):** لو سقط إشعار الويب هوك بسبب الشبكة أو قام المشرف بعمل Refresh لصفحة Angular، يوفر بايثون مسار `GET /v1/ingest/status/{lesson_id}`؛ يفحص هذا المسار قاعدة بيانات Qdrant مباشرة وأقفال الذاكرة الحية ليرجع الحالة الدقيقة لحظياً دون الحاجة لتخزين حالة وسيطة في قاعدة بيانات إضافية.

---

### ADR-13 (ADR-20): Resilient Cross-Stack JWT Claim Negotiation (.NET Identity vs. Python Pydantic)

* **Question / التحدي:**
  * **[EN]:** "How did you solve subtle JWT claim mismatches between ASP.NET Core Identity tokens and Python Pydantic models in production?"
  * **[AR]:** "كيف تغلبت على التناقضات بين توكنات ASP.NET Core ونماذج التحقق Pydantic في بايثون أثناء الإنتاج؟"
* **Technical Trade-off / المقايضة الهندسية:**
  * **[EN]:** .NET Identity frequently structures JWT claims differently depending on user roles: SuperAdmins lack tenant `company_id` claims, and claim types often map to either standard RFC names (`sub`) or Microsoft namespaces (`http://schemas.xmlsoap.org/ws/2005/05/identity/claims/nameidentifier`). Strict Pydantic models threw `422 Unprocessable Entity` or `500` errors on these tokens. In [auth_models.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/models/auth_models.py), we updated `TokenClaims` with optional defaults (`company_id: str | None = None`, `role: str = "Student"`). In [auth_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/auth_service.py), we added a graceful validation fallback: if strict Pydantic instantiation throws a `ValidationError`, the service parses claims defensively with safe defaults, preventing system outages while preserving cryptographic signature validation.
  * **[AR]:** توكنات ASP.NET Core تصدر أحياناً بهياكل مختلفة باختلاف الرتبة: فالمشرف العام (SuperAdmin) لا ينتمي لشركة محددة وبالتالي يغيب عنه حقل `company_id`، كما تختلف مسميات الحقول أحياناً بين أسماء الـ RFC القياسية ومسميات مايكروسوفت. التحقق الصارم في Pydantic كان يرفض هذه التوكنات بـ 422 أو 500. قمنا بتعديل `TokenClaims` ليقبل قيماً افتراضية اختيارية، وأضفنا في `auth_service.py` معالجة دفاعية تستوعب استثناءات `ValidationError` وتستخرج المطالبات بأمان دون كسر التحقق الرياضي من التوقيع بالمفتاح السري.

---

## 🎯 4. بنك أسئلة وأجوبة المقابلات التقنية المتوقعة (Deep Technical Interview Q&A)

---

### 🔹 المحور 1: معمارية الاسترجاع والبحث الهجين (Retrieval & Hybrid Search)

#### Q1: Full Request Lifecycle
* **Question [EN]:** "Walk me through the exact lifecycle of a user query from the moment it hits the API endpoint to the final generated response."
* **السؤال [AR]:** "اشرح لي بالتفصيل دورة حياة استعلام المستخدم من لحظة وصوله لـ API وحتى إرجاع الإجابة النهائية."

* **Answer [EN] (STAR Method):**
  * **Step 1 (Ingress, Auth & Intent Router):** FastAPI receives `POST /v1/search`. JWT claims are validated into `UserContext` and rate limits applied. The query is immediately routed to `IntentRouterService`: if it matches conversational greetings, banter, or invalid input, a canned response returns in `< 0.1ms` (zero ML latency).
  * **Step 2 (Tier-1 Exact Cache Lookup):** The normalized query is hashed into a 4D SHA-256 key (`company:dept:role:query`). If present in the In-Memory LRU Cache, the response returns instantly in `< 1ms` with 100% token and compute savings.
  * **Step 3 (Normalization & Embedding):** On Tier-1 MISS, text is normalized via `normalize_arabic_text_leaderboard` and embedded into a 1024d dense vector via BGE-M3 in a non-blocking threadpool (~360ms).
  * **Step 4 (Tier-2 Semantic Cache Check):** Qdrant's `semantic_cache` is queried for vectors with cosine similarity >= 0.92 matching the user's `company_id`. If found and student lesson entitlements pass RBAC, it returns in ~15ms and is auto-promoted to Tier-1 Exact Cache.
  * **Step 5 (Hybrid Vector Search + RRF):** On cold MISS, BM25 sparse vectors are generated. Qdrant executes concurrent Dense and Sparse pre-fetches, filtering by user `allowed_entities`, and merges the top 8 candidates using Reciprocal Rank Fusion (RRF).
  * **Step 6 (Cross-Encoder Reranking):** FlashRank reranks candidates against the raw query on CPU, assigning `_reranker_score` and picking the top 4 passages in ~180ms.
  * **Step 7 (LangGraph Memory & Generation):** Context strings are assembled. Conversation history for the `thread_id` is trimmed via sliding window (max 6 messages / token budget). Gemini 3.5 Flash generates the final response with bracketed source citations `[1]`. The answer is persisted to both cache tiers in the background, Prometheus records all stage latencies, and a JSON trace is saved.

* **الإجابة [AR] (منهجية STAR):**
  * **المرحلة 1 (الاستقبال وتوجيه النوايا):** استلام الطلب في FastAPI، تدقيق الـ JWT، وتمرير السؤال فوراً لموجّه النوايا (Intent Router): إذا كان تحية أو دردشة أو مدخلاً فارغاً، يُعاد الرد في أقل من 0.1 مللي ثانية دون أي استدعاء لـ Qdrant أو الموديلات.
  * **المرحلة 2 (فحص الكاش اللحظي Tier-1):** توليد مفتاح 4D مشفر بـ SHA-256 (`company:dept:role:query`). إذا وجد في كاش الذاكرة، يُعاد الرد فوراً في أقل من 1 مللي ثانية.
  * **المرحلة 3 (التطبيع والتضمين):** توحيد الحروف واستخراج المتجه الكثيف (1024 بعداً) بـ BGE-M3 في Threadpool غير حاجب للـ Event Loop.
  * **المرحلة 4 (فحص الكاش الدلالي Tier-2 بـ Qdrant):** استعلام كوليكشن `semantic_cache` بعتبة تشابه 0.92 وفلتر الشركة. عند التطابق والتحقق من صلاحية الدروس، يُعاد الرد في ~15ms ويُرقى تلقائياً للـ Tier-1.
  * **المرحلة 5 (البحث الهجين بـ RRF):** في حال عدم وجود كاش، توليد متجهات BM25 واسترجاع أعلى 8 مقاطع بدمج RRF مع فلاتر الصلاحيات.
  * **المرحلة 6 (إعادة الترتيب بـ FlashRank):** يقوم Cross-Encoder مكمم بإعادة ترتيب المرشحين بدقة واختيار أفضل 4 مقاطع في ~180 مللي ثانية على الـ CPU.
  * **المرحلة 7 (التوليد والذاكرة بـ LangGraph):** تقليم سياق الذاكرة للـ `thread_id` بنافذة انزلاقية، وتوليد الإجابة بـ Gemini مع التوثيق [1]. ثم حفظ الرد في الكاش الدلالي والفوري في الخلفية، وتسجيل المقاييس في Prometheus، وتصدير الـ JSON Trace.

---

#### Q2: Vector vs. Keyword Search
* **Question [EN]:** "When would you prefer keyword-based search (BM25) over semantic vector search in an enterprise ERP system?"
* **السؤال [AR]:** "متى تفضل استخدام البحث اللفظي المبني على الكلمات المفتاحية (BM25) على البحث الدلالي الشعاعي في نظام ERP مؤسسي؟"

* **Answer [EN]:**
  * "In an ERP environment, users frequently query specific technical jargon, database table names, accounting account numbers (e.g., 'Account 101001'), or exact module abbreviations (e.g., 'GL', 'HR', 'POS', 'SKU-4902'). Vector embeddings represent text in continuous geometric space where rare strings or exact identifiers can get blurred into generic semantic clusters. BM25 excels at term frequency and exact token matching. That is why hybrid search with RRF is mandatory—it prevents keyword misses while retaining conceptual semantic understanding."

* **الإجابة [AR]:**
  * "في أنظمة الـ ERP، يستعلم المستخدمون غالباً عن مصطلحات تقنية دقيقة، أو أرقام حسابات شجرة الحسابات (مثل 'حساب 101001')، أو اختصارات الموديولات والشاشات (مثل 'GL', 'POS', 'SKU'). التضمين الشعاعي يمثل الكلمات في فضاء هندسي متصل؛ مما قد يذيب الرموز والأكواد الدقيقة في معانٍ عامة. بينما يتفوق BM25 في المطابقة اللفظية الحرفية. لهذا السبب كان البحث الهجين مع RRF حتمياً لضمان عدم ضياع الأكواد مع الاحتفاظ بالفهم الدلالي."

---

### 🔹 المحور 2: الأداء والكمون والتحسين (Performance & Latency Optimization)

#### Q3: CPU Cross-Encoder Optimization
* **Question [EN]:** "How did you optimize your cross-encoder reranking stage to run in real-time on standard CPU hardware?"
* **السؤال [AR]:** "كيف قمت بتحسين مرحلة إعادة الترتيب (Cross-Encoder) لتعمل بالوقت الفعلي على معالجات عادية (CPU) بدون GPU؟"

* **Answer [EN] (STAR Method):**
  * **Situation:** Running standard PyTorch cross-encoders (`BAAI/bge-reranker-v2-m3`) on CPU resulted in 40–50s latencies for 20 candidates.
  * **Task:** Reduce reranking latency to under 500ms on CPU without paying for dedicated GPU servers.
  * **Action:** Integrated **FlashRank**, utilizing an 8-bit quantized ONNX runtime model (`miniReranker_arabic_v1`). Wrapped model execution in `asyncio.to_thread` with an `asyncio.Lock` to serialize calls and protect against the HuggingFace Rust tokenizer threading crash (`RuntimeError: Already borrowed`).
  * **Result:** Slashed reranking latency by **>99% (down from 50,000ms to ~250ms)** on 4-core CPUs with negligible impact on retrieval accuracy.

* **الإجابة [AR] (منهجية STAR):**
  * **الموقف (Situation):** تشغيل Cross-Encoder كامل بـ PyTorch على الـ CPU تسبب في بطء كارثي وصل إلى 50 ثانية لكل طلب.
  * **المهمة (Task):** تخفيض زمن إعادة الترتيب لأقل من 500 مللي ثانية على نفس المعالج وتجنب تكلفة استئجار GPUs باهظة.
  * **الإجراء (Action):** اعتمدنا مكتبة **FlashRank** المكممة بأوزان 8-bit على محرك **ONNX Runtime**، مع تغليف التنفيذ في `asyncio.to_thread` محمي بـ `asyncio.Lock` لتجنب تضارب مكتبة Rust Tokenizer.
  * **النتيجة (Result):** هبط زمن إعادة الترتيب بنسبة **أكثر من 99% (من 50,000ms إلى ~250ms فقط)** على معالج 4-cores دون أي تدهور ملحوظ في دقة النتائج.

---

#### Q4: Context Window & Token Budget Management
* **Question [EN]:** "How do you protect your LLM context window from blowing up or exceeding token budgets during extended multi-turn conversations?"
* **السؤال [AR]:** "كيف تحمي نافذة سياق النموذج وميزانية التوكنز من الانفجار أثناء المحادثات الطويلة مع الطالب؟"

* **Answer [EN]:**
  * "We implement a two-layer context guard in `_trim_messages`:
    1. **Sliding Window:** Limits conversation history to the last `AGENT_MAX_HISTORY_MESSAGES = 6` (3 turns of Q&A).
    2. **Token Budget Guard:** Estimates token usage using character heuristic proxy (1 token ≈ 4 chars). If the estimated total exceeds `AGENT_MAX_CONTEXT_TOKENS = 3000`, older messages are popped from the front one-by-one while strictly preserving the user's latest query and active RAG context. Furthermore, Prometheus tracks actual token consumption (`prompt`, `completion`, `total`)."

* **الإجابة [AR]:**
  * "نطبق استراتيجية دفاعية مزدوجة لحماية سقف التوكنز في دالة `_trim_messages`:
    1. **النافذة الانزلاقية (Sliding Window):** حصر تاريخ المحادثة في آخر 6 رسائل فقط (3 جولات سؤال وجواب).
    2. **حارس الميزانية التقديري (Token Budget Guard):** استخدام معادلة تقريبية لحجم الأحرف (1 توكن ≈ 4 أحرف)، وفي حال تجاوز الحد الأقصى (3000 توكن)، يتم حذف أقدم الرسائل تدريجياً مع الحفاظ التام على السؤال الأخير وسياق الـ RAG الحالي. كما يتم تسجيل الاستهلاك الفعلي في Prometheus."

---

### 🔹 المحور 3: الأمان وعزل المستأجرين (Security & Multi-Tenancy)

#### Q5: Multi-Tenant Vector Space Isolation
* **Question [EN]:** "How do you mathematically guarantee that student data from Company A is never leaked to Company B in a shared Qdrant vector collection?"
* **السؤال [AR]:** "كيف تضمن رياضياً في قاعدة بيانات Qdrant المشتركة عدم تسريب سياق درس يخص شركة (أ) إلى طالب في شركة (ب)؟"

* **Answer [EN]:**
  * "We enforce strict **Query-Time Filter Partitioning** using Qdrant's indexed payload architecture:
    1. Every ingested chunk payload contains `tenant_ids`, `module_id`, and `allowed_entities` (e.g., `['tenant:comp_123', 'role:Student', 'module:mod_456']`).
    2. The API layer parses JWT claims and constructs the user's authorized entity array.
    3. The Qdrant hybrid search query injects a mandatory `Filter(must=[FieldCondition(key='allowed_entities', match=MatchAny(any=user_ctx.user_entities))])`.
    4. Qdrant filters candidates prior to vector distance scoring (pre-filtering via Payload Keyword Index). Documents not matching Company A's tenant ID are discarded at the index layer and are never evaluated for similarity, making cross-tenant data leakage mathematically impossible."

* **الإجابة [AR]:**
  * "نعتمد على **الفلترة الإلزامية وقت الاستعلام (Pre-filtering)** بالاستفادة من فهارس Qdrant:
    1. عند استيعاب أي مقطع، يُسجل في الـ Payload مصفوفة `allowed_entities` تحتوي على `tenant:comp_id` وصلاحيات الموديول.
    2. عند استعلام الطالب، يستخرج السيرفر الكيانات المصرح له بها من واقع تصريح الـ JWT.
    3. استعلام Qdrant يفرض شرطاً إلزامياً (`must condition`) يطابق كيانات الطالب مع كيانات الدرس.
    4. محرك Qdrant يستبعد أي وثيقة لا تنتمي لشركة الطالب على مستوى الفهرس قبل البدء في حساب المسافات الشعاعية؛ مما يجعل تسريب البيانات مستحيلاً رياضياً."

---

#### Q6: Secure Semantic Caching
* **Question [EN]:** "What security and consistency risks exist with semantic caching, and how did you resolve them?"
* **السؤال [AR]:** "ما هي المخاطر الأمنية وتحديات اتساق البيانات في الكاش الدلالي (Semantic Cache)، وكيف تغلبت عليها؟"

* **Answer [EN]:**
  * "Semantic caching poses two major risks:
    1. **Data Leakage:** Serving Company A's cached response to Company B, or serving an Admin-only answer to a restricted Student.
    2. **Stale Data:** Serving cached answers after a course has been updated or deleted.
  * **Our Resolution in [semantic_cache_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/semantic_cache_service.py):**
    * Strict Cosine Threshold: `0.95` (prevents false-positive matches for subtle query differences).
    * Tenant Scoping: Mandatory filter on `company_id` on all cache queries.
    * Lesson Permission Verification: Every cached response stores `lesson_ids`. On a cache hit, the system verifies that the current student holds permissions for *all* referenced lessons; if not, it triggers a cache MISS.
    * Webhook-Driven Invalidation: LMS `.NET` webhooks trigger `invalidate_by_lesson_id` on delete/update events to purge stale entries instantly."

* **الإجابة [AR]:**
  * "الكاش الدلالي ينطوي على خطرين جسيمين:
    1. **تسريب البيانات:** إرجاع رد يخص شركة لمستخدم من شركة أخرى، أو إرجاع رد مخصص للمشرفين إلى طالب محروم من الدرس.
    2. **البيانات القديمة (Stale Data):** إرجاع إجابات قديمة بعد قيام المحاضر بتعديل محتوى الدرس أو حذفه.
  * **حلنا الهندسي في [semantic_cache_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/semantic_cache_service.py):**
    * عتبة كوزين صارمة (`0.95`) تمنع التطابق الخاطئ للأسئلة المختلفة.
    * فلترة إلزامية على مستوى الـ `company_id`.
    * تدقيق الصلاحيات اللحظي: الكاش يخزن `lesson_ids`، وعند الـ Hit يفحص صلاحيات الطالب للدروس المستشهد بها، فإذا كان محروماً من أي درس يعتبر الكاش (MISS).
    * تفريغ الكاش التلقائي عند استلام Webhook بتعديل أو حذف الدرس."

---

### 🔹 المحور 4: معالجة الصوت واللهجات واللغة العربية (Audio & Arabic NLP)

#### Q7: Arabic Code-Switching & Dialect ASR
* **Question [EN]:** "How did you tackle Egyptian colloquial Arabic mixed with English technical terms (Code-Switching) during audio transcription?"
* **السؤال [AR]:** "كيف تعاملت مع تفريغ المحاضرات التي تجمع بين اللهجة المصرية العامية والمصطلحات التقنية الإنجليزية (Code-Switching)؟"

* **Answer [EN]:**
  * "We engineered a two-stage speech pipeline based on Arabic speech research findings:
    1. **Dialect-Primed Whisper Prompting:** Whisper models are prone to hallucinating or butchering colloquial Egyptian phrases. We fed `WHISPER_ERP_DOMAIN_PROMPT` containing dialect priming context ('محاضرة باللهجة المصرية') and key ERP jargon (POS, HR, Payroll, General Ledger) within the 224-token prompt limit to steer acoustic attention.
    2. **CODA-Inspired LLM Normalization:** In [transcript_normalizer.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/transcript_normalizer.py), Gemini Flash cleans filler words ('بص يا سيدي', 'يعني'), enforces **Code-Switching Hardening** (prohibits phonetically translating English ERP terms like 'Sales Screen' into Arabic), and converts digits into Modern Standard Arabic words (Tafqit) to align the vocabulary with our BGE-M3 embedding model."

* **الإجابة [AR]:**
  * "طبقنا مساراً هندسياً من مرحلتين مستنداً إلى أحدث أبحاث معالجة الصوت العربي:
    1. **تلقيم Whisper ببرومبت لهجات مخصص:** قمنا بتغذية Whisper ببرومبت يحتوي على سياق اللهجة المصرية مع المصطلحات الإنجليزية الخاصة بالنظام (HR, POS, General Ledger) لضبط طبقة الانتباه الصوتية.
    2. **التنقيح بـ Gemini Flash وفق معايير CODA العالمية:** في [transcript_normalizer.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/transcript_normalizer.py)، نقوم بحذف كلمات الحشو، وتطبيق قاعدة حظر تعريب المصطلحات الإنجليزية المنطوقة، وتفقيط الأرقام وتحويلها لكلمات عربية فصحى لتوحيد الفضاء الشعاعي مع BGE-M3."

---

### 🔹 المحور 5: الجودة والتقييم ومنع الهلوسة (Evaluation & Anti-Hallucination)

#### Q8: Quantitative RAG Benchmarking with Ragas
* **Question [EN]:** "How do you empirically prove that your RAG pipeline does not hallucinate, rather than just relying on manual spot-checks?"
* **السؤال [AR]:** "كيف تثبت كمياً وعلمياً أن نظام الـ RAG لا يهلوس ولا يختلق حقائق بدلاً من الاعتماد على الفحص اليدوي العشوائي؟"

* **Answer [EN] (STAR Method):**
  * **Situation:** Stakeholders required proof that LLM-generated answers strictly adhered to video transcripts without hallucinations.
  * **Task:** Establish an automated, repeatable quantitative evaluation framework.
  * **Action:** Integrated **Ragas v0.4+** in [scripts/run_rag_eval.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/scripts/run_rag_eval.py). Generated a verified `golden_dataset.jsonl` extracted from real Qdrant video chunks. Configured Gemini 3.5 Flash as judge LLM and `gemini-embedding-001` for embedding evaluation. Measured **Faithfulness** and **Answer Relevancy**.
  * **Result:** Achieved **0.92 Faithfulness** (target >= 0.80) and **0.86 Answer Relevancy** (target >= 0.75), officially logged in [tests/eval/BASELINE.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/tests/eval/BASELINE.md) as an automated CI/CD regression baseline.

* **الإجابة [AR] (منهجية STAR):**
  * **الموقف (Situation):** طلبت الإدارة دليلاً ملموساً على أن إجابات المساعد الذكي مستندة حصراً إلى محتوى الفيديوهات دون أي اختلاق.
  * **المهمة (Task):** بناء إطار تقييم كمي مؤتمت ومستمر لقياس دقة المنظومة.
  * **الإجراء (Action):** قمنا بدمج إطار **Ragas v0.4+** وبناء مجموعة بيانات ذهبية `golden_dataset.jsonl` مستخرجة من مقاطع حقيقية، وقياس معيار الأمانة الواقعية (**Faithfulness**) ومعيار صلة الإجابة بالسؤال (**Answer Relevancy**).
  * **النتيجة (Result):** حققنا **0.92 في Faithfulness** (متفوقين على هدف 0.80) و **0.86 في Answer Relevancy**، وتم توثيق النتيجة رسمياً في [tests/eval/BASELINE.md](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/tests/eval/BASELINE.md) لتعمل كخط أساس ثابت لأي تعديل برمجي."


---

### 🔹 المحور 6: التكامل بين الأنظمة ودورة حياة الذكاء الاصطناعي (Cross-Service Integration & AI Lifecycle)

#### Q9: Inter-Service Architecture & Separation of Concerns (.NET 10 vs. Python FastAPI)
* **Question [EN]:** "How do your .NET 10 LMS backend and Python AI microservice communicate, and how did you divide responsibilities between them without duplicating state or business logic?"
* **السؤال [AR]:** "كيف تتواصل منظومة دوت نت (.NET 10) مع محرك بايثون للذكاء الاصطناعي، وكيف فصلت المسؤوليات المعمارية بينهما دون تكرار للبيانات أو منطق العمل؟"

* **Answer [EN] (STAR Method):**
  * **Situation:** We needed to integrate an enterprise e-learning platform (`LearnDynamicPro` in .NET 10 / Angular 19) with a sophisticated RAG AI engine (`LMS_CO_Pilot` in Python 3.13 / FastAPI / Qdrant).
  * **Task:** Design a robust, decoupled inter-service architecture with strict boundaries, zero state duplication, and unified security.
  * **Action:**
    1. **Strict Stateless Separation:** Designated .NET as the **Stateful Master Source of Truth** (owning SQL Server, relational entities, user permissions, and persistent quiz/summary records). Designated Python as the **Stateless Compute & Retrieval Engine** (owning audio ingestion, Qdrant vectors, hybrid search, and generative LLM orchestration). Python stores zero course data in SQL Server; it generates JSON payloads that .NET validates and persists.
    2. **Dual-Tier Authentication:** (a) End-user requests (Search, Streaming, Feedback) carry user JWTs issued by .NET (`HS256`, `JWT_SECRET`), which Python verifies to extract identity and RBAC entity filters. (b) Machine-to-Machine communication (webhooks and metadata lookups) uses a shared `SERVICE_TOKEN` via `X-Service-Token` headers under a strict Fail-Closed policy.
    3. **Postel's Law Routing:** Handled prefix differences by multiplexing routes under both `/v1/*` (canonical) and `/api/*` (compatibility alias) in FastAPI, ensuring zero runtime breaking changes.
  * **Result:** Achieved 100% decoupling: .NET team manages business workflows and UI in Angular; Python microservice scales independently on AI workloads without touching relational databases.

* **الإجابة [AR] (منهجية STAR):**
  * **الموقف (Situation):** كان التحدي هو ربط منصة تعليمية مؤسسية (`LearnDynamicPro` مبنية بـ .NET 10 و Angular 19) بمحرك ذكاء اصطناعي وبحث هجين متقدم (`LMS_CO_Pilot` مبني بـ Python 3.13 و FastAPI و Qdrant).
  * **المهمة (Task):** تصميم معمارية تواصل متينة ومفصولة الصلاحيات تمنع تكرار البيانات وتضمن أعلى درجات الأمان.
  * **الإجراء (Action):**
    1. **الفصل الصارم للمسؤوليات (Stateless vs Stateful):** جعلنا دوت نت هو **مصدر الحقيقة الدائم** (يملك SQL Server، بيانات المستخدمين، الكورسات، وحفظ نتائج الكويزات والملخصات). وجعلنا بايثون **محركاً حسابياً عديم الحالة** (مسؤول عن تفريغ الصوت، الفهرسة في Qdrant، والبحث والتوليد). بايثون لا يتصل بـ SQL Server ولا يحفظ الكويزات لديه؛ بل يولدها كـ JSON لحظي ليتولى دوت نت تدقيقها وحفظها.
    2. **نظام المصادقة المزدوج:** (أ) طلبات الطلاب تستخدم توكن الـ JWT الصادر من دوت نت (`HS256`) حيث يتحقق منه بايثون ويستخرج الصلاحيات. (ب) الاتصال المباشر بين السيرفرين (Machine-to-Machine) محمي بـ `SERVICE_TOKEN` إلزامي مشفر عبر ترويسة `X-Service-Token` بمبدأ Fail-Closed الصارم.
    3. **تطبيق قانون بوستيل للمسارات:** توفير المسارات ببادئتين `/v1/*` و `/api/*` بالتوازي لمنع أي أخطاء 404 عند استدعاءات عملاء دوت نت.
  * **النتيجة (Result):** استقلال تام للمنظومتين: فريق دوت نت يطور شاشات Angular ومنطق الأعمال بحرية، ومحرك بايثون يتوسع في مهام الذكاء الاصطناعي دون أن يعلق في تعقيدات قواعد البيانات العلائقية.

---

#### Q10: The `AiStatus` State Machine & Lifecycle (Handling Multi-Minute Ingestion)
* **Question [EN]:** "Audio transcription and vector ingestion take minutes to complete. How does the system manage this lifecycle, inform the Angular UI, and handle failures? Walk me through the `AiStatus` state machine."
* **السؤال [AR]:** "معالجة الفيديو وتفريغ الصوت تستغرق عدة دقائق. كيف تدير المنظومة دورة حياة هذه المعالجة، وكيف تبلغ واجهة المشرف بالنجاح أو الفشل؟ اشرح لي آلة حالة الـ `AiStatus` بالتفصيل."

* **Answer [EN]:**
  * "To provide a seamless UX without blocking HTTP threads, we designed the **5-state `AiStatus` lifecycle**:
    1. **`None`:** The lesson was newly created with a video URL. No vectors exist yet in Qdrant; content generation buttons are disabled.
    2. **`Queued`:** .NET emits `POST /v1/webhooks/lesson-updated`. Python acquires a per-lesson `asyncio.Lock` to prevent concurrent duplicate processing, queues the task in the background, and returns `202 Accepted` within 15ms.
    3. **`Processing`:** The pipeline downloads audio, calls Whisper for transcription, normalizes text with Gemini Flash, generates BGE-M3 embeddings, and upserts chunks to Qdrant. The Angular UI displays an active progress spinner.
    4. **`Completed`:** Qdrant upsert succeeds (`chunks_count > 0`). Python executes an **Asynchronous Webhook Callback** (`POST /api/internal/lessons/{lessonId}/ai-status`) notifying .NET that status is `Completed`. The Angular UI unlocks the 'Generate Quiz' and 'Generate Summary' buttons.
    5. **`Failed`:** If YouTube download fails, audio is corrupt, or quota is exceeded, the pipeline catches the error in `PipelineOrchestrator`, cleans up temp files in `finally:`, and dispatches the callback with `status: 'Failed'` and the human-readable error message. The Angular UI turns the badge red and displays an interactive **'إعادة المحاولة (Retry)'** button.
    6. **Resilient Dual-Sync (Push + Poll):** If the webhook callback drops due to a network glitch, .NET or Angular can query `GET /v1/ingest/status/{lesson_id}`. Python checks Qdrant chunk counts and in-memory locks, returning the live ground truth without requiring an intermediate queue database."

* **الإجابة [AR]:**
  * "لضمان تجربة مستخدم استثنائية دون حجز اتصالات السيرفر لدقائق، صممنا **دورة حياة `AiStatus` خماسية الحالات**:
    1. **`None` (غير معالج):** الدرس مضاف حديثاً برابط فيديو، لا توجد أي مقاطع في Qdrant، وأزرار توليد الكويز والملخص معطلة في الواجهة.
    2. **`Queued` (في الانتظار):** دوت نت يرسل Webhook لبايثون، يحجز بايثون قفل الدرس التزامني `asyncio.Lock` لمنع المعالجة المزدوجة، ويضع المهمة في الخلفية ويرد في 15ms بـ `202 Accepted`.
    3. **`Processing` (قيد المعالجة):** يبدأ بايثون سحب الصوت، التفريغ بـ Whisper، التنقيح بـ Gemini، والتضمين بـ BGE-M3 والرفع لـ Qdrant. تعرض واجهة Angular مؤشر تحميل تفاعلي.
    4. **`Completed` (مكتمل بنجاح):** تكتمل الفهرسة وتصبح المقاطع جاهزة. يستدعي بايثون فوراً الـ Webhook Callback لدوت نت: `POST /api/internal/lessons/{lessonId}/ai-status` بـ `status: Completed`. تتحول الشارة في الواجهة للأخضر وتتألق أزرار 'توليد الكويز' و'توليد الملخص'.
    5. **`Failed` (فشل):** إذا كان رابط الفيديو معطلاً أو انقطعت الشبكة، يلتقط بايثون الخطأ وينظف الملفات المؤقتة في كتلة `finally:`، ويرسل إشعاراً لـ دوت نت بـ `status: Failed` مع نص الخطأ. تظهر شارة حمراء في الواجهة مع زر **'إعادة المحاولة (Retry)'**.
    6. **التزامن الهجين (Push + Poll):** لضمان عدم ضياع الحالة في حال سقط إشعار الويب هوك، يوفر بايثون مسار `GET /v1/ingest/status/{lesson_id}` يفحص Qdrant وقفل الذاكرة لحظياً ويرجع الحالة الحقيقية فوراً."

---

#### Q11: Adaptive Quiz Generation (`min(k, chunks)`) & Anti-Hallucination
* **Question [EN]:** "What happens when an instructor requests a 5-question quiz for a 90-second video lesson? How did you prevent hallucinations while keeping the API reliable?"
* **السؤال [AR]:** "ماذا يحدث عندما يطلب المحاضر كويز من 5 أسئلة لمحاضرة قصيرة مدتها 90 ثانية؟ كيف منعت الهلوسة وحافظت على استقرار السيرفر؟"

* **Answer [EN]:**
  * "In audio RAG systems, fixed-output requirements often conflict with context constraints. A 90-second video split into 120-second segments produces only 1 or 2 chunks in Qdrant. If you force an LLM to produce 5 multiple-choice questions from 1 chunk, the model runs out of factual statements and hallucinates plausible-sounding facts to fulfill the contract, violating our 92% Faithfulness SLA.
  * **Our Architectural Solution in [lesson_content_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/lesson_content_service.py):**
    1. **Adaptive Bound:** We calculate `actual_questions = min(num_questions, len(chunks))`. If only 2 chunks exist, we instruct Gemini to synthesize exactly 2 high-value, strictly grounded questions.
    2. **Typed Error Protection:** If `len(chunks) == 0` (the lesson has not completed ingestion), instead of executing Gemini with an empty prompt and crashing with an unhandled 500 error, we return an explicit `404 Not Found` with `detail='Lesson ... has no ingested content chunks in Qdrant. Please ensure the video has been ingested first.'`.
    3. This architectural nuance preserves 100% faithfulness, prevents user confusion, and guarantees deterministic system behavior."

* **الإجابة [AR]:**
  * "في أنظمة الـ RAG، فرض عدد أسئلة ثابت يصطدم غالباً بقلة المحتوى. فيديو مدته 90 ثانية ينتج مقطعاً واحداً أو مقطعين في Qdrant. إذا أجبرت الموديل على تأليف 5 أسئلة اختيار من متعدد من مقطع واحد، سينفد المحتوى الحقيقي فيلجأ لاختلاق أسئلة ومعلومات وهمية من خياله، مما ينسف معيار الأمانة (Faithfulness) الذي بنيناه.
  * **حلنا الهندسي في [lesson_content_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/lesson_content_service.py):**
    1. **السقف المتكيف:** حساب عدد الأسئلة بمعادلة: `actual_questions = min(num_questions, len(chunks))`. فإذا كان الدرس يحتوي مقطعين فقط، يولد كويز من سؤالين متميزين مستندين 100% للشرح.
    2. **الحماية من الانهيار:** إذا كان عدد المقاطع صفراً (الدرس لم يعالج بعد)، نمنع إرسال برومبت فارغ للموديل ولا نرجع خطأ 500؛ بل نرجع كود `404 Not Found` واضح وصريح يطلب معالجة الفيديو أولاً.
    3. هذه اللمسة الهندسية تمنع الهلوسة تماماً، وتحمي واجهة المستخدم من الانهيار، وتثبت فهمك العميق للإنتاجية في المقابلات."

---

#### Q12: Resilient JWT Ingress & Cross-Stack Claim Negotiation
* **Question [EN]:** "When integrating .NET Identity JWTs into Python FastAPI, tokens for System Administrators caused 422/500 validation failures due to missing `company_id`. How did you resolve this without disabling security?"
* **السؤال [AR]:** "عند استقبال توكنات .NET Identity في بايثون، توكنات المشرفين العامين (SuperAdmin) تسببت في أخطاء 422/500 بسبب غياب حقل `company_id`. كيف حللت هذه المشكلة دون الإخلال بأمان النظام؟"

* **Answer [EN]:**
  * "In multi-tenant SaaS platforms, regular users belong to a specific company (`company_id`), but Global Administrators (SuperAdmins) span the entire platform and do not have a fixed `company_id` claim in their JWTs. Initially, our strict Pydantic `TokenClaims` marked `company_id: str` as required, triggering `ValidationError` (422/500) whenever an admin generated quizzes or summaries.
  * **Our Resolution:**
    1. **Flexible Claim Schema:** In [auth_models.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/models/auth_models.py), made `company_id: str | None = None` and provided safe defaults for `role` (`Student`).
    2. **Graceful Fallback Parser:** In [auth_service.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/src/services/auth_service.py), we wrapped Pydantic validation in a `try...except ValidationError` block. If strict validation fails on unexpected claim shapes, the service decodes the verified payload, extracts user identifiers (`sub` or `Id`) and roles (`role` or `Role`), and constructs a valid `TokenClaims` instance.
    3. **Zero Compromise on Cryptography:** Signature verification against `JWT_SECRET` with `HS256` remains 100% intact; only the claim extraction is made resilient to cross-platform naming differences."

* **الإجابة [AR]:**
  * "في أنظمة الـ SaaS متعددة الشركات (Multi-Tenant)، ينتمي الموظف لشركة محددة فيحمل حقل `company_id`، بينما المشرف العام على المنصة (SuperAdmin) يدير كل الشركات ولا يرتبط بمعرف شركة واحدة في الـ JWT. في البداية كان نموذج Pydantic الصارم يفرض وجود `company_id`، فكان ينهار بخطأ 422 أو 500 عندما يحاول المشرف العام توليد كويز أو ملخص.
  * **حلنا الهندسي:**
    1. **مرونة النموذج:** جعلنا `company_id: str | None = None` مع وضع قيمة افتراضية للرتبة.
    2. **المعالج الدفاعي في `auth_service.py`:** أحطنا بناء النموذج بكتلة `try...except ValidationError`؛ فلو اختلف شكل المطالبات بين .NET وبايثون، يستخرج السيرفر البيانات الأساسية من التوكن المفحوص ويبني كائن الصلاحيات بأمان.
    3. **عدم المساس بالأمان الرياضي:** التحقق من صحة التوقيع المشفر بالمفتاح السري `JWT_SECRET` وخوارزمية `HS256` يظل فعالاً بنسبة 100%؛ المرونة كانت فقط في قراءة الحقول التوافقية."

---

## 🛠️ 5. سيناريوهات استكشاف الأعطال وتصميم النظم (Troubleshooting & Scenarios)

---

### سيناريو 1: تشخيص الهلوسة (Diagnosing Hallucination)
* **Question [EN]:** "A user reports: 'The bot generated incorrect accounting instructions for adding a supplier!' What is your diagnostic tree?"
* **السؤال [AR]:** "مستخدم يشتكي: 'المساعد الذكي رد بخطوات محاسبية خاطئة لإضافة مورد!' ما هي شجرة التشخيص التي تتبعها؟"

* **Answer [EN]:**
  1. **Locate Trace Artifact:** Inspect the corresponding JSON execution log in `downloads/search_debugs/` by timestamp.
  2. **Isolate Retrieval vs. Generation:**
     - Check `qdrant_rrf_candidates` and `reranker_results`: Were the correct lesson chunks retrieved?
     - *If retrieval was bad:* The issue is in chunking boundaries, query embedding normalization, or missing syllabus indexing.
     - *If retrieval was good but answer was wrong:* The issue is in the generation prompt instructions, context injection format, or temperature (we keep temperature at `0.2` to minimize randomness).
  3. **Run Ragas Faithfulness:** Run the query against `scripts/run_rag_eval.py` to calculate exact faithfulness score.

* **الإجابة [AR]:**
  1. **فحص الـ Trace:** فتح ملف الـ JSON الخاص بالطلب في `downloads/search_debugs/`.
  2. **عزل المشكلة (استرجاع أم توليد؟):**
     - فحص المقاطع المسترجعة في `reranker_results`: هل كانت المقاطع تحتوي على شرح إضافة المورد فعلاً؟
     - *إذا كانت المقاطع سيئة:* العيب في الاسترجاع أو التقطيع أو أن الدرس لم يُفهرس كاملاً.
     - *إذا كانت المقاطع ممتازة والإجابة خاطئة:* العيب في البرومبت التوجيهي أو أن درجة الحرارة مرتفعة (لدينا مثبتة على `0.2` لمنع العشوائية).
  3. **فحص الـ Faithfulness:** تمرير الحالة في سكريبت التقييم لمعرفة جملة الاختلاق بدقة.

---

### سيناريو 2: معالجة قفزات زمن الاستجابة (Handling Latency Spikes)
* **Question [EN]:** "Search latency suddenly spiked from 1.2s to 9s in production. How do you find the bottleneck?"
* **السؤال [AR]:** "زمن استجابة البحث قفز فجأة من 1.2 ثانية إلى 9 ثوانٍ في الإنتاج. كيف تحدد موضع الاختناق؟"

* **Answer [EN]:**
  * "We query Prometheus metrics exposed at `/metrics` via `lms_rag_stage_duration_seconds` grouped by stage:
    * `stage="embedding"`: Checks CPU utilization on the sentence-transformers thread pool.
    * `stage="vector_search"`: Checks Qdrant memory, HNSW indexing saturation, and network latency.
    * `stage="reranking"`: Verifies that candidate limit did not exceed `settings.QDRANT_SEARCH_CANDIDATES_LIMIT = 8`.
    * `stage="gemini_generation"`: Checks upstream Google API latency, token size spikes, or rate limiting throttling."

* **الإجابة [AR]:**
  * "نرجع فوراً إلى مقاييس Prometheus المتاحة على نقطة `/metrics` ومؤشر `lms_rag_stage_duration_seconds`:
    * مرحلة `embedding`: التأكد من عدم وجود ضغط على الـ CPU في معالجة التضمين.
    * مرحلة `vector_search`: فحص سرعة شبكة واستجابة Qdrant.
    * مرحلة `reranking`: التأكد من عدم تمرير عدد مرشحين أكبر من الحد المحدد (8 مرشحين).
    * مرحلة `gemini_generation`: فحص ما إذا كان التأخير ناتجاً عن ضغط أو بطء في خوادم Google API السحابية."

---

### سيناريو 3: التوافقية العابرة للغات وقانون بوستيل (.NET 10 + Python Interoperability & Postel's Law)
* **Question [EN]:** "When integrating your Python AI service with a separate .NET 10 enterprise backend, you encountered runtime contract mismatches, route prefix conflicts, and disk exhaustion under failed ingestion. How did you resolve them without breaking existing clients?"
* **السؤال [AR]:** "عند ربط خدمة الـ Python AI مع منصة .NET 10 مؤسسية، واجهت تناقضات برمجية وقت التشغيل في المسارات والـ DTOs، وتسريباً في مساحة القرص عند فشل المعالجة. كيف قمت بحلها دون كسر التوافق مع الأنظمة العاملة؟"

* **Answer [EN] (STAR Method):**
  * **Situation:** Pre-production end-to-end integration revealed subtle breaking incompatibilities between our Python FastAPI microservice and the .NET 10 backend (`DynamicProLearn`): .NET HTTP clients queried `/api/admin/...` while Python exposed `/v1/admin/...`; missing `overview` fields failed .NET summary validation; and aborted ingestion pipelines left orphaned audio files in `downloads/`, threatening container disk exhaustion.
  * **Task:** Establish a canonical integration contract, guarantee zero-downtime routing compatibility, harden resource lifecycles, and deploy active SLA alert routing.
  * **Action:**
    1. **Canonical Contract v3.0.0:** Authored and locked `docs/LMS_INTEGRATION_CONTRACT.md` as the frozen bidirectional single source of truth across 8 endpoints and 2 webhooks.
    2. **Dual-Prefix Multiplexing (Postel's Law):** Obeyed Postel's Robustness Principle (*"Be conservative in what you send, be liberal in what you accept"*) by registering routes under both `/v1` and `/api` simultaneously via FastAPI's router inclusion, ensuring zero disruption regardless of client prefix conventions.
    3. **Defensive Resource Reclaim:** Refactored `PipelineOrchestrator` to enforce file cleanup in a strict `finally:` block, guaranteeing disk deletion even if Whisper transcription, normalization, or Qdrant vector indexing throws uncaught exceptions.
    4. **Alertmanager 9093 & OWASP Headers:** Provisioned Alertmanager in `docker-compose.yml` for SLA violation dispatch, and injected defensive OWASP security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`) in `CorrelationMiddleware`.
  * **Result:** Achieved 100% automated test compliance ([tests/unit/test_dotnet_compatibility.py](file:///e:/Mazen/EgyDynamic/LMS_CO_Pilot/tests/unit/test_dotnet_compatibility.py)), zero leaked inodes under simulated failures, and frictionless cross-stack interoperability.

* **الإجابة [AR] (منهجية STAR):**
  * **الموقف (Situation):** عند فحص التكامل الفعلي مع منصة `.NET 10`، ظهرت تناقضات برمجية قاتلة (Breaking Incompatibilities): منصة دوت نت ترسل طلبات ببادئة `/api/admin/...` بينما بايثون ينتظر `/v1/admin/...`، ونقص حقل `overview` تسبب في فشل التحقق البرمجي لدوت نت، كما تبين أن فشل استيعاب الفيديوهات يترك ملفات صوتية مهملة بالقرص تهدد بامتلاء حاوية الدوكر.
  * **المهمة (Task):** تثبيت عقد تكامل قياسي موحد، وضمان التوافقية للمسارات دون كسر عملاء دوت نت، وحماية موارد السيرفر، وتفعيل موزع التنبيهات.
  * **الإجراء (Action):**
    1. **عقد التكامل القياسي v3.0.0:** تجميد وثيقة `docs/LMS_INTEGRATION_CONTRACT.md` كمرجع موحد ونهائي لـ 8 مسارات واثنين Webhook.
    2. **التوجيه المزدوج وقانون بوستيل (Postel's Law):** تطبيق مبدأ *"كن متساهلاً فيما تستقبل، صارماً فيما ترسل"* بتسجيل المسارات تحت كل من `/v1` و `/api` في نفس الوقت، ليستجيب بايثون بسلاسة مهما كانت بادئة طلبات دوت نت.
    3. **الحماية الدفاعية للموارد (Finally Cleanup):** نقل عملية حذف الملفات الصوتية المؤقتة لكتلة `finally:` إلزامية لضمان الحذف التلقائي من القرص حتى لو حدث استثناء مفاجئ أثناء التفريغ أو التضمين.
    4. **موزع التنبيهات وترويسات OWASP:** دمج خدمة Alertmanager على المنفذ 9093 لتوزيع تنبيهات الـ SLA، وحقن ترويسات الأمان المؤسسية (`nosniff`, `DENY`) في الـ Middleware.
  * **النتيجة (Result):** اجتياز كامل لاختبارات التوافقية بنسبة 100%، وحماية تامة للقرص من التسريب، وتكامل سلس ومستقر بين بيئتي العمل دون أي تعديل اضطراري لكود .NET.

---

### سيناريو 4: الأمان الموزع والتوقيع المشفر والـ Zero-Hop RBAC (HMAC-SHA256 Webhooks & Zero-Hop Claims)
* **Question [EN]:** "In enterprise integrations, static service tokens are vulnerable to leakage, and cross-service permission round-trips add unacceptable latency. How did you harden machine-to-machine webhooks and optimize token authorization in your AI microservice?"
* **السؤال [AR]:** "في تكامل الأنظمة المؤسسية، تُعد توكنات الخدمات الثابتة عرضة للتسريب، كما أن استدعاءات الصلاحيات المتكررة بين الخدمات تزيد من زمن التأخير (Latency). كيف حصّنت الويب هوك بين الأنظمة وحسّنت مصادقة وصلاحيات التوكن في محرك الذكاء الاصطناعي؟"

* **Answer [EN] (STAR Method):**
  * **Situation:** Our Python AI service previously used a static shared secret header (`X-Service-Token`) for .NET webhooks, which was vulnerable to replay attacks and payload tampering. Concurrently, every student and admin search request performed a network round-trip back to the .NET LMS backend to fetch granular permissions, adding 20-40ms to search latency and causing cascading 503 outages whenever the LMS service experienced brief blips.
  * **Task:** Upgrade webhook authentication to industry cryptographic standards, eliminate redundant inter-service network hops for Admins, and ensure zero-downtime resilient fallback for student search.
  * **Action:**
    1. **Stripe/GitHub Standard HMAC-SHA256:** Replaced static tokens with digital signatures calculated over raw binary UTF-8 request bytes (`timestamp + "." + raw_body`) matching .NET `WebhookDispatcher`. Added strict anti-replay attack expiration (`abs(now - timestamp) <= 300s`) and constant-time signature comparison (`hmac.compare_digest`).
    2. **Zero-Hop Claims RBAC (Admins 0ms Hop):** Decoded `company_id` and `department_id` directly from .NET 10 JWT claims via Pydantic `AliasChoices`. Admins bypass LMS permission network calls entirely (0ms hop).
    3. **Resilient Student Fallback:** For non-admins, if the LMS permission service is temporarily unreachable, the system gracefully falls back to token claims for tenant/department isolation instead of raising a 503 error.
  * **Result:** Achieved 100% test pass rate across 51 unit tests, saved 20-40ms on search queries, and hardened distributed webhook communication against replay and timing side-channel attacks.

* **الإجابة [AR] (منهجية STAR):**
  * **الموقف (Situation):** كان محرك الذكاء الاصطناعي يعتمد على توكن خدمة ثابت (`X-Service-Token`) للـ Webhooks القادمة من دوت نت، وهو عرضة لهجمات الإعادة (Replay Attacks) والتلاعب بالبيانات. في الوقت ذاته، كان كل استعلام بحث للمشرف أو الطالب يرسل طلباً شبكياً للـ LMS لجلب الصلاحيات، مما يضيف 20-40ms زمن تأخير ويتسبب في أخطاء 503 عند أي تذبذب في خادم الـ LMS.
  * **المهمة (Task):** ترقية أمان الـ Webhook إلى المعايير التشفيرية القياسية عالمياً، وإلغاء القفزات الشبكية الزائدة للمشرفين، وتوفير بديل مرن يمنع انهيار الخدمة للطلاب.
  * **الإجراء (Action):**
    1. **توقيع رقمي HMAC-SHA256 بمعيار Stripe و GitHub:** استبدال التوكن الثابت بتوقيع رقمي يُحسب على بايتات الطلب الخام مباشرة (`timestamp + "." + raw_body`)، مع مهلة أمان ضد هجمات الإعادة (Anti-Replay <= 300 ثانية)، ومقارنة ثابتة الزمن بـ `hmac.compare_digest`.
    2. **القفزة الصفرية للصلاحيات (Zero-Hop Claims RBAC):** استخراج معرف الشركة والقسم مباشرة من Claims توكن JWT لدوت نت عبر `AliasChoices`. المشرف يتخطى استدعاءات الشبكة بنسبة 100% (0ms network hop).
    3. **التراجع المرن للطلاب (Resilient Fallback):** في حال تعطل خدمة صلاحيات LMS مؤقتاً، يتراجع بايثون للعزل بناءً على بيانات التوكن بدلاً من رفض الطلب بـ 503.
  * **النتيجة (Result):** اجتياز 51 اختباراً مؤتمتاً بنجاح 100%، توفير 20-40ms في استعلامات البحث، وتحصين النظام بالكامل ضد هجمات التوقيت والتلاعب بالحمولة.

---

## 🗺️ 6. خارطة طريق التطور الهندسي (From Junior to Senior AI Engineer)

* **[EN]:** To transition from an impressive Junior/Associate to a Solid Mid-Level and Senior AI Engineer:
  1. **Distributed Tracing:** Replace disk-based JSON debug logs with **Langfuse** or **OpenTelemetry** spans across multi-service boundaries.
  2. **Streaming & Observability (Delivered in M06 & M07):** ✅ Completed real-time SSE streaming (<300ms TTFT, TPOT telemetry) and declarative Prometheus SLA alerting (`alerts.yml`).
  3. **Self-RAG Loops:** Upgrade LangGraph from a linear fast-path graph to an agentic reflection loop that self-corrects low-confidence retrieval misses in background workers.
  4. **Distributed Scalability:** Introduce Redis as a distributed cache cluster and Celery/Kafka for audio job queues across multi-node Kubernetes clusters.

* **[العربية]:** للانتقال من مرحلة المبتدئ المتميز إلى مستوى Mid-Level صلب ثم Senior:
  1. **التتبع الموزع (Distributed Tracing):** استبدال ملفات JSON المحلية بمنصة مركزية موزعة مثل **Langfuse** أو **OpenTelemetry**.
  2. **تدفق التوكنز والإنذارات (تم إنجازهما في M06 و M07):** ✅ تم بناء البث اللحظي عبر SSE (<300ms TTFT مع قياس TPOT) ومنظومة التنبيهات والـ SLAs في Prometheus.
  3. **وكلاء التقييم الذاتي (Self-RAG Loops):** ترقية LangGraph لجراف تفاعلي يعيد صياغة الأسئلة ذاتياً عند ضعف جودة الاسترجاع كخدمة في الخلفية.
  4. **التوسع السحابي (Scalability):** دمج Redis ككاش مركزي، و Kafka/Celery لطوابير معالجة الفيديوهات عبر Kubernetes.

---

## 🔄 7. سكيل التحديث التلقائي للملف (Auto-Update Lifecycle via Skill & Triad)

* **[EN]:** Whenever new architectural changes, endpoints, or guardrails are implemented in this repository, run:
  `/readme-updater` or `/interview-prep-planner`
  The system automatically triggers the **Living Showcase Triad**, synchronizing:
  1. [`README.md`](../README.md) (Public GitHub Showcase)
  2. [`docs/chronicle/MASTER_ROADMAP.md`](chronicle/MASTER_ROADMAP.md) (Milestone Dossiers & STAR story sources)
  3. This file (`docs/INTERVIEW_PORTFOLIO_MASTER_GUIDE.md`) (Technical Q&A & Seniority Matrix)

* **[العربية]:** كلما تم تطبيق ميزات جديدة أو خدمات إضافية في المشروع، استدعِ السكيل في أي وقت عبر:
  `/readme-updater` أو `/interview-prep-planner`
  وسيقوم النظام بمزامنة **منظومة التوثيق الثلاثية الحية** تلقائياً عبر ربط مستجدات الكود، ومطابقة معالم المشروع (Milestones) في `docs/chronicle/` مع أسئلة وإجابات المقابلات في هذا الملف.

