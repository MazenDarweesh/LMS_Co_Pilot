"""
LMS AI Co-Pilot — Live Observability & Metrics Engine
=====================================================
Integrates Prometheus client & prometheus-fastapi-instrumentator to expose
standard HTTP metrics (RPS, latency percentiles, error rates) and custom
domain metrics (Semantic Cache hit rate, RAG stage latency, token consumption).
"""

from fastapi import FastAPI
import structlog
from prometheus_client import Counter, Histogram, Gauge
from prometheus_fastapi_instrumentator import Instrumentator

from src.core.config import settings

logger = structlog.get_logger()

# ─── Custom Domain Prometheus Collectors ──────────────────────────────────────

# 1. Semantic Cache Metric (Hit vs Miss)
CACHE_REQUESTS = Counter(
    "lms_cache_requests_total",
    "Total count of semantic cache queries categorized by result",
    labelnames=["result"],  # "hit" | "miss"
)

# 1.1 Exact In-Memory Cache Metric (Hit vs Miss)
EXACT_CACHE_REQUESTS = Counter(
    "lms_exact_cache_requests_total",
    "Total count of exact in-memory cache lookups categorized by result",
    labelnames=["result"],  # "hit" | "miss"
)

# 1.2 Fast Ingress Intent Router Metric
INTENT_REQUESTS = Counter(
    "lms_intent_requests_total",
    "Total requests routed by the Fast Ingress Intent Router",
    labelnames=["intent"],  # "greeting" | "out_of_scope" | "rag_query" | "invalid_query"
)

# 1.3 Cache RBAC Rejection Metric
CACHE_RBAC_REJECTIONS = Counter(
    "lms_cache_rbac_rejections_total",
    "Total cache matches rejected due to student missing course permissions",
    labelnames=["tier"],  # "exact" | "semantic"
)

# 2. RAG Pipeline Latency Breakdown
RAG_STAGE_DURATION = Histogram(
    "lms_rag_stage_duration_seconds",
    "Latency per RAG pipeline stage in seconds",
    labelnames=["stage"],  # "exact_cache", "intent_router", "cache_lookup", "embedding", "vector_search", "reranking", "gemini_generation", "total"
    buckets=(0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# 3. LLM Token Consumption
LLM_TOKENS = Counter(
    "lms_llm_tokens_total",
    "Total token consumption for Gemini generative calls",
    labelnames=["type"],  # "prompt", "completion", "total"
)

# 4. In-Flight Active Requests
ACTIVE_REQUESTS = Gauge(
    "lms_active_requests",
    "Current number of concurrent in-flight requests in the AI engine",
)

# 5. Student Search Feedback
SEARCH_FEEDBACK_TOTAL = Counter(
    "lms_search_feedback_total",
    "Total student feedback ratings submitted on search answers",
    labelnames=["rating"],  # "up", "down"
)



# ─── Recording Helpers ────────────────────────────────────────────────────────

def record_cache_lookup(hit: bool) -> None:
    """Records a Semantic Cache hit or miss."""
    result = "hit" if hit else "miss"
    CACHE_REQUESTS.labels(result=result).inc()


def record_exact_cache_lookup(hit: bool) -> None:
    """Records an Exact In-Memory Cache hit or miss."""
    result = "hit" if hit else "miss"
    EXACT_CACHE_REQUESTS.labels(result=result).inc()


def record_intent_classified(intent: str) -> None:
    """Records an intent classification event."""
    INTENT_REQUESTS.labels(intent=intent.lower()).inc()


def record_cache_rbac_rejection(tier: str) -> None:
    """Records a cache lookup rejection caused by RBAC entitlement checks."""
    CACHE_RBAC_REJECTIONS.labels(tier=tier.lower()).inc()


def record_stage_duration(stage: str, duration_seconds: float) -> None:
    """Records execution duration for a specific RAG pipeline stage."""
    if duration_seconds >= 0:
        RAG_STAGE_DURATION.labels(stage=stage).observe(duration_seconds)


def record_token_usage(prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0) -> None:
    """Records LLM token consumption."""
    if prompt_tokens > 0:
        LLM_TOKENS.labels(type="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        LLM_TOKENS.labels(type="completion").inc(completion_tokens)
    if total_tokens > 0:
        LLM_TOKENS.labels(type="total").inc(total_tokens)
    elif prompt_tokens > 0 or completion_tokens > 0:
        LLM_TOKENS.labels(type="total").inc(prompt_tokens + completion_tokens)


def record_search_feedback(rating: str) -> None:
    """Records a student feedback rating event (UP or DOWN)."""
    SEARCH_FEEDBACK_TOTAL.labels(rating=rating.lower()).inc()


# ─── Instrumentator Initialization ────────────────────────────────────────────


def init_metrics(app: FastAPI) -> Instrumentator | None:
    """
    Hooks Prometheus ASGI instrumentation into the FastAPI application
    and exposes the /metrics scraping endpoint.
    """
    if not settings.METRICS_ENABLED:
        logger.info("Prometheus metrics disabled via configuration")
        return None

    excluded = [
        "/health",
        settings.METRICS_PATH,
        "/docs",
        "/redoc",
        "/openapi.json",
    ]

    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_round_latency_decimals=True,
        excluded_handlers=excluded,
    )

    # Instrument application and expose /metrics endpoint
    instrumentator.instrument(app).expose(
        app,
        endpoint=settings.METRICS_PATH,
        include_in_schema=True,
        tags=["Monitoring"],
    )

    logger.info("Prometheus metrics initialized ✅", endpoint=settings.METRICS_PATH)
    return instrumentator
