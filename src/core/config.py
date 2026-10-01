from typing import Any
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "LMS_CO_Pilot"
    ENVIRONMENT: str = "development"

    @field_validator(
        "DATABASE_URL",
        "QDRANT_URL",
        "LMS_BASE_URL",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "JWT_SECRET",
        "SERVICE_TOKEN",
        mode="before",
        check_fields=False
    )
    @classmethod
    def strip_quotes_and_whitespace(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip("\"' ")
        return v

    
    # مفاتيح الـ API ستُقرأ تلقائياً من ملف .env (Best Practice)
    GROQ_API_KEY: str
    GEMINI_API_KEY: str
    GEMINI_MODEL: str = "gemini-3.5-flash-lite"  # Unified model name for all services

    # قاعدة البيانات PostgreSQL
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/lms_co_pilot"

    # LMS Backend & JWT Security
    LMS_BASE_URL: str = "http://localhost:8080"
    SERVICE_TOKEN: str = "change-this-in-env-file"
    LMS_WEBHOOK_SECRET: str = "default_webhook_secret_key_2026"
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

    # Search & Retrieval Optimization
    QDRANT_SEARCH_CANDIDATES_LIMIT: int = 5  # عدد المرشحين المسترجعين للـ Reranker (الأمثل لتقليص زمن الـ CPU)

    # Exact In-Memory Cache Configuration (Tier-1)
    EXACT_CACHE_ENABLED: bool = True
    EXACT_CACHE_MAX_SIZE: int = 10000
    EXACT_CACHE_TTL_SECONDS: int = 3600  # 1 hour in-memory TTL

    # Semantic Vector Cache Configuration (Tier-2)
    SEMANTIC_CACHE_ENABLED: bool = True
    SEMANTIC_CACHE_COLLECTION: str = "semantic_cache"
    SEMANTIC_CACHE_THRESHOLD: float = 0.95  # Cosine similarity threshold (0.95 prevents false positives)
    SEMANTIC_CACHE_TTL_DAYS: int = 7       # Cache expiration in days
    SEMANTIC_CACHE_MAX_POINTS: int = 100000  # Upper threshold for vector collection capacity
    CACHE_EVICTION_INTERVAL_HOURS: int = 24  # Periodic eviction background task interval

    # Fast Ingress Intent Router Configuration
    INTENT_ROUTER_ENABLED: bool = True

    # Reranker Engine Configuration (Quantized ONNX via FlashRank)
    RERANKER_MODEL_NAME: str = "miniReranker_arabic_v1"
    RERANKER_CACHE_DIR: str = "./.model_cache"

    # Rate Limiting Control
    RATE_LIMIT_ENABLED: bool = True

    # Standalone / Load Testing Controls
    MOCK_LMS: bool = False

    # Observability & Metrics (Prometheus)
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"
    SEARCH_DEBUG_ENABLED: bool = False  # Set to True only for offline diagnostic traces

    # CORS Allowed Origins
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:4200",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:4200",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
    ]

    # Trusted Host Security
    ALLOWED_HOSTS: list[str] = [
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
        "*.egydynamic.com",
        "testserver",
    ]

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()