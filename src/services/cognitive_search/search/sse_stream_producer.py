"""SSE Streaming Producer — Threaded Gemini Token Stream, Backpressure Queue, Heartbeat, and Cache Persistence."""
import asyncio
import json
import re
import threading
import time
import uuid
from typing import AsyncIterator
from fastapi import Request
from google import genai
from google.genai import types
import structlog

from src.core.config import settings
from src.core.metrics import (
    record_stage_duration,
    record_streaming_tpot,
    record_streaming_ttft,
    record_token_usage,
)
from src.core.prompts import get_rag_system_prompt
from src.models.auth_models import UserContext
from src.models.search_models import SearchRequest, SearchResponse, SourceItem
from src.services.cognitive_search.exact_cache_service import exact_cache_service
from src.services.cognitive_search.semantic_cache_service import semantic_cache_service

logger = structlog.get_logger()


def format_sse(event_type: str, data: dict) -> str:
    """Formats a payload dictionary into a standard, UTF-8 compliant SSE message."""
    payload = json.dumps(data, ensure_ascii=False)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event_type}\n{data_lines}\n\n"


async def stream_gemini_rag_tokens(
    gemini_client: genai.Client | None,
    req: SearchRequest,
    user_ctx: UserContext,
    request: Request,
    context_str: str,
    num_sources: int,
    is_multi_lesson: bool,
    sources: list[SourceItem],
    normalized_query: str,
    dense_vec: list[float],
    t0: float,
    background_tasks: set[asyncio.Task],
) -> AsyncIterator[str]:
    """
    Streams Gemini RAG tokens over SSE with:
    - Bounded `asyncio.Queue(maxsize=30)` backpressure
    - 15s `: heartbeat\\n\\n` W3C keep-alive comments
    - Client disconnect detection & worker cancellation
    - Inline `form_fill` block suppression and late SSE event emission
    - Post-stream Exact & Semantic cache storage
    """
    t_gen = time.time()
    system_instruction = get_rag_system_prompt(
        context_str=context_str,
        num_sources=num_sources,
        is_multi_lesson=is_multi_lesson,
        visible_fields=req.visible_fields,
    )
    thread_id = req.thread_id or str(uuid.uuid4())

    user_prompt_text = req.query
    gemini_contents = [types.Content(role="user", parts=[types.Part.from_text(text=user_prompt_text)])]

    loop = asyncio.get_running_loop()
    stop_event = threading.Event()
    # Bounded queue (maxsize=30) enforces Backpressure on slow clients and prevents memory bloat
    queue: asyncio.Queue[str | Exception | None] = asyncio.Queue(maxsize=30)
    recorded_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def _produce_tokens():
        candidate_models = [settings.GEMINI_MODEL, "gemini-2.5-flash", "gemini-1.5-flash"]
        candidate_models = list(dict.fromkeys([m for m in candidate_models if m]))
        last_err = None
        client = gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)

        for model_name in candidate_models:
            try:
                stream_res = client.models.generate_content_stream(
                    model=model_name,
                    contents=gemini_contents,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=1024,
                        system_instruction=system_instruction,
                    ),
                )
                for chunk in stream_res:
                    if stop_event.is_set():
                        break
                    if getattr(chunk, "usage_metadata", None):
                        meta = chunk.usage_metadata
                        recorded_usage["prompt_tokens"] = getattr(meta, "prompt_token_count", 0) or 0
                        recorded_usage["completion_tokens"] = getattr(meta, "candidates_token_count", 0) or 0
                        recorded_usage["total_tokens"] = getattr(meta, "total_token_count", 0) or 0
                    chunk_text = None
                    try:
                        chunk_text = chunk.text
                    except Exception:
                        pass
                    if chunk_text:
                        future = asyncio.run_coroutine_threadsafe(queue.put(chunk_text), loop)
                        future.result(timeout=30.0)
                if not stop_event.is_set():
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop).result(timeout=5.0)
                return
            except Exception as e:
                last_err = e
                logger.warning("Gemini streaming attempt failed on model, attempting fallback", model=model_name, error=str(e))
                continue

        if not stop_event.is_set() and last_err:
            asyncio.run_coroutine_threadsafe(queue.put(last_err), loop).result(timeout=5.0)

    producer_task = asyncio.create_task(asyncio.to_thread(_produce_tokens))

    accumulated_answer: list[str] = []
    is_client_disconnected = False
    first_token_received = False
    first_token_time: float | None = None
    token_count = 0
    form_fill_detected = False
    form_fill_emitted = False

    try:
        while True:
            if await request.is_disconnected():
                logger.info("Client disconnected during SSE stream — cancelling generation", thread_id=thread_id)
                is_client_disconnected = True
                break

            try:
                item = await asyncio.wait_for(queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
                continue

            if item is None:
                break
            elif isinstance(item, Exception):
                logger.error("Error during Gemini stream generation", error=str(item))
                yield format_sse("error", {"message": f"حدث خطأ أثناء معالجة الرد: {type(item).__name__}: {str(item)}"})
                break
            else:
                now = time.time()
                if not first_token_received:
                    first_token_received = True
                    first_token_time = now
                    record_streaming_ttft(now - t0)
                token_count += max(1, len(item) // 4)
                accumulated_answer.append(item)

                if form_fill_detected:
                    continue

                combined_text = "".join(accumulated_answer)
                if "```form_fill" in combined_text:
                    form_fill_detected = True
                    if "```form_fill" in item:
                        prefix = item.split("```form_fill", 1)[0]
                        if prefix:
                            yield format_sse("token", {"text": prefix})
                    continue

                yield format_sse("token", {"text": item})
    finally:
        stop_event.set()
        producer_task.cancel()
        if first_token_time is not None and token_count > 0:
            stream_duration = time.time() - first_token_time
            if stream_duration > 0:
                record_streaming_tpot(stream_duration / token_count)
        record_stage_duration("gemini_generation", time.time() - t_gen)
        record_stage_duration("total", time.time() - t0)

        pt = recorded_usage["prompt_tokens"]
        ct = recorded_usage["completion_tokens"]
        tt = recorded_usage["total_tokens"]
        if tt == 0:
            ct = max(1, token_count)
            pt = max(1, (len(context_str) + len(req.query)) // 4)
            tt = pt + ct
        record_token_usage(prompt_tokens=pt, completion_tokens=ct, total_tokens=tt)

    if not is_client_disconnected:
        full_answer = "".join(accumulated_answer)
        clean_answer = full_answer

        is_qa_only = (req.erp_intent or "").strip().lower() == "question"
        if not form_fill_emitted and not is_qa_only:
            match = re.search(r"```(?:form_fill|json)?\s*(\{[\s\S]*?\})\s*```", full_answer)
            if match:
                try:
                    parsed_json = json.loads(match.group(1))
                    is_batch = bool(parsed_json.get("batch_mode", False)) or bool(parsed_json.get("batch_items"))
                    b_items = parsed_json.get("batch_items", [])
                    f_data = parsed_json.get("fields", parsed_json if not is_batch else {})
                    r_data = parsed_json.get("rows", [])
                    raw_action_intent = str(parsed_json.get("intent") or "new").strip().lower()
                    action_intent = raw_action_intent if raw_action_intent in ("new", "edit_current") else "new"
                    payload = {
                        "intent": "form_fill",
                        "action_intent": action_intent,
                        "fields": f_data,
                        "rows": r_data,
                        "screenKey": req.erp_key,
                        "pageId": getattr(req, "page_id", None) or parsed_json.get("page_id") or parsed_json.get("pageId"),
                        "batch_mode": is_batch,
                        "batch_items": b_items,
                    }
                    logger.info("Emitting late form_fill SSE event", batch_mode=is_batch, items_count=len(b_items), erp_key=req.erp_key)
                    yield format_sse("form_fill", payload)
                    form_fill_emitted = True
                except Exception as e:
                    logger.error("Failed to parse form_fill json", error=str(e))
        clean_answer = re.sub(r"```form_fill\s*\{.*?\}\s*```", "", full_answer, flags=re.DOTALL).strip()

        if clean_answer:
            final_resp = SearchResponse(answer=clean_answer, sources=sources, query_used=req.query)
            if settings.EXACT_CACHE_ENABLED:
                exact_cache_service.store(
                    normalized_query,
                    final_resp,
                    user_ctx,
                    req.scope_fingerprint,
                )
            if settings.SEMANTIC_CACHE_ENABLED and not req.visible_fields:
                cache_task = asyncio.create_task(
                    semantic_cache_service.store(
                        query=req.query,
                        query_vector=dense_vec,
                        response=final_resp,
                        user_ctx=user_ctx,
                        scope_fingerprint=req.scope_fingerprint,
                    )
                )
                background_tasks.add(cache_task)
                cache_task.add_done_callback(background_tasks.discard)

        latency_ms = round((time.time() - t0) * 1000, 2)
        yield format_sse("done", {
            "thread_id": thread_id,
            "provenance": "RAG_GENERATION",
            "cache_hit": False,
            "latency_ms": latency_ms,
            "metrics": {"total_latency_ms": latency_ms},
        })

