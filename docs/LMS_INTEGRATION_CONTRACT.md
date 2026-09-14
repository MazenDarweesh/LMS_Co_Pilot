---
document_type: "Canonical API Integration Contract & Architecture Standard"
contract_version: "3.0.0-FINAL"
last_synced_date: "2026-09-14"
status: "FROZEN_CANONICAL_STANDARD"
lead_author: "Antigravity & Mazen Darweesh (Lead Engineering)"
target_backends:
  - ".NET 10 LMS Backend (LearnDynamicPro)"
  - "Python AI Co-Pilot Engine (LMS_CO_Pilot)"
  - "Angular 19 Frontend (DynamicProLearn.Client)"
---

# 📜 Canonical LMS & AI Co-Pilot Contract (v3.0.0 النهائي)

> [!IMPORTANT]
> **وثيقة المعيار الإلزامي الموحد (The Frozen Canonical Standard)**  
> هذا العقد **مُغلق ومُعتمد نهائياً**. لا توجد مسارات بديلة أو خيارات متعددة. 
> يجب على فرق التطوير (.NET و Angular) الالتزام **الحرفي** بالمسارات ونماذج البيانات (DTOs) المحددة أدناه لضمان نجاح التشغيل الفعلي (Zero Runtime Incompatibility).

---

## 🎯 القواعد المعمارية الثابتة (The Non-Negotiables)

1. **محرك الذكاء الاصطناعي عديم الحالة (Stateless Engine):**  
   بايثون هو مُولِّد لحظي (Generator)، ولا يحفظ الكويزات أو الملخصات في قاعدة بياناته. **الحفظ النهائي يتم حصراً داخل SQL Server عبر .NET**.
2. **البادئة الموحدة لجميع المسارات هي `/v1/` حصراً:**  
   كافة مسارات محرك بايثون تبدأ بـ `/v1/`. تم إلغاء بادئة `/api/` من كافة استدعاءات .NET.
3. **حقل الـ `overview` في الملخص إلزامي وغير قابل للحذف:**  
   بايثون يرسل حقل `overview` كـ String إلزامي دائماً، ودوت نت يتحقق من وجوده قبل الحفظ.
4. **أمان الـ JWT موحد بـ `HS256`:**  
   يتم التحقق من الـ Token المرسل في ترويسة `Authorization: Bearer <token>` بنفس المفتاح السري `JWT_SECRET`.

---

## 🌐 جدول المسارات المعتمدة رسمياً (The Frozen Routes Matrix)

> [!CAUTION]
> **لفريق .NET:** اضبط `BaseUrl` في `appsettings.json` ليكون `http://localhost:8000`، واستخدم المسارات التالية **بالضبط كما هي**:

| # | الميزة (Feature) | طريقة الطلب | المسار المعتمد رسمياً (Canonical Path) | الصلاحية (Role) | نوع الرد المتوقع |
| :---: | :--- | :---: | :--- | :---: | :---: |
| **1** | **توليد الكويز (Quiz)** | `POST` | `/v1/admin/lessons/{lessonId}/generate-quiz` | `Admin` | JSON (Quiz DTO) |
| **2** | **توليد الملخص (Summary)** | `POST` | `/v1/admin/lessons/{lessonId}/generate-summary` | `Admin` | JSON (Summary DTO) |
| **3** | **بث البحث اللحظي (SSE)** | `POST` | `/v1/search/stream` | `Student` / `Admin` | `text/event-stream` |
| **4** | **تسجيل تقييم الطالب (Feedback)** | `POST` | `/v1/search/feedback` | `Student` / `Admin` | JSON (Status 200) |
| **5** | **إحصائيات الجودة للإدارة** | `GET` | `/v1/admin/feedback` | `Admin` / `Teacher` | JSON (Analytics) |
| **6** | **بدء معالجة فيديو (Ingest)** | `POST` | `/v1/ingest/audio` | `Admin` | JSON (Status 200) |
| **7** | **باعث تحديث الدروس (Webhook)** | `POST` | `/v1/webhooks/lesson-updated` | `X-Service-Token` | JSON (Status 202) |
| **8** | **متابعة المعالجة (Ingest SSE)** | `GET` | `/v1/ingest/events/{sessionId}` | Public / Token | `text/event-stream` |

