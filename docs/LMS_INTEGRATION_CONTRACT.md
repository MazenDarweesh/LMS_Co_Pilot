---
document_type: "API Integration Contract"
contract_version: "2.2.0"
last_synced_commit: "HEAD"
last_synced_date: "2026-09-13"
target_backend: ".NET LMS Backend & Frontend (Angular / Blazor)"
---

# 📄 LMS Integration Contract (AI Content Generation & Search)

## نظرة عامة
هذا الملف موجه لفرق تطوير الـ .NET (LMS Backend) والواجهات الأمامية (Frontend). يوضح هذا الملف شكل التخاطب بين نظام الـ LMS ومحرك الذكاء الاصطناعي (Python Engine) فيما يخص:
1. توليد الاختبارات والملخصات وتثبيتها على صفحات الدروس.
2. محرك البحث اللحظي المدعوم بالبث المباشر (Server-Sent Events - SSE).
3. محرك تسجيل تقييمات الطلاب (Student Feedback Engine).

---

## 1. توليد اختبار للدرس (Quiz Generation)

**المسار (Route):** `POST /api/admin/lessons/{lesson_id}/generate-quiz`
**الصلاحيات:** `Admin` (يتم التحقق عبر الـ JWT المرسل في الـ Header)
**آلية العمل:** يقوم النظام بسحب سياق الفيديو من الـ Qdrant، وتوليد 5 أسئلة MCQ مقسمة على طول الفيديو، وإرجاع الـ JSON التالي لـ .NET (بدون حفظه في Python).

### Response JSON (GeneratedQuiz)
```json
{
  "lesson_id": "string",
  "generated_at": "2026-08-25T15:00:00Z",
  "questions": [
    {
      "id": 1,
      "question": "ما هي الوظيفة الأساسية لموديول الـ POS؟",
      "options": [
        { "id": "a", "text": "إدارة الموظفين" },
        { "id": "b", "text": "تسجيل نقاط البيع" },
        { "id": "c", "text": "إدارة المخازن" },
        { "id": "d", "text": "عمل القيود اليومية" }
      ],
      "correct_answer_id": "b",
      "explanation": "موديول الـ POS (Point of Sale) مخصص لتسجيل المبيعات اللحظية."
    }
  ]
}
```
*ملاحظة لمهندسي .NET:* محرك Python يعيد الإجابات الصحيحة (`correct_answer_id`). يجب حفظ هذه الإجابات في قاعدة بيانات .NET (SQL Server) لاستخدامها في التصحيح التلقائي للطالب، وإخفائها عند إرسال الاختبار لواجهة الطالب (UI).

---

## 2. توليد ملخص للدرس (Summary Generation)

**المسار (Route):** `POST /api/admin/lessons/{lesson_id}/generate-summary`
**الصلاحيات:** `Admin`
**آلية العمل:** يقوم النظام باستخدام (Pyramid Summarization) لاستخراج أهم 3-5 مواضيع رئيسية مع نقاطها التفصيلية.

### Response JSON (GeneratedSummary)
```json
{
  "lesson_id": "string",
  "generated_at": "2026-08-25T15:00:00Z",
  "topics": [
    {
      "title": "إعدادات صلاحيات المستخدمين",
      "points": [
        "افتح شاشة الإعدادات وانتقل إلى قسم الأمان.",
        "اختر الموظف وقم بتفعيل خيار 'إدارة المخازن'."
      ]
    }
  ]
}
```

---

## 3. حفظ وعرض البيانات (LMS Responsibility)

> **قرار معماري هام (Stateless AI Engine):**
> محرك الذكاء الاصطناعي (Python) لن يقوم بحفظ الاختبارات أو الملخصات في قاعدة بياناته. المحرك يعمل كـ "مُوَلِّد" فقط. 
> 
> **المطلوب من فريق الـ .NET:**
> بمجرد نجاح نداء `POST /generate-quiz` أو `POST /generate-summary` واستلام الـ JSON:
> 1. يجب حفظ هذا المحتوى في قاعدة بيانات الـ LMS (SQL Server) بجوار الدرس (مثلاً في جداول `LessonQuizzes` و `LessonSummaries`).
> 2. عند فتح الطالب لصفحة الدرس، يتم عرض المحتوى مباشرة من قاعدة بيانات الـ LMS، **ولا يتم عمل أي نداء (HTTP Request)** لمحرك الـ Python لتخفيف الضغط وتقليل الـ Latency.

---

## 4. البحث اللحظي بالبث المباشر (Real-Time Search Streaming)

**المسار (Route):** `POST /v1/search/stream`  
**الترويسة (Headers):**
- `Authorization: Bearer <JWT>`
- `Accept: text/event-stream`
- `Content-Type: application/json`

### جسم الطلب (Request Payload):
```json
{
  "query": "كيف يتم عمل قيد استحقاق الرواتب في موديول الحسابات؟",
  "lesson_id": "lesson_accounting_101",
  "scope": "lesson",
  "thread_id": "optional_conversation_thread_uuid"
}
```

### شكل مجرى البث (SSE Protocol):
يتم تدفق البيانات بصيغة أحداث `text/event-stream` قياسية ومشفرة بـ `UTF-8` الصريح دون هروب الحروف العربية:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no

