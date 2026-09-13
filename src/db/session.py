# src/db/session.py
import asyncio
import json
from contextlib import asynccontextmanager
import asyncpg
from fastapi import FastAPI
import structlog
from src.core.config import settings

logger = structlog.get_logger()

async def _periodic_semantic_cache_eviction(interval_hours: int):
    """Periodically cleans up expired semantic cache points in Qdrant."""
    from src.services.semantic_cache_service import semantic_cache_service
    interval_seconds = max(interval_hours * 3600, 60)
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            evicted = await semantic_cache_service.evict_expired_entries()
            if evicted > 0:
                logger.info("Periodic cache eviction completed", evicted_count=evicted)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning("Periodic cache eviction encountered error", error=str(e))

async def init_connection(conn: asyncpg.Connection):
    """
    تسجيل Type Codec تلقائي لـ JSONB على مستوى الاتصال:
    يسمح بإدخال Python dict مباشرة دون json.dumps
    ويقوم باسترجاع حقول الـ JSONB كـ dict تلقائياً دون json.loads
    """
    await conn.set_type_codec(
        'jsonb',
        encoder=json.dumps,
        decoder=json.loads,
        schema='pg_catalog'
    )

# الـ SQL الذي ينشئ جدول سجل الأحداث إذا لم يكن موجوداً
# IF NOT EXISTS: يضمن أننا لن نحصل على خطأ إذا شغّلنا التطبيق مرتين
CREATE_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS agent_event_log (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id VARCHAR(100) NOT NULL,
    agent_name VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}',
    timestamp TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_event_log_session_id 
    ON agent_event_log(session_id, timestamp DESC);
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    استخدام Lifespan Context Manager بدلاً من @app.on_event القديم.
    يضمن تهيئة الـ Pool مرة واحدة وإغلاقه بأمان حتى لو حدث Crash.
    """
    # ① تهيئة قاعدة البيانات
    logger.info("Database pool initializing...")
    app.state.db_pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=5,
        max_size=20,
        timeout=30.0,
        init=init_connection
    )
    async with app.state.db_pool.acquire() as conn:
        await conn.execute(CREATE_EVENTS_TABLE_SQL)
    logger.info("Database pool ready ✅")

    # ② تحميل نماذج الـ Embedding مرة واحدة عند بدء التشغيل
    # (Best Practice 2026: initialize inside lifespan → stored in app.state)
    from src.services.embedding_service import embedding_service
    await embedding_service.initialize()
    app.state.embedding_service = embedding_service
    logger.info("Embedding service ready ✅")

    # ③ تحميل نموذج الـ Reranker مرة واحدة عند بدء التشغيل
    from src.services.reranker_service import reranker_service
    await reranker_service.initialize()
    app.state.reranker_service = reranker_service
    logger.info("Reranker service ready ✅")

    # ④ تهيئة Qdrant Service
    from src.services.qdrant_service import qdrant_service
    await qdrant_service.initialize()
    app.state.qdrant_service = qdrant_service
    logger.info("Qdrant service ready ✅")

    # ④.1 تهيئة Exact In-Memory Cache Service (Tier-1)
    from src.services.exact_cache_service import exact_cache_service
    exact_cache_service.initialize()
    app.state.exact_cache_service = exact_cache_service

    # ④.2 تهيئة Semantic Cache Service (Tier-2)
    from src.services.semantic_cache_service import semantic_cache_service
    await semantic_cache_service.initialize()
    app.state.semantic_cache_service = semantic_cache_service
    logger.info("Semantic cache service ready ✅")

    # تشغيل مهمة التنظيف الدوري للمتجهات المنتهية في الكاش الدلالي (Background Task)
    eviction_task = asyncio.create_task(
        _periodic_semantic_cache_eviction(settings.CACHE_EVICTION_INTERVAL_HOURS)
    )

    # ④.3 تهيئة Fast Ingress Intent Router
    from src.services.intent_router import intent_router
    intent_router.initialize()
    app.state.intent_router = intent_router

    # ⑤ تهيئة Search Service (Gemini client for RAG answers)
    from src.services.search_service import search_service
    search_service.initialize()
    app.state.search_service = search_service
    logger.info("Search service ready ✅")

    # ⑥ تهيئة LMS Client (للاتصال بـ .NET ERP)
    from src.services.lms_client import lms_client_service
    lms_client_service.initialize()
    app.state.lms_client_service = lms_client_service

    # ⑦ تهيئة Auth Validator Service
    from src.services.auth_service import auth_validator_service
    auth_validator_service.initialize()
    app.state.auth_validator_service = auth_validator_service

    # ⑧ تهيئة Agent Service (LangGraph Checkpointer)
    from src.agents.base_agent import agent_service
    await agent_service.initialize()
    app.state.agent_service = agent_service
    
    # ⑨ تهيئة Event Logger Service
    from src.services.event_logger import event_logger_service
    event_logger_service.initialize(app.state.db_pool)
    app.state.event_logger_service = event_logger_service

    yield  # ← التطبيق يعمل هنا ويستقبل الطلبات

    # ③ إغلاق الموارد عند إيقاف السيرفر
    eviction_task.cancel()
    try:
        await eviction_task
    except asyncio.CancelledError:
        pass

    exact_cache_service.close()
    intent_router.close()

    await app.state.db_pool.close()
    logger.info("Database pool closed gracefully 🛑")
    
    await qdrant_service.close()
    logger.info("Qdrant connection closed 🛑")
    
    await lms_client_service.close()
    logger.info("LMS Client closed 🛑")
    
    await agent_service.close()
    logger.info("Agent Service (LangGraph Pool) closed 🛑")