---

## 1. عقد توليد الاختبارات الذكية (Quiz Generation Contract)

### 1.1 الاستدعاء من .NET Client
* **المسار:** `POST http://localhost:8000/v1/admin/lessons/{lessonId}/generate-quiz`
* **الترويسة (Headers):**
  - `Authorization: Bearer <ADMIN_JWT_TOKEN>`
  - `Content-Type: application/json`

### 1.2 الـ JSON الصادر من بايثون (Standard Response Payload)
```json
{
  "lesson_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "generated_at": "2026-09-14T15:30:00Z",
  "questions": [
    {
      "id": 1,
      "question": "ما هي الخطوة الأولى لإعداد موديول الـ POS في نظام Dynamic Pro؟",
      "options": [
        { "id": "a", "text": "تحديد طابعة الفواتير وإعدادات الصندوق" },
        { "id": "b", "text": "إلغاء القيود المحاسبية لليوم السابق" },
        { "id": "c", "text": "تعديل صلاحيات المدير العام" },
        { "id": "d", "text": "إغلاق المخزن الرئيسي مؤقتاً" }
      ],
      "correct_answer_id": "a",
      "explanation": "يجب أولاً ربط الصندوق وتعيين طابعة الفواتير قبل بدء عمليات البيع."
    }
  ]
}
```

### 1.3 كود C# النهائي لملف `PythonAiDtos.cs` (انسخ هذا الكود في .NET)
```csharp
namespace LearnDynamicPro.Application.Dtos.Internal;

using System.Text.Json.Serialization;

public class GeneratedQuizDto
{
    [JsonPropertyName("lesson_id")]
    public string LessonId { get; set; } = string.Empty;

    [JsonPropertyName("generated_at")]
    public DateTime GeneratedAt { get; set; }

    [JsonPropertyName("questions")]
    public List<QuizQuestionDto> Questions { get; set; } = new();
}

public class QuizQuestionDto
{
    [JsonPropertyName("id")]
    public int QuestionNumber { get; set; }

    [JsonPropertyName("question")]
    public string QuestionText { get; set; } = string.Empty;

    [JsonPropertyName("options")]
    public List<QuizOptionDto> Options { get; set; } = new();

    [JsonPropertyName("correct_answer_id")]
    public string CorrectAnswerId { get; set; } = string.Empty;

    [JsonPropertyName("explanation")]
    public string Explanation { get; set; } = string.Empty;
}

public class QuizOptionDto
{
    [JsonPropertyName("id")]
    public string OptionId { get; set; } = string.Empty;

    [JsonPropertyName("text")]
    public string Text { get; set; } = string.Empty;
}
```

---

## 2. عقد توليد الملخصات (Summary Generation Contract)

### 2.1 الاستدعاء من .NET Client
* **المسار:** `POST http://localhost:8000/v1/admin/lessons/{lessonId}/generate-summary`
* **الترويسة (Headers):**
  - `Authorization: Bearer <ADMIN_JWT_TOKEN>`
  - `Content-Type: application/json`

### 2.2 الـ JSON الصادر من بايثون (مع حقل `overview` الإلزامي)
```json
{
  "lesson_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "overview": "يقدم هذا الدرس شرحاً تطبيقياً شاملاً لخطوات تفعيل موديول نقاط البيع (POS) وربطه مع المخازن وشاشات الحسابات العامة، مع استعراض صلاحيات الكاشير وإدارة الورديات اليومية.",
  "generated_at": "2026-09-14T15:35:00Z",
  "topics": [
    {
      "title": "إعدادات الصندوق والورديات",
      "points": [
        "افتح شاشة إعدادات الـ POS من قائمة المبيعات.",
        "حدد رقم الوردية وقم بربطها بالمستخدم الحالي.",
        "تحقق من رصيد بداية اليوم قبل تسجيل أول فاتورة."
      ]
    },
    {
      "title": "إتمام عمليات البيع والربط المخزني",
      "points": [
        "اختر الأصناف عبر قارئ الباركود أو شاشة اللمس.",
        "اضغط على زر الدفع النقدي أو عبر البطاقة الائتمانية.",
        "يقوم النظام تلقائياً بخصم الكميات من مخزن الفرع وإنشاء قيد اليومية."
      ]
    }
  ]
}
```

