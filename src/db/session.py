# src/db/session.py
import asyncio
import json
import time
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

# جدول تسجيل تقييمات الطلاب للإجابات (M07 Feedback Engine)
CREATE_FEEDBACK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS search_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    department_id VARCHAR(64),
    user_id VARCHAR(64) NOT NULL,
    user_role VARCHAR(32) NOT NULL DEFAULT 'Student',
    lesson_id VARCHAR(128),
    thread_id VARCHAR(128),
    query_hash VARCHAR(64) NOT NULL,
    answer_hash VARCHAR(64) NOT NULL,
    query_text TEXT NOT NULL,
    answer_text TEXT NOT NULL,
    rating VARCHAR(10) NOT NULL,
    comment TEXT,
    sources JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_user_query_answer_feedback UNIQUE (user_id, query_hash, answer_hash)
);

CREATE INDEX IF NOT EXISTS idx_search_feedback_tenant_lesson 
    ON search_feedback(tenant_id, lesson_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_feedback_tenant_rating 
    ON search_feedback(tenant_id, rating, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_search_feedback_created_at 
    ON search_feedback(created_at DESC);
"""

# جدول تدقيق قرارات التوجيه الذكي لشاشات الـ ERP (ذاكرة القرارات + أدوار الأزرار)
CREATE_ERP_AUDIT_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS erp_routing_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    query_text TEXT,
    screen_id VARCHAR(128),
    fingerprint VARCHAR(64) NOT NULL,
    intent VARCHAR(16),
    source VARCHAR(16) NOT NULL,
    decision JSONB NOT NULL DEFAULT '{}'::jsonb,
    outcome VARCHAR(16) NOT NULL DEFAULT 'pending',
    matched_point_id VARCHAR(64),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_erp_routing_audit_lookup
    ON erp_routing_audit(tenant_id, kind, screen_id, fingerprint, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_erp_routing_audit_tenant_time
    ON erp_routing_audit(tenant_id, created_at DESC);
"""

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    استخدام Lifespan Context Manager بدلاً من @app.on_event القديم.
    يضمن تهيئة الـ Pool مرة واحدة وإغلاقه بأمان حتى لو حدث Crash.
    """
    app.state.is_ready = False
    t_startup = time.time()

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
        await conn.execute(CREATE_FEEDBACK_TABLE_SQL)
        await conn.execute(CREATE_ERP_AUDIT_TABLE_SQL)
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

    # ⑩ تهيئة Feedback Service (M07 Feedback Engine)
    from src.services.feedback_service import feedback_service
    feedback_service.initialize(app.state.db_pool)
    app.state.feedback_service = feedback_service

    # ⑪ تهيئة ERP Service (DynamicPro Smart Assistant)
    from src.services.erp_service import erp_service
    erp_service.initialize()
    app.state.erp_service = erp_service

    # ⑪.1 تهيئة ذاكرة قرارات التوجيه (Qdrant للبحث + PostgreSQL للتدقيق)
    from src.services.erp_decision_memory_service import erp_decision_memory_service
    try:
        await erp_decision_memory_service.initialize(app.state.db_pool)
    except Exception as e:
        logger.error("ERP decision memory initialization failed; routing continues without memory", error=str(e))
    app.state.erp_decision_memory_service = erp_decision_memory_service

    # تم اكتمال كافة النماذج والخدمات وجاهزية النظام للاستقبال
    startup_duration = round(time.time() - t_startup, 3)
    app.state.startup_duration = startup_duration
    app.state.is_ready = True
    from src.core.metrics import record_startup_duration
    record_startup_duration(startup_duration)
    logger.info("All AI Engine services initialized & ready 🚀", startup_duration_seconds=startup_duration)

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

