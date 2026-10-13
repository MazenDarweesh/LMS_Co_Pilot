import asyncio
import os
import json
import re
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Any, AsyncIterator
import structlog
from fastapi import Request
from google import genai
from google.genai import types

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage, AIMessage


from src.core.config import settings
from src.core.prompts import (
    RAG_SYSTEM_PROMPT,
    get_rag_system_prompt,
    get_erp_intent_classification_prompt,
    get_erp_form_extraction_prompt,
)
from src.agents.base_agent import AgentState, agent_service
from src.models.search_models import SearchRequest, SearchResponse, SourceItem
from src.models.auth_models import UserContext
from src.services.embedding_service import embedding_service
from src.services.qdrant_service import qdrant_service
from src.services.reranker_service import reranker_service
from src.services.semantic_cache_service import semantic_cache_service
from src.services.exact_cache_service import exact_cache_service
from src.services.intent_router import intent_router, IntentType
from src.core.metrics import (
    record_cache_lookup,
    record_exact_cache_lookup,
    record_stage_duration,
    record_token_usage,
    record_streaming_ttft,
    record_streaming_tpot,
    record_guardrail_refusal,
)
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard
from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue

logger = structlog.get_logger()

def _build_scope_filter(req: SearchRequest) -> Filter | None:
    must = []
    
    # 1. Scope Content Type Filtering
    if req.scope == "course":
        must.append(FieldCondition(key="content_type", match=MatchAny(any=["video_chunk", "pdf_chunk"])))
    elif req.scope == "standalone":
        must.append(FieldCondition(key="content_type", match=MatchValue(value="standalone_video_chunk")))
    elif req.scope == "playlist":
        must.append(FieldCondition(key="content_type", match=MatchValue(value="playlist_video_chunk")))
        
    # 2. Hierarchical Scope ID Filtering
    # Explicit binding: only filter by lesson/unit/module when scope specifically targets that level.
    # Matches both single fields and multi-reference array fields (Process Once, Reference Everywhere).
    if (req.scope in ("lessons", "multi_lesson") or req.lesson_ids) and req.lesson_ids:
        must.append(Filter(should=[
            FieldCondition(key="lesson_id", match=MatchAny(any=req.lesson_ids)),
            FieldCondition(key="lesson_ids", match=MatchAny(any=req.lesson_ids)),
        ]))
    elif req.scope == "lesson" and req.lesson_id:
        must.append(Filter(should=[
            FieldCondition(key="lesson_id", match=MatchValue(value=req.lesson_id)),
            FieldCondition(key="lesson_ids", match=MatchValue(value=req.lesson_id)),
        ]))
    elif req.scope == "unit" and req.unit_id:
        must.append(FieldCondition(key="unit_id", match=MatchValue(value=req.unit_id)))
    elif req.scope == "module" and req.module_id:
        must.append(Filter(should=[
            FieldCondition(key="module_id", match=MatchValue(value=req.module_id)),
            FieldCondition(key="module_ids", match=MatchValue(value=req.module_id)),
        ]))
    elif req.scope not in {"all", "module", "unit", "lesson", "lessons", "multi_lesson"}:
        # Backward compatibility for direct ID queries or legacy playlist/video requests
        if req.lesson_ids:
            must.append(Filter(should=[
                FieldCondition(key="lesson_id", match=MatchAny(any=req.lesson_ids)),
                FieldCondition(key="lesson_ids", match=MatchAny(any=req.lesson_ids)),
            ]))
        elif req.lesson_id:
            must.append(Filter(should=[
                FieldCondition(key="lesson_id", match=MatchValue(value=req.lesson_id)),
                FieldCondition(key="lesson_ids", match=MatchValue(value=req.lesson_id)),
            ]))
        elif req.unit_id:
            must.append(FieldCondition(key="unit_id", match=MatchValue(value=req.unit_id)))
        elif req.module_id:
            must.append(Filter(should=[
                FieldCondition(key="module_id", match=MatchValue(value=req.module_id)),
                FieldCondition(key="module_ids", match=MatchValue(value=req.module_id)),
            ]))

    if req.playlist_id:
        must.append(FieldCondition(key="playlist_id", match=MatchValue(value=req.playlist_id)))
    if req.video_id:
        must.append(FieldCondition(key="video_id", match=MatchValue(value=req.video_id)))

    # 3. Level & Content Type Filtering
    if req.level_id:
        must.append(FieldCondition(key="level_id", match=MatchValue(value=req.level_id)))
    if req.type_id:
        must.append(FieldCondition(key="type_id", match=MatchValue(value=req.type_id)))
        
    return Filter(must=must) if must else None

def _filter_valid_chunks(chunks: list[dict]) -> list[dict]:
    """
    تصفية المقاطع لاستبعاد أي مقطع غير مكتمل التوصيف قبل بناء السياق والمصادر.
    تضمن هذه الخطوة المطابقة الكاملة بين عدد وأرقام المقاطع المرسلة إلى Gemini
    وبين المصفوفة النهائية للمصادر المرجعة للواجهة الأمامية.
    """
    valid = []
    for chunk in chunks:
        c_type = chunk.get("content_type")
        if c_type in ["video_chunk", "standalone_video_chunk", "playlist_video_chunk"]:
            if chunk.get("source_url"):
                valid.append(chunk)
        elif c_type == "pdf_chunk":
            valid.append(chunk)
    return valid


