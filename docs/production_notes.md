# 🚀 مذكرات وبيانات نشر الإنتاج (Production Deployment Notes)

هذا الملف يحتوي على الملاحظات الحرجة والمعماريات الخاصة ببيئة الإنتاج الحقيقية (Production)، والتي يجب الالتزام بها لتفادي ثغرات الأداء أو مشاكل البنية التحتية.

---

## ⚠️ 1. ملاحظة إنتاجية: Reverse Proxies & Rate Limiting Gotcha

### 🔴 المشكلة (The Problem):
بالنسبة للـ **Rate Limiter** (`slowapi`):
الدالة المستخدمة `get_remote_address` تعتمد على قراءة الـ IP الخاص بالعميل المتصل بالخادم.
في بيئة الإنتاج، الخادم الخاص بك (FastAPI) غالباً ما سيعمل خلف موزع أحمال أو وسيط (Reverse Proxy) مثل:
* Nginx
* AWS Application Load Balancer (ALB)
* Traefik / Caddy

في هذه الحالة، فإن دالة `get_remote_address` ستقرأ **الـ IP الداخلي لـ Nginx** وليس الـ IP الحقيقي للمستخدم!
هذا يعني أن **جميع المستخدمين سيتم حظرهم معاً** لأن النظام سيعتبرهم جميعاً يأتون من نفس الـ IP (وهو Nginx).

### ✅ الحل المعياري (The Solution):
لحسن الحظ، **الكود لا يحتاج إلى أي تعديل**. 
الحل يكمن في طريقة تشغيل خادم `uvicorn` نفسه. يجب إخبار `uvicorn` بأنه يعمل خلف Proxy وأنه يجب عليه قراءة الـ IP الحقيقي من الـ Header الشهير `X-Forwarded-For`.

لتطبيق ذلك في الإنتاج، استخدم أحد هذين الأمرين عند تشغيل السيرفر:

**عن طريق الـ CLI:**
```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
```

**أو عن طريق Docker (Dockerfile CMD أو docker-compose.yml):**
```dockerfile
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
```
*(ملاحظة: يمكنك وضع الـ IP الخاص بـ Nginx بدلاً من `*` لزيادة الأمان).*

---

## ⚠️ 2. ملاحظة إنتاجية: Redis Multi-Worker Rate Limiting

### 🔴 المشكلة (The Problem):
الوضع الافتراضي لـ `slowapi` يخزن بيانات الحظر (Rate Limiting) في الذاكرة العشوائية الخاصة بالخادم (In-Memory).
إذا كنت تستخدم أكثر من Worker (مثلاً `--workers 4`)، فإن كل Worker سيكون له ذاكرة منفصلة، ولن يعرفوا متى يتجاوز المستخدم الحد المطلوب.

### ✅ الحل المعياري (The Solution):
في الإنتاج، افتح ملف `src/core/middleware.py` وقم بتفعيل رابط الـ Redis بدل الذاكرة:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

# استبدل هذا السطر:
# limiter = Limiter(key_func=get_remote_address)

# بهذا السطر (مع وضع رابط خادم Redis الخاص بك):
limiter = Limiter(
    key_func=get_remote_address, 
    storage_uri="redis://localhost:6379/0" 
)
```