### 2.3 كود C# النهائي لملف `GeneratedSummaryDto.cs` (انسخ هذا الكود في .NET)
```csharp
namespace LearnDynamicPro.Application.Dtos.Internal;

using System.Text.Json.Serialization;

public class GeneratedSummaryDto
{
    [JsonPropertyName("lesson_id")]
    public string LessonId { get; set; } = string.Empty;

    [JsonPropertyName("overview")]
    public string Overview { get; set; } = string.Empty;

    [JsonPropertyName("generated_at")]
    public DateTime GeneratedAt { get; set; }

    [JsonPropertyName("topics")]
    public List<SummaryTopicDto> Topics { get; set; } = new();
}

public class SummaryTopicDto
{
    [JsonPropertyName("title")]
    public string Title { get; set; } = string.Empty;

    [JsonPropertyName("points")]
    public List<string> Points { get; set; } = new();
}
```

---

## 3. عقد باعث الـ Webhook الموحد (Lesson Sync Webhook)

### 3.1 الاستدعاء من .NET `WebhookDispatcher.cs`
* **المسار:** `POST http://localhost:8000/v1/webhooks/lesson-updated`
* **الترويسة (Headers):**
  - `X-Service-Token: <SHARED_SERVICE_TOKEN>`
  - `Content-Type: application/json`

### 3.2 جسم الطلب المعتمد حصراً (Payload)
```json
{
  "lesson_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "action": "Updated"
}
```
*(ملاحظة: قيم الـ `action` المعتمدة هي `"Updated"` أو `"Deleted"` فقط).*

### 3.3 تصرف محرك بايثون فور الاستلام:
* **الرد اللحظي:** `202 Accepted`
* **في حالة `Updated`:** يقوم بايثون في الخلفية بمسح الكاش، مسح متجهات Qdrant القديمة، استدعاء سياق الدرس من .NET، وتشغيل الـ Ingestion.
* **في حالة `Deleted`:** يمسح بايثون الكاش ومتجهات الدرس من Qdrant فوراً.

---

## 4. أمان الـ JWT والـ RBAC

### 4.1 إعدادات التوكن
* **الخوارزمية:** `HS256` حصراً.
* **المفتاح:** موحد بين `JWT_SECRET` في بيئة بايثون و `appsettings.json` في .NET.

### 4.2 أسماء الـ Claims المطلوبة في التوكن الصادر من .NET:
```csharp
new Claim("Id", user.Id.ToString()),
new Claim("Role", user.Role), // "Admin" or "Student"
new Claim("CompanyId", user.CompanyId.ToString()),
new Claim("DepartmentId", user.DepartmentId?.ToString() ?? "")
```

---

## 5. محرك البحث الذكي المباشر (Search SSE Protocol)

### 5.1 الاستدعاء (من Angular Client)
* **المسار:** `POST http://localhost:8000/v1/search/stream`
* **الترويسة:**
  - `Authorization: Bearer <JWT_TOKEN>`
  - `Accept: text/event-stream`
  - `Content-Type: application/json`

### 5.2 جسم الطلب (Payload)
```json
{
  "query": "كيف أقوم بتعديل صلاحيات الكاشير على شاشة الـ POS؟",
  "lesson_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "scope": "lesson",
  "thread_id": "optional-thread-uuid"
}
```