def _build_rag_context_str(chunks: list[dict]) -> str:
    context_blocks = []
    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text_msa", "")
        url  = chunk.get("source_url", "")
        start_time = chunk.get("start_time")
        end_time = chunk.get("end_time")
        
        source_info = f"[{i}] {text}\n(المصدر: {url}"
        if start_time is not None:
            source_info += f" - من {start_time} إلى {end_time} ثانية"
        source_info += ")"
        context_blocks.append(source_info)

    return "\n\n".join(context_blocks)


def _build_source_items(chunks: list[dict]) -> list[SourceItem]:
    """
    ينشئ كائنات SourceItem مهيكلة مرتبة متسلسلاً من 1 إلى N بناءً على المقاطع المصفاة.
    يضمن توفير حقل 'title' لعرضه مباشرة في بطاقات المصادر بالواجهة.
    """
    sources: list[SourceItem] = []
    for i, chunk in enumerate(chunks, 1):
        c_type = chunk.get("content_type")
        if c_type in ["video_chunk", "standalone_video_chunk", "playlist_video_chunk"]:
            start_s = chunk.get("start_time")
            end_s = chunk.get("end_time")
            if start_s is not None and end_s is not None:
                s_min, s_sec = divmod(int(start_s), 60)
                e_min, e_sec = divmod(int(end_s), 60)
                title = f"المصدر [{i}] — مقطع فيديو ({s_min:02d}:{s_sec:02d} - {e_min:02d}:{e_sec:02d})"
            else:
                title = f"المصدر [{i}] — مقطع فيديو"
            sources.append(SourceItem(
                type="video",
                url=chunk.get("source_url"),
                title=title,
                start=start_s,
                end=end_s,
                lesson_id=chunk.get("lesson_id"),
            ))
        elif c_type == "pdf_chunk":
            section = chunk.get("section_title")
            page = chunk.get("page_number")
            if section:
                title = f"المصدر [{i}] — {section}"
            elif page:
                title = f"المصدر [{i}] — صفحة {page}"
            else:
                title = f"المصدر [{i}] — مستند PDF"
            sources.append(SourceItem(
                type="pdf",
                title=title,
                page=page,
                section=section,
                lesson_id=chunk.get("lesson_id"),
            ))
    return sources

def _trim_messages(
    messages: list,
    max_messages: int,
    max_tokens_approx: int
) -> list:
    """
    Sliding Window Memory Trimmer — 2026 Best Practice.
    
    Strategy (two-layer defense):
    Layer 1: Keep only the last `max_messages` (hard message count limit).
    Layer 2: If total chars still too large, trim further from the oldest.
    
    Note: We use character count as a cheap proxy for tokens (1 token ≈ 4 chars
    in Arabic/English mixed text). This avoids the overhead of a full tokenizer call.
    
    Always preserves the LAST message (the new student question) intact.
    """
    if not messages:
        return messages

    # Layer 1: Sliding Window — trim by message count
    trimmed = list(messages[-max_messages:]) if len(messages) > max_messages else list(messages)

    # Layer 2: Token Budget Guard — trim by approximate character budget
    # 1 token ≈ 4 chars (conservative estimate for Arabic)
    char_budget = max_tokens_approx * 4
    total_chars = sum(len(getattr(m, "content", "")) for m in trimmed)

    while total_chars > char_budget and len(trimmed) > 1:
        # Always drop from the oldest end (index 0), never drop the last message
        removed = trimmed.pop(0)
        total_chars -= len(getattr(removed, "content", ""))

    return trimmed

def _write_search_debug_file(
    query: str, 
    candidates: list[dict], 
    reranked: list[dict], 
    prompt: str, 
    answer: str,
    metrics: dict | None = None,
    token_usage: dict | None = None
) -> None:
    """حفظ تفاصيل عملية البحث في ملف JSON عند تفعيل SEARCH_DEBUG_ENABLED فقط لمنع استهلاك القرص."""
    if not settings.SEARCH_DEBUG_ENABLED:
        return

    debug_dir = "downloads/search_debugs"
    os.makedirs(debug_dir, exist_ok=True)
    
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    file_path = os.path.join(debug_dir, f"search_{timestamp}.json")
    
    debug_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "query": query,
        "metrics": metrics or {},
        "token_usage": token_usage or {},
        "qdrant_rrf_candidates": [
            {
                "point_id": c.get("_qdrant_point_id"),
                "chunk_id": c.get("chunk_id"),
                "content_type": c.get("content_type"),
                "text_msa": c.get("text_msa"),
                "source_url": c.get("source_url")
            } for c in candidates
        ],
        "reranker_results": [
            {
                "point_id": r.get("_qdrant_point_id"),
                "chunk_id": r.get("chunk_id"),
                "content_type": r.get("content_type"),
                "text_msa": r.get("text_msa"),
                "source_url": r.get("source_url"),
                "reranker_score": r.get("_reranker_score")
            } for r in reranked
        ],
        "prompt_sent_to_gemini": prompt,
        "gemini_answer": answer
    }
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(debug_data, f, ensure_ascii=False, indent=4)
    logger.info("Search debug file written", path=file_path)


