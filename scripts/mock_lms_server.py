import jwt
from fastapi import FastAPI, Depends, Header, HTTPException
from pydantic import BaseModel
import datetime

# نستورد الإعدادات من المشروع لتوحيد مفاتيح التشفير
from src.core.config import settings

app = FastAPI(title="Mock .NET LMS Server", description="يحاكي ردود خادم الـ ERP لاختبار الـ Co-Pilot")

# 1. مسار لتوليد توكن اختباري (JWT)
class TokenRequest(BaseModel):
    user_id: str = "user_777"
    role: str = "Student"
    company_id: str = "egy_dynamic"
    department_id: str = "dept_it"

@app.post("/generate-token")
def generate_token(req: TokenRequest):
    payload = {
        "Id": req.user_id,
        "Role": req.role,
        "CompanyId": req.company_id,
        "DepartmentId": req.department_id,
        "exp": datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=24)
    }
    
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE

    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return {"access_token": token, "instructions": "Copy this token and use it in Co-Pilot Swagger UI (Authorize button)"}

# 2. محاكاة مسار الصلاحيات (Internal Permissions Endpoint)
@app.get("/api/internal/user-permissions/{user_id}")
def get_user_permissions(user_id: str, authorization: str = Header(None)):
    expected_header = f"Bearer {settings.SERVICE_TOKEN}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Invalid Service Token")

    # نرد بالهيكل المتداخل (Nested) الذي اتفقنا عليه
    return {
        "userId": user_id,
        "accessibleModules": [
            {
                "moduleId": "mod_1",
                "levelFilters": ["beginner_guid", "intermediate_guid"],
                "typeFilters": ["video_lecture_guid"]
            }
        ],
        "accessibleUnitIds": ["unit_5"],
        "accessibleLessonIds": ["less_10"]
    }

# 3. محاكاة مسار تفاصيل الدرس للـ Webhook (Full Context)
@app.get("/api/internal/lessons/{lesson_id}/full-context")
def get_lesson_full_context(lesson_id: str, authorization: str = Header(None)):
    expected_header = f"Bearer {settings.SERVICE_TOKEN}"
    if authorization != expected_header:
        raise HTTPException(status_code=401, detail="Invalid Service Token")

    return {
        "lessonId": lesson_id,
        "videoUrl": "https://www.youtube.com/watch?v=J3-O2bE_yI4", # رابط عشوائي للاختبار
        "tenantIds": ["egy_dynamic", "company_x"],
        "moduleId": "mod_1",
        "unitId": "unit_5",
        "levelId": "beginner_guid",
        "typeId": "video_lecture_guid",
        "targetRoles": ["Student", "Admin"]
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Mock .NET LMS Server on http://127.0.0.1:8080")
    uvicorn.run(app, host="127.0.0.1", port=8080)