event: sources
data: {"sources": [{"type": "video", "url": "https://youtu.be/xyz?t=45", "start": 45, "end": 120, "lesson_id": "lesson_accounting_101"}]}

event: token
data: {"text": "يتم "}

event: token
data: {"text": "تسجيل قيد استحقاق الرواتب عبر الطرف المدين: مصروف الرواتب..."}

: heartbeat

event: done
data: {"thread_id": "optional_conversation_thread_uuid", "metrics": {"total_latency_ms": 320.5}}
```

**ملاحظات هامة لفريق الواجهة الأمامية (Frontend):**
1. **الترتيب المضمون:** الحدث الأول دائماً هو `event: sources` لتثبيت روابط الفيديو فوراً، يليه سلسلة أحداث `event: token`، وينتهي بالحدث النهائي `event: done`.
2. **نبضات القلب (`: heartbeat\n\n`):** يرسل السيرفر تعليق SSE قياسي كل 15 ثانية صمت لمنع وسائط الـ Proxy و Cloudflare من قطع الاتصال، ويجب على الـ Frontend تجاهل أسطر التعليقات التي تبدأ بنقطتين (`:`).
3. **قطع الاتصال الذكي:** بمجرد إغلاق المستخدم للنافذة، يُلغي السيرفر حرق التوكنات فوراً.

---

## 5. محرك تقييمات الطلاب (Student Feedback Engine)

**المسار (Route):** `POST /v1/search/feedback`  
**الصلاحيات:** متاح للطلاب والأساتذة والإداريين عبر الـ JWT.  
**آلية العمل:** تسجيل فوري لتقييم الرد (إبهام لأعلى 👍 أو إبهام لأسفل 👎) مع منع التكرار اللحظي عبر الـ In-Memory Cache (خلال 24 ساعة للطلب الواحد).

### Request JSON:
```json
{
  "query": "كيف يتم حساب الإهلاك؟",
  "answer": "يتم حساب الإهلاك بالقسط الثابت...",
  "rating": "up", // أو "down"
  "comment": "شرح واضح وسريع جداً، شكراً لكم!",
  "lesson_id": "lesson_accounting_101",
  "thread_id": "optional_thread_uuid",
  "sources": [
    {
      "type": "video",
      "url": "https://youtu.be/vid_123",
      "start": 120,
      "end": 180,
      "lesson_id": "lesson_accounting_101"
    }
  ]
}
```

### Response JSON (نجاح):
```json
{
  "status": "success",
  "message": "شكراً لمشاركتك! تم تسجيل تقييمك بنجاح للمساهمة في تحسين جودة التعليم. 🎓"
}
```

### Response JSON (تكرار التقييم لنفس السؤال):
```json
{
  "status": "duplicate",
  "message": "تم تسجيل تقييمك مسبقاً لهذا السؤال. شكراً لمشاركتك! 🎓"
}
```

---

## 6. استعلامات وتحليلات التقييمات للإدارة والأساتذة (Admin & Quality Analytics)

**المسار (Route):** `GET /v1/admin/feedback`  
**الصلاحيات:** متاح للأدمن والمدرسين (`Admin`, `Teacher`) ومحصور تلقائياً بنطاق الشركة (`tenant_id`).  
**محددات البحث (Query Parameters):**
- `lesson_id` (اختياري): لتصفية التقييمات الخاصة بدرس محدد.
- `rating` (اختياري): تصفية حسب نوع التقييم (`UP` أو `DOWN`).
- `format` (اختياري): `json` (الافتراضي للوحة التحكم) أو `ragas` (لتصدير مصفوفة Golden Dataset جاهزة لـ Ragas).
- `limit`: حد أقصى للنتائج (الافتراضي 50).
- `offset`: ترقيم الصفحات (Pagination).

### Response JSON (نمط لوحة التحكم `format=json`):
```json
{
  "records": [
    {
      "id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "tenant_id": "company_erp_01",
      "department_id": "accounting",
      "user_id": "student_101",
      "user_role": "Student",
      "lesson_id": "lesson_accounting_101",
      "thread_id": "thread_abc_123",
      "query_hash": "sha256_hash",
      "answer_hash": "sha256_hash",
      "query_text": "كيف يتم حساب الإهلاك؟",
      "answer_text": "يتم حساب الإهلاك بالقسط الثابت...",
      "rating": "UP",
      "comment": "شرح ممتاز ومباشر",
      "sources": [],
      "created_at": "2026-09-14T12:00:00Z"
    }
  ],
  "analytics": {
    "total_votes": 45,
    "up_votes": 41,
    "down_votes": 4,
    "satisfaction_rate": 91.11
  },
  "limit": 50,
  "offset": 0
}
```

### Response JSON (نمط تقييم Ragas الآلي `format=ragas`):
```json
[
  {
    "user_input": "كيف يتم حساب مجمع الإهلاك؟",
    "response": "يتم إقفال الإهلاك في حساب الأرباح والخسائر...",
    "retrieved_contexts": [
      "https://youtu.be/acc101?t=120s"
    ],
    "rating": "DOWN",
    "student_comment": "المقطع لم يوضح المعالجة في نهاية السنة",
    "lesson_id": "lesson_accounting_101",
    "thread_id": "thread_abc_123"
  }
]
```