def _format_sse(event_type: str, data: dict) -> str:
    """Formats a payload dictionary into a standard, UTF-8 compliant SSE message."""
    payload = json.dumps(data, ensure_ascii=False)
    lines = payload.split("\n")
    data_lines = "\n".join(f"data: {line}" for line in lines)
    return f"event: {event_type}\n{data_lines}\n\n"


class SearchService:

    def __init__(self):
        self._gemini_client = None
        self.app_graph = None

    def initialize(self):
        self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        workflow = StateGraph(AgentState)
        workflow.add_node("agent", self._call_model)
        workflow.add_edge(START, "agent")
        workflow.add_edge("agent", END)
        self.app_graph = workflow.compile(checkpointer=agent_service.checkpointer)

    async def _call_model(self, state: AgentState) -> dict:
        raw_messages = state["messages"]
        context_str = state["context"].get("context_str", "") if state.get("context") else ""
        
        # Apply Sliding Window + Token Budget trimming before sending to Gemini
        messages = _trim_messages(
            messages=raw_messages,
            max_messages=settings.AGENT_MAX_HISTORY_MESSAGES,
            max_tokens_approx=settings.AGENT_MAX_CONTEXT_TOKENS,
        )
        
        if len(raw_messages) != len(messages):
            logger.debug(
                "Memory trimmed",
                original_count=len(raw_messages),
                trimmed_count=len(messages),
            )
            
        gemini_contents = []
        for msg in messages:
            role = "user" if isinstance(msg, HumanMessage) else "model"
            gemini_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))
            
        num_sources = state["context"].get("num_sources", 1) if state.get("context") else 1
        is_multi_lesson = state["context"].get("is_multi_lesson", False) if state.get("context") else False
        visible_fields = state["context"].get("visible_fields") if state.get("context") else None
        system_instruction = get_rag_system_prompt(
            context_str=context_str,
            num_sources=num_sources,
            is_multi_lesson=is_multi_lesson,
            visible_fields=visible_fields,
        )

        t0 = time.time()
        response = await asyncio.to_thread(
            (self._gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)).models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=gemini_contents,
            config=types.GenerateContentConfig(
                temperature=0.2, 
                max_output_tokens=1024,
                system_instruction=system_instruction
            ),
        )
        gemini_latency_ms = round((time.time() - t0) * 1000, 2)
        
        token_usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_usage = {
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
            }
            
        if token_usage.get("total_tokens", 0) > settings.AGENT_MAX_CONTEXT_TOKENS * 0.85:
            logger.warning(
                "Token usage approaching budget limit",
                total_tokens=token_usage.get("total_tokens"),
                budget=settings.AGENT_MAX_CONTEXT_TOKENS
            )
            
        return {
            "messages": [AIMessage(content=response.text)],
            "context": {
                "token_usage": token_usage,
                "gemini_latency_ms": gemini_latency_ms,
                "system_prompt_used": system_instruction
            }
        }

    async def search(self, req: SearchRequest, user_ctx: UserContext) -> SearchResponse:
        logger.info("Search started", query=req.query, scope=req.scope, user_entities_count=len(user_ctx.user_entities))
        metrics = {}
        t0 = time.time()

        # ──────────────────────────────────────────────
        # 0. Fast Ingress: Intent Router (< 1ms bypass)
        # ──────────────────────────────────────────────
        if settings.INTENT_ROUTER_ENABLED:
            t_intent = time.time()
            intent_res = intent_router.classify(req.query)
            intent_duration = time.time() - t_intent
            record_stage_duration("intent_router", intent_duration)

            if intent_res.intent != IntentType.RAG_QUERY and intent_res.canned_response:
                metrics["intent"] = intent_res.intent.value
                metrics["intent_latency_ms"] = round(intent_duration * 1000, 2)
                metrics["total_latency_ms"] = round((time.time() - t0) * 1000, 2)
                record_stage_duration("total", time.time() - t0)
                if intent_res.intent == IntentType.SECURITY_VIOLATION:
                    record_guardrail_refusal("security_violation")
                    logger.warning("Security violation intercepted at Fast Ingress 🛡️", query_snippet=req.query[:50], ms=metrics["total_latency_ms"])
                else:
                    logger.info("Fast Ingress intercept", intent=intent_res.intent.value, ms=metrics["total_latency_ms"])
                return SearchResponse(
                    answer=intent_res.canned_response,
                    sources=[],
                    query_used=req.query,
                    provenance="INTENT_ROUTER",
                    cache_hit=False,
                    latency_ms=round((time.time() - t0) * 1000, 2),
                )


        # ──────────────────────────────────────────────
        # 1. Normalize query
        # ──────────────────────────────────────────────
        normalized_query = normalize_arabic_text_leaderboard(req.query)
        logger.debug("Query normalized for cache & embedding", original=req.query, normalized=normalized_query)

        # ──────────────────────────────────────────────
        # 1.1 Fast Ingress: Tier-1 Exact In-Memory Cache (< 2ms)
        # ──────────────────────────────────────────────
        if settings.EXACT_CACHE_ENABLED and not req.skip_cache and not req.visible_fields and not req.form_schema:
            t_exact = time.time()
            exact_hit = exact_cache_service.lookup(normalized_query, user_ctx, req.scope_fingerprint)
            exact_duration = time.time() - t_exact
            record_stage_duration("exact_cache", exact_duration)
            if exact_hit is not None:
                record_exact_cache_lookup(hit=True)
                metrics["exact_cache_hit"] = True
                metrics["exact_cache_latency_ms"] = round(exact_duration * 1000, 2)
                metrics["total_latency_ms"] = round((time.time() - t0) * 1000, 2)
                record_stage_duration("total", time.time() - t0)
                logger.info("Serving from Exact In-Memory Cache ⚡", ms=metrics["total_latency_ms"])
                if settings.SEARCH_DEBUG_ENABLED:
                    await asyncio.to_thread(
                        _write_search_debug_file,
                        query=req.query,
                        candidates=[],
                        reranked=[],
                        prompt="EXACT_CACHED",
                        answer=exact_hit.answer,
                        metrics=metrics,
                    )
                exact_hit.provenance = "EXACT_CACHE"
                exact_hit.cache_hit = True
                exact_hit.latency_ms = metrics["total_latency_ms"]
                return exact_hit
            else:
                record_exact_cache_lookup(hit=False)

        # ──────────────────────────────────────────────
        # 2. Embed → Dense + Sparse
        # ──────────────────────────────────────────────
        t_embed = time.time()
        dense_vec, sparse_vec = await embedding_service.get_both_embeddings(normalized_query)
        embedding_duration = time.time() - t_embed
        metrics["embedding_latency_ms"] = round(embedding_duration * 1000, 2)
        record_stage_duration("embedding", embedding_duration)

        # ──────────────────────────────────────────────
        # 2.1 Tier-2 Semantic Cache (Qdrant Vector Cache)
        # ──────────────────────────────────────────────
        if settings.SEMANTIC_CACHE_ENABLED and not req.skip_cache and not req.visible_fields and not req.form_schema:
            t_cache = time.time()
            cached_resp = await semantic_cache_service.lookup(
                query_vector=dense_vec,
                user_ctx=user_ctx,
                scope_fingerprint=req.scope_fingerprint,
            )
            cache_duration = time.time() - t_cache
            record_stage_duration("cache_lookup", cache_duration)
            if cached_resp is not None:
                record_cache_lookup(hit=True)
                # Auto-populate Tier-1 Exact Cache for immediate subsequent hits
                if settings.EXACT_CACHE_ENABLED:
                    exact_cache_service.store(normalized_query, cached_resp, user_ctx, req.scope_fingerprint)

                metrics["cache_hit"] = True
                metrics["cache_latency_ms"] = round(cache_duration * 1000, 2)
                metrics["total_latency_ms"] = round((time.time() - t0) * 1000, 2)
                record_stage_duration("total", time.time() - t0)
                logger.info("Serving from Semantic Cache", ms=metrics["total_latency_ms"])
                if settings.SEARCH_DEBUG_ENABLED:
                    await asyncio.to_thread(
                        _write_search_debug_file,
                        query=req.query,
                        candidates=[],
                        reranked=[],
                        prompt="CACHED",
                        answer=cached_resp.answer,
                        metrics=metrics,
                    )
                cached_resp.provenance = "SEMANTIC_CACHE"
                cached_resp.cache_hit = True
                cached_resp.latency_ms = metrics["total_latency_ms"]
                return cached_resp
            else:
                record_cache_lookup(hit=False)

        scope_filter = _build_scope_filter(req)

        t1 = time.time()
        candidates = await qdrant_service.hybrid_search(
            dense_vector=dense_vec,
            sparse_vector=sparse_vec,
            user_ctx=user_ctx,
            limit=settings.QDRANT_SEARCH_CANDIDATES_LIMIT,
            extra_filter=scope_filter,
        )
        qdrant_duration = time.time() - t1
        metrics["qdrant_latency_ms"] = round(qdrant_duration * 1000, 2)
        record_stage_duration("vector_search", qdrant_duration)

        if not candidates:
            if settings.SEARCH_DEBUG_ENABLED:
                await asyncio.to_thread(
                    _write_search_debug_file,
                    query=req.query,
                    candidates=[],
                    reranked=[],
                    prompt="",
                    answer="لا تتوفر معلومات كافية في المحتوى المتاح حول هذا الموضوع.",
                    metrics=metrics
                )
            return SearchResponse(
                answer="لا تتوفر معلومات كافية في المحتوى المتاح حول هذا الموضوع.",
                sources=[],
                query_used=req.query,
                provenance="NO_CANDIDATES",
                cache_hit=False,
                latency_ms=round((time.time() - t0) * 1000, 2),
            )

        logger.info("Qdrant candidates returned", count=len(candidates), ms=metrics["qdrant_latency_ms"])

        t2 = time.time()
        top_chunks = await reranker_service.rerank(
            query=req.query,
            passages=candidates,
            top_n=min(req.limit, settings.QDRANT_SEARCH_CANDIDATES_LIMIT),
            text_field="text_msa",
        )
        reranker_duration = time.time() - t2
        metrics["reranker_latency_ms"] = round(reranker_duration * 1000, 2)
        record_stage_duration("reranking", reranker_duration)
        logger.info("Reranked results", top_n=len(top_chunks), ms=metrics["reranker_latency_ms"])

        # ──────────────────────────────────────────────
        # 5. Build context & Invoke LangGraph
        # ──────────────────────────────────────────────
        valid_chunks = _filter_valid_chunks(top_chunks)
        context_str = _build_rag_context_str(valid_chunks)
        sources = _build_source_items(valid_chunks)
        num_sources = len(valid_chunks) if valid_chunks else 1
        is_multi_lesson = bool(req.lesson_ids) or (req.scope in ("lessons", "multi_lesson"))
        
        thread_id = req.thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        
        t3 = time.time()
        final_state = await self.app_graph.ainvoke(
            {
                "messages": [HumanMessage(content=req.query)],
                "context": {
                    "context_str": context_str,
                    "num_sources": num_sources,
                    "is_multi_lesson": is_multi_lesson,
                    "visible_fields": req.visible_fields,
                },
            },
            config=config
        )
        graph_latency_ms = round((time.time() - t3) * 1000, 2)
        record_stage_duration("gemini_generation", time.time() - t3)
        record_stage_duration("total", time.time() - t0)
        
        answer_text = final_state["messages"][-1].content
        
        returned_context = final_state.get("context", {})
        metrics["gemini_latency_ms"] = returned_context.get("gemini_latency_ms", 0)
        metrics["total_latency_ms"] = round((time.time() - t0) * 1000, 2)
        token_usage = returned_context.get("token_usage", {})
        if token_usage:
            record_token_usage(
                prompt_tokens=token_usage.get("prompt_tokens", 0),
                completion_tokens=token_usage.get("completion_tokens", 0),
                total_tokens=token_usage.get("total_tokens", 0),
            )
        
        logger.info("Gemini answer generated via LangGraph", answer_length=len(answer_text), thread_id=thread_id, ms=graph_latency_ms)

        # Write trace log file asynchronously only if diagnostic logging is enabled
        if settings.SEARCH_DEBUG_ENABLED:
            await asyncio.to_thread(
                _write_search_debug_file,
                query=req.query,
                candidates=candidates,
                reranked=valid_chunks,
                prompt=returned_context.get("system_prompt_used", ""),
                answer=answer_text,
                metrics=metrics,
                token_usage=token_usage
            )

        final_response = SearchResponse(
            answer=answer_text,
            sources=sources,
            query_used=req.query,
            provenance="RAG_GENERATION",
            cache_hit=False,
            latency_ms=metrics["total_latency_ms"],
        )

        # ──────────────────────────────────────────────
        # 6. Save in Exact Cache & Semantic Cache
        # ──────────────────────────────────────────────
        if settings.EXACT_CACHE_ENABLED and answer_text:
            exact_cache_service.store(
                normalized_query=normalized_query,
                response=final_response,
                user_ctx=user_ctx,
                scope_fingerprint=req.scope_fingerprint,
            )

        if settings.SEMANTIC_CACHE_ENABLED and answer_text:
            cache_task = asyncio.create_task(
                semantic_cache_service.store(
                    query=req.query,
                    query_vector=dense_vec,
                    response=final_response,
                    user_ctx=user_ctx,
                    scope_fingerprint=req.scope_fingerprint,
                )
            )
            _background_tasks.add(cache_task)
            cache_task.add_done_callback(_background_tasks.discard)

        return final_response

    async def _classify_form_action_intent(self, query: str) -> bool:
        """
        Two-Stage Production Intent Classifier:
        Stage 1: Fast Word Matching & Heuristics (< 0.1ms).
        Stage 2: If Stage 1 is inconclusive, fallback to AI Model (gemini-3.5-flash-lite) for semantic classification.
        """
        q = query.strip()
        if not q:
            return False

        # ── STAGE 1: Fast Word Matching ─────────────────────────────────────
        # 1.1 Decisive Question Interrogatives
        question_starters = (
            "أين", "اين", "كيف", "ما هو", "ما هي", "ماهو", "ماهي", "متى", "هل",
            "لماذا", "ليه", "اشرح", "وضح", "شرح", "معنى", "ايه هو", "ايه هي",
            "كام", "كم", "مين", "بكام", "فين", "إزاي", "ازاي"
        )
        is_question_start = any(
            q.startswith(starter + " ") or q.startswith(starter + "،") or q == starter
            for starter in question_starters
        )

        # 1.2 Decisive Action Phrases (Unambiguous Form Filling Requests)
        decisive_action_phrases = (
            "سجل لي", "سجل عميل", "سجل فاتورة", "ادخل فاتورة", "اعمل فاتورة",
            "اعمل قيد", "قيد يومية بقيمة", "عايز اسجل", "عايز ادخل", "عايز اعمل فاتورة",
            "عايز اعمل قيد", "تسجيل عميل جديد", "فاتورة مبيعات جديدة", "فاتورة مشتريات جديدة"
        )
        has_decisive_action = any(phrase in q for phrase in decisive_action_phrases)

        # If Stage 1 decisively matches a question with no action phrases -> return False immediately
        if is_question_start and not has_decisive_action:
            logger.debug("Intent Stage 1 matched decisive question, bypassing AI classification", query=q)
            return False

        # If Stage 1 decisively matches an unambiguous action phrase -> return True immediately
        if has_decisive_action:
            logger.debug("Intent Stage 1 matched decisive action phrase", query=q)
            return True

        # ── STAGE 2: AI Model Fallback (gemini-3.5-flash-lite) ───────────────
        # When Stage 1 is inconclusive (ambiguous or colloquial phrasing), invoke lightweight AI classifier
        logger.info("Intent Stage 1 inconclusive; invoking Stage 2 AI classifier", model=settings.GEMINI_MODEL, query=q)
        try:
            intent_prompt = get_erp_intent_classification_prompt(q)
            model_to_use = settings.GEMINI_MODEL
            resp = await asyncio.to_thread(
                (self._gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)).models.generate_content,
                model=model_to_use,
                contents=intent_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    max_output_tokens=16,
                ),
            )
            if resp and resp.text:
                parsed = json.loads(resp.text)
                detected = parsed.get("intent", "").lower()
                logger.info("Intent Stage 2 AI classification result", detected=detected, query=q)
                return detected == "form_action"
        except Exception as e:
            logger.warning("Intent Stage 2 AI classification failed, falling back to heuristic", error=str(e))
            # Fallback heuristic: check for phone numbers / monetary tokens
            import re
            return bool(re.search(r'\b01\d{9}\b|\b\d{3,}\b|\bج\.م\b|\bجنيه\b|\bEGP\b', q))

        return False

    async def _extract_form_fields_if_needed(
        self, query: str, visible_fields: list[str] | None, form_schema: list[dict] | None = None
    ) -> dict[str, Any]:
        if not visible_fields and not form_schema:
            return {}
        try:
            fields_ctx = form_schema if form_schema else visible_fields
            fields_ctx_json = json.dumps(fields_ctx, ensure_ascii=False)
            prompt = get_erp_form_extraction_prompt(query, fields_ctx_json)
            # Use gemini-3.5-flash-lite as standard high-performance engine
            candidate_models = [settings.GEMINI_MODEL]
            candidate_models = list(dict.fromkeys([m for m in candidate_models if m]))

            last_err = None
            for model_name in candidate_models:
                try:
                    resp = await asyncio.to_thread(
                        (self._gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)).models.generate_content,
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            temperature=0.0,
                        ),
                    )
                    data = json.loads(resp.text)
                    if isinstance(data, dict):
                        if "fields" not in data and "rows" not in data and "batch_items" not in data:
                            return {"batch_mode": False, "fields": data, "rows": []}
                        return data
                except Exception as err:
                    last_err = err
                    logger.warning("Batch extraction attempt failed on model, trying next", model=model_name, error=str(err))
                    continue

            if last_err:
                logger.error("All candidate models failed for ERP form extraction", error=str(last_err))
        except Exception as e:
            logger.error("Failed to extract ERP form data", error=str(e))
        return {}
