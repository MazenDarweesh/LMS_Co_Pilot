from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "LMS_CO_Pilot"
    ENVIRONMENT: str = "development"

    
    # مفاتيح الـ API ستُقرأ تلقائياً من ملف .env (Best Practice)
    GROQ_API_KEY: str
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"  # Unified model name for all services

    # قاعدة البيانات PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lms_co_pilot"

    # LMS Backend & JWT Security
    LMS_BASE_URL: str = "http://localhost:8080"
    SERVICE_TOKEN: str = "change-this-in-env-file"
    JWT_SECRET: str = "your-lms-jwt-secret-must-match-dotnet"
    JWT_ALGORITHM: str = "HS256"
    JWT_AUDIENCE: str | None = None
    JWT_ISSUER: str | None = None

    # Qdrant Vector Database
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION: str = "learning_content"

    # LangGraph Memory Management
    AGENT_MAX_HISTORY_MESSAGES: int = 6   # آخر 6 رسائل = 3 أسئلة + 3 إجابات
    AGENT_MAX_CONTEXT_TOKENS: int = 3000  # حد أقصى للـ Tokens المرسلة للموديل

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()