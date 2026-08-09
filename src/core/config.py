from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "LMS_CO_Pilot"
    ENVIRONMENT: str = "development"

    
    # مفاتيح الـ API ستُقرأ تلقائياً من ملف .env (Best Practice)
    GROQ_API_KEY: str
    GEMINI_API_KEY: str

    # قاعدة البيانات PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lms_co_pilot"

    # Qdrant Vector Database
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "lms_lessons"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()