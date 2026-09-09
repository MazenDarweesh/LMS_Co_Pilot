"""
LMS AI Co-Pilot — Live Observability & Metrics Engine
=====================================================
Integrates Prometheus client & prometheus-fastapi-instrumentator to expose
standard HTTP metrics (RPS, latency percentiles, error rates) and custom
domain metrics (Semantic Cache hit rate, RAG stage latency, token consumption).
"""

from typing import Literal
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

# 2. RAG Pipeline Latency Breakdown
RAG_STAGE_DURATION = Histogram(
    "lms_rag_stage_duration_seconds",
    "Latency per RAG pipeline stage in seconds",
    labelnames=["stage"],  # "cache_lookup", "embedding", "vector_search", "reranking", "gemini_generation", "total"
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
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


# ─── Recording Helpers ────────────────────────────────────────────────────────

def record_cache_lookup(hit: bool) -> None:
    """Records a Semantic Cache hit or miss."""
    result = "hit" if hit else "miss"
    CACHE_REQUESTS.labels(result=result).inc()


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
