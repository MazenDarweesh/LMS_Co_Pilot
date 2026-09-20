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
    record_streaming_ttft,
    record_streaming_tpot,
    record_guardrail_refusal,
    record_startup_duration,
    record_content_generation_duration,
    record_video_ingestion_stage,
    record_video_ingestion_completed,
    record_video_ingestion_failed,
    set_video_ingestion_in_flight,
    CACHE_REQUESTS,
    RAG_STAGE_DURATION,
    LLM_TOKENS,
    STREAMING_TTFT,
    STREAMING_TPOT,
    GUARDRAIL_REFUSALS,
    LMS_STARTUP_DURATION,
    LMS_CONTENT_GENERATION_DURATION,
    VIDEO_INGESTION_TOTAL,
    VIDEO_INGESTION_DURATION,
    VIDEO_INGESTION_STAGE_DURATION,
    VIDEO_INGESTION_CHUNKS_TOTAL,
    VIDEO_INGESTION_IN_FLIGHT,
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

    # 4. Streaming TTFT & TPOT
    initial_ttft_sum = STREAMING_TTFT._sum.get()
    record_streaming_ttft(0.35)
    assert STREAMING_TTFT._sum.get() >= initial_ttft_sum + 0.35

    initial_tpot_sum = STREAMING_TPOT._sum.get()
    record_streaming_tpot(0.025)
    assert STREAMING_TPOT._sum.get() >= initial_tpot_sum + 0.025

    # 5. Guardrail Refusals
    initial_refusals = GUARDRAIL_REFUSALS.labels(reason="security_violation")._value.get()
    record_guardrail_refusal("security_violation")
    assert GUARDRAIL_REFUSALS.labels(reason="security_violation")._value.get() == initial_refusals + 1

    # 6. Exposition text validation
    text = generate_latest().decode("utf-8")
    assert "lms_cache_requests_total" in text
    assert "lms_rag_stage_duration_seconds" in text
    assert "lms_llm_tokens_total" in text
    assert "lms_ttft_seconds" in text
    assert "lms_tpot_seconds" in text
    assert "lms_guardrail_refusals_total" in text


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


def test_startup_and_content_metrics():
    """Verify startup gauge and content generation histogram recording helpers."""
    record_startup_duration(4.25)
    assert LMS_STARTUP_DURATION._value.get() == 4.25

    init_sum = LMS_CONTENT_GENERATION_DURATION.labels(type="quiz", action="generate")._sum.get()
    record_content_generation_duration("quiz", "generate", 1.85)
    assert LMS_CONTENT_GENERATION_DURATION.labels(type="quiz", action="generate")._sum.get() >= init_sum + 1.85


@pytest.mark.asyncio
async def test_readiness_probe_endpoints():
    """Verify /ready, /v1/ready, /api/ready return 503 when not ready, and 200 when ready."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://localhost",
    ) as client:
        # 1. Test unready state
        app.state.is_ready = False
        res_unready = await client.get("/ready")
        assert res_unready.status_code == 503
        assert res_unready.json()["ready"] is False

        # 2. Test ready state
        app.state.is_ready = True
        app.state.startup_duration = 3.5
        for endpoint in ["/ready", "/v1/ready", "/api/ready"]:
            res_ready = await client.get(endpoint)
            assert res_ready.status_code == 200
            data = res_ready.json()
            assert data["ready"] is True
            assert data["status"] == "ready"
            assert data["startup_duration_seconds"] == 3.5


def test_video_ingestion_metrics():
    """Verify video ingestion collectors and recording helpers."""
    # 1. In-flight gauge
    initial_in_flight = VIDEO_INGESTION_IN_FLIGHT._value.get()
    set_video_ingestion_in_flight(1)
    assert VIDEO_INGESTION_IN_FLIGHT._value.get() == initial_in_flight + 1
    set_video_ingestion_in_flight(-1)
    assert VIDEO_INGESTION_IN_FLIGHT._value.get() == initial_in_flight

    # 2. Stage duration
    initial_download = VIDEO_INGESTION_STAGE_DURATION.labels(stage="download")._sum.get()
    record_video_ingestion_stage("download", 3.2)
    assert VIDEO_INGESTION_STAGE_DURATION.labels(stage="download")._sum.get() >= initial_download + 3.2

    # 3. Success & chunks counter
    initial_success = VIDEO_INGESTION_TOTAL.labels(status="success")._value.get()
    initial_chunks = VIDEO_INGESTION_CHUNKS_TOTAL._value.get()
    record_video_ingestion_completed(duration_seconds=45.0, chunks_count=12)
    assert VIDEO_INGESTION_TOTAL.labels(status="success")._value.get() == initial_success + 1
    assert VIDEO_INGESTION_CHUNKS_TOTAL._value.get() == initial_chunks + 12

    # 4. Failure counter
    initial_failed = VIDEO_INGESTION_TOTAL.labels(status="failed")._value.get()
    record_video_ingestion_failed(duration_seconds=12.5)
    assert VIDEO_INGESTION_TOTAL.labels(status="failed")._value.get() == initial_failed + 1

