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

# 6. Real-time Streaming Latency Telemetry (TTFT & TPOT)
STREAMING_TTFT = Histogram(
    "lms_ttft_seconds",
    "Time to First Token (TTFT) in seconds for SSE search stream",
    buckets=(0.05, 0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0),
)

STREAMING_TPOT = Histogram(
    "lms_tpot_seconds",
    "Time Per Output Token (TPOT) in seconds for SSE search stream",
    buckets=(0.005, 0.01, 0.02, 0.03, 0.05, 0.08, 0.1, 0.15, 0.25),
)

# 7. Security Guardrail & Injection Refusals
GUARDRAIL_REFUSALS = Counter(
    "lms_guardrail_refusals_total",
    "Total security guardrail refusals and policy violations blocked",
    labelnames=["reason"],  # "security_violation" | "prompt_injection" | "out_of_scope"
)

# 8. Lifespan Startup & Warmup Latency
LMS_STARTUP_DURATION = Gauge(
    "lms_startup_duration_seconds",
    "Total startup and model warmup duration in seconds",
)

# 9. AI Content Generation Latency (Quiz & Summary)
LMS_CONTENT_GENERATION_DURATION = Histogram(
    "lms_content_generation_duration_seconds",
    "Latency of AI content generation (quiz, summary) in seconds",
    labelnames=["type", "action"],  # type: "quiz" | "summary", action: "generate" | "regenerate"
    buckets=(0.5, 1.0, 2.0, 3.5, 5.0, 8.0, 12.0, 20.0, 30.0),
)


# ─── Recording Helpers ────────────────────────────────────────────────────────

def record_cache_lookup(hit: bool) -> None:
    """Records a Semantic Cache hit or miss."""
    CACHE_REQUESTS.labels(result="hit" if hit else "miss").inc()


def record_exact_cache_lookup(hit: bool) -> None:
    """Records an Exact Cache hit or miss."""
    EXACT_CACHE_REQUESTS.labels(result="hit" if hit else "miss").inc()


def record_intent_routing(intent: str) -> None:
    """Records an intent classification result from Fast Ingress."""
    INTENT_REQUESTS.labels(intent=intent.lower()).inc()


record_intent_classified = record_intent_routing


def record_cache_rbac_rejection(tier: str = "semantic") -> None:
    """Records a cache lookup rejected due to lack of course/lesson RBAC permissions."""
    CACHE_RBAC_REJECTIONS.labels(tier=tier.lower()).inc()


def record_stage_duration(stage: str, duration_seconds: float) -> None:
    """Records duration of a specific RAG pipeline stage in seconds."""
    RAG_STAGE_DURATION.labels(stage=stage).observe(duration_seconds)


def record_token_usage(prompt_tokens: int = 0, completion_tokens: int = 0, total_tokens: int = 0) -> None:
    """Records LLM token consumption by type."""
    if prompt_tokens > 0:
        LLM_TOKENS.labels(type="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        LLM_TOKENS.labels(type="completion").inc(completion_tokens)
    if total_tokens > 0:
        LLM_TOKENS.labels(type="total").inc(total_tokens)


def record_search_feedback(rating: str) -> None:
    """Records student feedback for search answer (up or down)."""
    SEARCH_FEEDBACK_TOTAL.labels(rating=rating.lower()).inc()


def record_streaming_ttft(ttft_seconds: float) -> None:
    """Records Time to First Token (TTFT) in seconds."""
    if ttft_seconds >= 0:
        STREAMING_TTFT.observe(ttft_seconds)


def record_streaming_tpot(tpot_seconds: float) -> None:
    """Records Time Per Output Token (TPOT) in seconds."""
    if tpot_seconds >= 0:
        STREAMING_TPOT.observe(tpot_seconds)


def record_guardrail_refusal(reason: str = "security_violation") -> None:
    """Records a security guardrail refusal event."""
    GUARDRAIL_REFUSALS.labels(reason=reason.lower()).inc()


def record_startup_duration(duration_seconds: float) -> None:
    """Records total startup and model warmup duration in seconds."""
    if duration_seconds >= 0:
        LMS_STARTUP_DURATION.set(duration_seconds)


def record_content_generation_duration(content_type: str, action: str, duration_seconds: float) -> None:
    """Records execution duration for AI content generation (quiz or summary)."""
    if duration_seconds >= 0:
        LMS_CONTENT_GENERATION_DURATION.labels(type=content_type.lower(), action=action.lower()).observe(duration_seconds)


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

    # Pre-initialize baseline label sets and Gauge so Prometheus and Grafana display baseline series immediately
    ACTIVE_REQUESTS.set(0)

    for res in ["hit", "miss"]:
        CACHE_REQUESTS.labels(result=res)
        EXACT_CACHE_REQUESTS.labels(result=res)
    for intent in ["greeting", "out_of_scope", "rag_query", "invalid_query"]:
        INTENT_REQUESTS.labels(intent=intent)
    for tier in ["exact", "semantic"]:
        CACHE_RBAC_REJECTIONS.labels(tier=tier)
    for reason in ["security_violation", "prompt_injection", "out_of_scope"]:
        GUARDRAIL_REFUSALS.labels(reason=reason)
    for rating in ["up", "down"]:
        SEARCH_FEEDBACK_TOTAL.labels(rating=rating)
    for token_t in ["prompt", "completion", "total"]:
        LLM_TOKENS.labels(type=token_t)
    for content_t in ["quiz", "summary"]:
        for act in ["generate", "regenerate"]:
            LMS_CONTENT_GENERATION_DURATION.labels(type=content_t, action=act)
    for stage in ["exact_cache", "intent_router", "cache_lookup", "embedding", "vector_search", "reranking", "gemini_generation", "total"]:
        RAG_STAGE_DURATION.labels(stage=stage)

    logger.info("Prometheus metrics initialized with baseline series ✅", endpoint=settings.METRICS_PATH)
    return instrumentator
