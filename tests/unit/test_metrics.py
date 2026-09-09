"""
Unit Tests for Prometheus Metrics Engine
========================================
Validates that Prometheus metrics collectors, recording helpers,
and the /metrics exposition endpoint operate correctly without regressions.
"""

import pytest
from httpx import AsyncClient, ASGITransport
from prometheus_client import generate_latest

from src.main import app
from src.core.metrics import (
    record_cache_lookup,
    record_stage_duration,
    record_token_usage,
    CACHE_REQUESTS,
    RAG_STAGE_DURATION,
    LLM_TOKENS,
)


def test_custom_metric_recording_helpers():
    """Verify that domain metric recording helper functions update Prometheus collectors safely."""
    # 1. Semantic Cache Hit / Miss
    initial_hits = CACHE_REQUESTS.labels(result="hit")._value.get()
    initial_misses = CACHE_REQUESTS.labels(result="miss")._value.get()

    record_cache_lookup(hit=True)
    record_cache_lookup(hit=False)

    assert CACHE_REQUESTS.labels(result="hit")._value.get() == initial_hits + 1
    assert CACHE_REQUESTS.labels(result="miss")._value.get() == initial_misses + 1

    # 2. Stage Duration Histogram
    initial_sum = RAG_STAGE_DURATION.labels(stage="vector_search")._sum.get()
    record_stage_duration("vector_search", 0.05)
    assert RAG_STAGE_DURATION.labels(stage="vector_search")._sum.get() >= initial_sum + 0.05

    # 3. Token Consumption Counter
    initial_prompt = LLM_TOKENS.labels(type="prompt")._value.get()
    initial_comp = LLM_TOKENS.labels(type="completion")._value.get()
    initial_total = LLM_TOKENS.labels(type="total")._value.get()

    record_token_usage(prompt_tokens=120, completion_tokens=45, total_tokens=165)

    assert LLM_TOKENS.labels(type="prompt")._value.get() == initial_prompt + 120
    assert LLM_TOKENS.labels(type="completion")._value.get() == initial_comp + 45
    assert LLM_TOKENS.labels(type="total")._value.get() == initial_total + 165

    # 4. Exposition text validation
    text = generate_latest().decode("utf-8")
    assert "lms_cache_requests_total" in text
    assert "lms_rag_stage_duration_seconds" in text
    assert "lms_llm_tokens_total" in text


@pytest.mark.asyncio
async def test_metrics_endpoint_exposition():
    """Verify that GET /metrics returns HTTP 200 with Prometheus text format containing custom collectors."""
    # Use localhost to satisfy TrustedHostMiddleware
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers.get("content-type", "")

    body = response.text
    # Check that custom domain metrics exist in the scraped body
    assert "lms_cache_requests_total" in body
    assert "lms_rag_stage_duration_seconds" in body
    assert "lms_llm_tokens_total" in body
    assert "lms_active_requests" in body