### 5.3 تتابع أحداث الـ SSE المعتمد:
1. `event: sources` ➔ يعيد مصفوفة مصادر الفيديو والطوابع الزمنية أولاً (لعرضها فوراً في الـ UI).
2. `event: token` ➔ يتدفق فيه نص الإجابة حرفياً كلمة بكلمة.
3. `: heartbeat` ➔ تعليق يرسله الخادم كل 15 ثانية صمت لمنع إغلاق الاتصال.
4. `event: done` ➔ حدث النهاية متضمناً مؤشرات الأداء والـ latency.

---

## 6. محرك تسجيل تقييمات الطلاب (Student Feedback API)

* **المسار:** `POST http://localhost:8000/v1/search/feedback`
* **الترويسة:** `Authorization: Bearer <JWT>`
* **جسم الطلب:**
```json
{
  "query": "كيف أقوم بتعديل صلاحيات الكاشير؟",
  "answer": "توجه إلى شاشة الإعدادات واختر الصلاحيات...",
  "rating": "up", // أو "down"
  "comment": "شرح ممتاز ومباشر",
  "lesson_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "thread_id": "optional-thread-uuid",
  "sources": []
}
```
* **الرد (200 OK):** `{"status": "success", "message": "تم تسجيل تقييمك بنجاح. 🎓"}`

---

## 7. لوحة تحليلات المشرف و Ragas (Admin Feedback & Quality)

* **المسار:** `GET http://localhost:8000/v1/admin/feedback`
* **الصلاحية:** `Admin` أو `Teacher`
* **البارامترات:**
  - `lesson_id` (اختياري)
  - `rating` (`UP` أو `DOWN`)
  - `format` (`json` للوحة التحكم، أو `ragas` لتصدير الـ Golden Dataset)
  - `limit` (افتراضي 50)
  - `offset` (افتراضي 0)

---

## 📋 الأوامر التنفيذية الصارمة للفرق (Action Checklist)

### 👨‍💻 فريق .NET Backend (`DynamicProLearn`):
1. في ملف `PythonAiClient.cs`: عدل المسارات لتكون `/v1/admin/lessons/{id}/generate-quiz` و `/v1/admin/lessons/{id}/generate-summary`.
2. في ملف `PythonAiDtos.cs`: انسخ كود الـ C# DTOs الموضح في القسم 1.3 والقسم 2.3 كاملاً.
3. في ملف `LessonAiService.cs`: تأكد من قراءة `generatedSummary.Overview` وحفظها في جدول الدروس.
4. في ملف `WebhookDispatcher.cs`: أرسل الـ Payload بصيغة `{"lesson_id": "...", "action": "Updated"}` لمسار `/v1/webhooks/lesson-updated`.

### 🎨 فريق Angular Frontend (`DynamicProLearn.Client`):
1. **شاشة الدرس (Student Lesson Detail):** إضافة تبويبين: تبويب "الاختبار (Quiz)" وتبويب "الملخص (Summary)" وعرض المحتوى المحفوظ في SQL Server عبر .NET.
2. **مكون الشات الذكي (Copilot Chat Widget):** استدعاء `POST /v1/search/stream` وقراءة أحداث الـ SSE (`sources` أولاً، ثم `token`، ثم `done`).
3. **أزرار التقييم (Feedback):** إضافة زري إبهام (👍 / 👎) بجوار إجابة الذكاء الاصطناعي يستدعيان `POST /v1/search/feedback`.
4. **أزرار المشرف (Admin Lesson Editor):** وضع زر "توليد اختبار ذكي" وزر "توليد ملخص تلقائي" يستدعيان الـ APIs في دوت نت.

### 🐍 فريق بايثون (`LMS_CO_Pilot`):
- [x] تم تجهيز واختبار الـ DTOs والـ Schemas وحقل `overview`.
- [x] تم تأمين المسارات وضبط التسامح في الـ Webhooks والـ JWT Claims.
- [x] النظام جاهز للعمل الفوري واستقبال طلبات .NET و Angular.