async def search_stream(
        self, req: SearchRequest, user_ctx: UserContext, request: Request
    ) -> AsyncIterator[str]:
        """
        Production-grade Server-Sent Events (SSE) streaming search endpoint:
        - Step 0: Fast Ingress Intent Router (< 0.1ms short-circuit)
        - Step 1: 2-Tier Caching (Exact LRU + Semantic Qdrant Vector Cache)
        - Step 2: Dense + Sparse Qdrant retrieval + FlashRank Reranker (< 25ms)
        - Step 3: Yields 'sources' event first for immediate citation rendering
        - Step 4: Streams tokens in real time from Gemini SDK with heartbeat & disconnect protection
        - Step 5: Post-stream exact & semantic cache storage and terminal 'done' event
        """
        logger.info("Search stream started", query=req.query, scope=req.scope)
        t0 = time.time()

        # ──────────────────────────────────────────────
        # 0. Fast Ingress: Intent Router (< 1ms bypass)
        # ──────────────────────────────────────────────
        if settings.INTENT_ROUTER_ENABLED:
            t_stage = time.time()
            intent_res = intent_router.classify(req.query)
            record_stage_duration("intent_router", time.time() - t_stage)
            if intent_res.intent != IntentType.RAG_QUERY and intent_res.canned_response:
                if intent_res.intent == IntentType.SECURITY_VIOLATION:
                    record_guardrail_refusal("security_violation")
                record_stage_duration("total", time.time() - t0)
                latency_ms = round((time.time() - t0) * 1000, 2)
                yield _format_sse("sources", {"sources": []})
                yield _format_sse("token", {"text": intent_res.canned_response})
                yield _format_sse("done", {
                    "intent": intent_res.intent.value,
                    "provenance": "INTENT_ROUTER",
                    "cache_hit": False,
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                })
                return

        # ──────────────────────────────────────────────
        # 1. Normalize Query & Check 2-Tier Cache
        # ──────────────────────────────────────────────
        normalized_query = normalize_arabic_text_leaderboard(req.query)

        # 1.1 Exact In-Memory Cache
        if settings.EXACT_CACHE_ENABLED and not req.skip_cache and not req.visible_fields and not req.form_schema:
            t_stage = time.time()
            exact_hit = exact_cache_service.lookup(normalized_query, user_ctx, req.scope_fingerprint)
            record_stage_duration("exact_cache", time.time() - t_stage)
            if exact_hit is not None:
                record_exact_cache_lookup(hit=True)
                record_stage_duration("total", time.time() - t0)
                latency_ms = round((time.time() - t0) * 1000, 2)
                yield _format_sse("sources", {"sources": [s.model_dump() for s in exact_hit.sources]})
                yield _format_sse("token", {"text": exact_hit.answer})
                yield _format_sse("done", {
                    "cache_hit": True,
                    "cache_tier": "exact",
                    "provenance": "EXACT_CACHE",
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                })
                return
            else:
                record_exact_cache_lookup(hit=False)

        # 1.2 Embedding & Semantic Cache
        t_emb = time.time()
        dense_vec, sparse_vec = await embedding_service.get_both_embeddings(normalized_query)
        record_stage_duration("embedding", time.time() - t_emb)

        if settings.SEMANTIC_CACHE_ENABLED and not req.skip_cache and not req.visible_fields and not req.form_schema:
            t_sem = time.time()
            cached_resp = await semantic_cache_service.lookup(
                query_vector=dense_vec,
                user_ctx=user_ctx,
                scope_fingerprint=req.scope_fingerprint,
            )
            record_stage_duration("cache_lookup", time.time() - t_sem)
            if cached_resp is not None:
                record_cache_lookup(hit=True)
                record_stage_duration("total", time.time() - t0)
                latency_ms = round((time.time() - t0) * 1000, 2)
                if settings.EXACT_CACHE_ENABLED:
                    exact_cache_service.store(normalized_query, cached_resp, user_ctx, req.scope_fingerprint)
                yield _format_sse("sources", {"sources": [s.model_dump() for s in cached_resp.sources]})
                yield _format_sse("token", {"text": cached_resp.answer})
                yield _format_sse("done", {
                    "cache_hit": True,
                    "cache_tier": "semantic",
                    "provenance": "SEMANTIC_CACHE",
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                })
                return
            else:
                record_cache_lookup(hit=False)

        # ──────────────────────────────────────────────
        # 2. Qdrant Hybrid Search & FlashRank Reranker
        # ──────────────────────────────────────────────
        t_vec = time.time()
        scope_filter = _build_scope_filter(req)
        candidates = await qdrant_service.hybrid_search(
            dense_vector=dense_vec,
            sparse_vector=sparse_vec,
            user_ctx=user_ctx,
            limit=settings.QDRANT_SEARCH_CANDIDATES_LIMIT,
            extra_filter=scope_filter,
        )
        record_stage_duration("vector_search", time.time() - t_vec)

        if not candidates:
            record_stage_duration("total", time.time() - t0)
            latency_ms = round((time.time() - t0) * 1000, 2)
            yield _format_sse("sources", {"sources": []})
            yield _format_sse("token", {"text": "لا تتوفر معلومات كافية في المحتوى المتاح حول هذا الموضوع."})
            yield _format_sse("done", {
                "status": "no_candidates",
                "provenance": "NO_CANDIDATES",
                "cache_hit": False,
                "latency_ms": latency_ms,
                "metrics": {"total_latency_ms": latency_ms},
            })
            return

        t_rerank = time.time()
        top_chunks = await reranker_service.rerank(
            query=req.query,
            passages=candidates,
            top_n=min(req.limit, settings.QDRANT_SEARCH_CANDIDATES_LIMIT),
            text_field="text_msa",
        )
        record_stage_duration("reranking", time.time() - t_rerank)

        valid_chunks = _filter_valid_chunks(top_chunks)
        sources = _build_source_items(valid_chunks)

        # Yield sources event first for immediate citation rendering in frontend
        yield _format_sse("sources", {"sources": [s.model_dump() for s in sources]})

        # 🚀 ERP Form Fill Early Extraction: Detect data and emit form_fill event immediately
        extracted_form_fields: dict[str, Any] | None = None
        form_fill_emitted = False
        if (req.visible_fields or req.form_schema) and (await self._classify_form_action_intent(req.query)):
            raw_extracted = await self._extract_form_fields_if_needed(req.query, req.visible_fields, req.form_schema)
            if raw_extracted and isinstance(raw_extracted, dict):
                fields_dict = raw_extracted.get("fields", {}) if isinstance(raw_extracted.get("fields"), dict) else {}
                rows_list = raw_extracted.get("rows", []) if isinstance(raw_extracted.get("rows"), list) else []
                batch_mode = bool(raw_extracted.get("batch_mode", False))
                batch_items = raw_extracted.get("batch_items", []) if isinstance(raw_extracted.get("batch_items"), list) else []

                # Crucial Fix: Only consider extracted_form_fields if ACTUAL data was extracted!
                has_actual_data = bool(fields_dict) or bool(rows_list) or bool(batch_items)
                if has_actual_data:
                    extracted_form_fields = raw_extracted
                    payload = {
                        "intent": "form_fill",
                        "fields": fields_dict,
                        "rows": rows_list,
                        "screenKey": req.erp_key,
                        "batch_mode": batch_mode,
                        "batch_items": batch_items,
                    }
                    logger.info("Emitting early form_fill SSE event", fields=list(fields_dict.keys()), rows_count=len(rows_list), erp_key=req.erp_key)
                    yield _format_sse("form_fill", payload)
                    form_fill_emitted = True

        # ──────────────────────────────────────────────
        # 3. Gemini Streaming with Heartbeat & Disconnect Guard
        # ──────────────────────────────────────────────
        t_gen = time.time()
        context_str = _build_rag_context_str(valid_chunks)
        num_sources = len(valid_chunks) if valid_chunks else 1
        is_multi_lesson = bool(req.lesson_ids) or (req.scope in ("lessons", "multi_lesson"))
        system_instruction = get_rag_system_prompt(
            context_str=context_str,
            num_sources=num_sources,
            is_multi_lesson=is_multi_lesson,
            visible_fields=req.visible_fields,
            extracted_form_fields=extracted_form_fields,
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
            try:
                stream_res = self._gemini_client.models.generate_content_stream(
                    model=settings.GEMINI_MODEL,
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
                    if chunk.text:
                        # Thread-safe put with backpressure: blocks worker thread if queue reaches maxsize
                        future = asyncio.run_coroutine_threadsafe(queue.put(chunk.text), loop)
                        future.result(timeout=30.0)
                if not stop_event.is_set():
                    asyncio.run_coroutine_threadsafe(queue.put(None), loop).result(timeout=5.0)
            except Exception as e:
                if not stop_event.is_set():
                    asyncio.run_coroutine_threadsafe(queue.put(e), loop).result(timeout=5.0)

        producer_task = asyncio.create_task(asyncio.to_thread(_produce_tokens))

        accumulated_answer: list[str] = []
        is_client_disconnected = False
        first_token_received = False
        first_token_time: float | None = None
        token_count = 0
        form_fill_detected = False

        try:
            while True:
                if await request.is_disconnected():
                    logger.info("Client disconnected during SSE stream — cancelling generation", thread_id=thread_id)
                    is_client_disconnected = True
                    break

                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # W3C SSE comment keeps reverse proxy sockets alive without consumer consumption
                    yield ": heartbeat\n\n"
                    continue

                if item is None:
                    break
                elif isinstance(item, Exception):
                    logger.error("Error during Gemini stream generation", error=str(item))
                    yield _format_sse("error", {"message": "حدث خطأ أثناء معالجة الرد."})
                    break
                else:
                    now = time.time()
                    if not first_token_received:
                        first_token_received = True
                        first_token_time = now
                        record_streaming_ttft(now - t0)
                    token_count += max(1, len(item) // 4)
                    accumulated_answer.append(item)

                    # لا ترسل كود الـ form_fill للمستخدم كنص عادي مشوه
                    if form_fill_detected:
                        continue

                    combined_text = "".join(accumulated_answer)
                    if "```form_fill" in combined_text:
                        form_fill_detected = True
                        if "```form_fill" in item:
                            prefix = item.split("```form_fill", 1)[0]
                            if prefix:
                                yield _format_sse("token", {"text": prefix})
                        continue

                    yield _format_sse("token", {"text": item})
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

        # ──────────────────────────────────────────────
        # 4. Cache Accumulation, Form Fill Event & Terminal Done Event
        # ──────────────────────────────────────────────
        if not is_client_disconnected:
            full_answer = "".join(accumulated_answer)
            clean_answer = full_answer

            # بعد انتهاء الرد: افحص هل يوجد بلوك form_fill؟
            if not form_fill_emitted:
                match = re.search(r"```(?:form_fill|json)?\s*(\{[\s\S]*?\})\s*```", full_answer)
                if match:
                    try:
                        parsed_json = json.loads(match.group(1))
                        is_batch = bool(parsed_json.get("batch_mode", False)) or bool(parsed_json.get("batch_items"))
                        b_items = parsed_json.get("batch_items", [])
                        f_data = parsed_json.get("fields", parsed_json if not is_batch else {})
                        r_data = parsed_json.get("rows", [])
                        payload = {
                            "intent": "form_fill",
                            "fields": f_data,
                            "rows": r_data,
                            "screenKey": req.erp_key,
                            "batch_mode": is_batch,
                            "batch_items": b_items,
                        }
                        logger.info("Emitting late form_fill SSE event", batch_mode=is_batch, items_count=len(b_items), erp_key=req.erp_key)
                        yield _format_sse("form_fill", payload)
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
                    _background_tasks.add(cache_task)
                    cache_task.add_done_callback(_background_tasks.discard)

            latency_ms = round((time.time() - t0) * 1000, 2)
            yield _format_sse("done", {
                "thread_id": thread_id,
                "provenance": "RAG_GENERATION",
                "cache_hit": False,
                "latency_ms": latency_ms,
                "metrics": {"total_latency_ms": latency_ms},
            })


_background_tasks: set[asyncio.Task] = set()
search_service = SearchService()
