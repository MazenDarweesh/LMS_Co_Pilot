"""
SearchService Facade — Cognitive Search Pipeline Orchestrator.

Delegates specialized domain logic to `src.services.cognitive_search.search`:
- `rag_context_builder`: Qdrant scope filters, chunk validation, RAG context strings, SourceItems
- `memory_budget_manager`: Sliding-window + token-budget message trimming & LangGraph agent node
- `search_debug_tracer`: Conditional JSON diagnostic trace writer
- `erp_action_extractor`: AI form action intent classifier, catalog schema enricher, JSON extractor
- `sse_stream_producer`: Threaded Gemini SSE token producer, backpressure queue, heartbeat, cache persistence
"""
import asyncio
import re
import time
import uuid
from typing import Any, AsyncIterator
from fastapi import Request
from google import genai
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
import structlog

from src.agents.base_agent import AgentState, agent_service
from src.core.config import settings
from src.core.metrics import (
    record_cache_lookup,
    record_exact_cache_lookup,
    record_guardrail_refusal,
    record_stage_duration,
    record_token_usage,
)
from src.models.auth_models import UserContext
from src.models.search_models import SearchRequest, SearchResponse
from src.services.cognitive_search.embedding_service import embedding_service
from src.services.cognitive_search.exact_cache_service import exact_cache_service
from src.services.cognitive_search.intent_router import IntentType, intent_router
from src.services.cognitive_search.qdrant_service import qdrant_service
from src.services.cognitive_search.reranker_service import reranker_service
from src.services.cognitive_search.search import (
    FORM_FILL_CONFIRMATION,
    build_action_guide_message,
    build_form_fill_payload,
    build_rag_context_str,
    build_schema_from_catalog,
    build_scope_filter,
    build_source_items,
    classify_form_action_intent,
    execute_langgraph_agent_node,
    extract_form_fields_if_needed,
    filter_valid_chunks,
    format_sse,
    resolve_and_enrich_erp_action_schema,
    stream_gemini_rag_tokens,
    trim_messages,
    write_search_debug_file,
)
from src.services.cognitive_search.semantic_cache_service import semantic_cache_service
from src.utils.arabic_speech_utils import normalize_arabic_text_leaderboard

logger = structlog.get_logger()

# Backward-compatible private aliases for internal callers & tests
_build_scope_filter = build_scope_filter
_filter_valid_chunks = filter_valid_chunks
_build_rag_context_str = build_rag_context_str
_build_source_items = build_source_items
_trim_messages = trim_messages
_write_search_debug_file = write_search_debug_file
_format_sse = format_sse
_FORM_FILL_CONFIRMATION = FORM_FILL_CONFIRMATION
_build_form_fill_payload = build_form_fill_payload
_build_schema_from_catalog = build_schema_from_catalog


class SearchService:
    """High-level Facade orchestrating synchronous and streaming RAG + ERP Action pipelines."""

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
        return await execute_langgraph_agent_node(state, self._gemini_client)

    async def _classify_form_action_intent(self, query: str, erp_intent: str | None = None) -> bool:
        return await classify_form_action_intent(self._gemini_client, query, erp_intent)

    async def _extract_form_fields_if_needed(
        self, query: str, visible_fields: list[str] | None, form_schema: list[dict] | None = None
    ) -> dict[str, Any]:
        return await extract_form_fields_if_needed(
            self._gemini_client, query, visible_fields, form_schema
        )

    async def search(self, req: SearchRequest, user_ctx: UserContext) -> SearchResponse:
        logger.info("Search started", query=req.query, scope=req.scope, user_entities_count=len(user_ctx.user_entities))
        metrics: dict[str, Any] = {}
        t0 = time.time()

        # 0. Fast Ingress: Intent Router (< 1ms bypass)
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

        # 1. Normalize query & check Tier-1 Exact Cache
        normalized_query = normalize_arabic_text_leaderboard(req.query)
        logger.debug("Query normalized for cache & embedding", original=req.query, normalized=normalized_query)

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
                        write_search_debug_file,
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
            record_exact_cache_lookup(hit=False)

        # 2. Embed → Dense + Sparse & check Tier-2 Semantic Cache
        t_embed = time.time()
        dense_vec, sparse_vec = await embedding_service.get_both_embeddings(normalized_query)
        embedding_duration = time.time() - t_embed
        metrics["embedding_latency_ms"] = round(embedding_duration * 1000, 2)
        record_stage_duration("embedding", embedding_duration)

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
                if settings.EXACT_CACHE_ENABLED:
                    exact_cache_service.store(normalized_query, cached_resp, user_ctx, req.scope_fingerprint)

                metrics["cache_hit"] = True
                metrics["cache_latency_ms"] = round(cache_duration * 1000, 2)
                metrics["total_latency_ms"] = round((time.time() - t0) * 1000, 2)
                record_stage_duration("total", time.time() - t0)
                logger.info("Serving from Semantic Cache", ms=metrics["total_latency_ms"])
                if settings.SEARCH_DEBUG_ENABLED:
                    await asyncio.to_thread(
                        write_search_debug_file,
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
            record_cache_lookup(hit=False)

        # 3. Hybrid Search & Reranking
        scope_filter = build_scope_filter(req)
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
                    write_search_debug_file,
                    query=req.query,
                    candidates=[],
                    reranked=[],
                    prompt="",
                    answer="لا تتوفر معلومات كافية في المحتوى المتاح حول هذا الموضوع.",
                    metrics=metrics,
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

        # 4. Build context & Invoke LangGraph
        valid_chunks = filter_valid_chunks(top_chunks)
        context_str = build_rag_context_str(valid_chunks)
        sources = build_source_items(valid_chunks)
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
            config=config,
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

        if settings.SEARCH_DEBUG_ENABLED:
            await asyncio.to_thread(
                write_search_debug_file,
                query=req.query,
                candidates=candidates,
                reranked=valid_chunks,
                prompt=returned_context.get("system_prompt_used", ""),
                answer=answer_text,
                metrics=metrics,
                token_usage=token_usage,
            )

        final_response = SearchResponse(
            answer=answer_text,
            sources=sources,
            query_used=req.query,
            provenance="RAG_GENERATION",
            cache_hit=False,
            latency_ms=metrics["total_latency_ms"],
        )

        # 5. Save in Exact Cache & Semantic Cache
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

    async def search_stream(
        self, req: SearchRequest, user_ctx: UserContext, request: Request
    ) -> AsyncIterator[str]:
        """Production-grade Server-Sent Events (SSE) streaming search & ERP action pipeline."""
        logger.info("Search stream started", query=req.query, scope=req.scope)
        t0 = time.time()

        # 0. Fast Ingress: Intent Router (< 1ms bypass)
        if settings.INTENT_ROUTER_ENABLED:
            t_stage = time.time()
            intent_res = intent_router.classify(req.query)
            record_stage_duration("intent_router", time.time() - t_stage)
            if intent_res.intent != IntentType.RAG_QUERY and intent_res.canned_response:
                if intent_res.intent == IntentType.SECURITY_VIOLATION:
                    record_guardrail_refusal("security_violation")
                record_stage_duration("total", time.time() - t0)
                latency_ms = round((time.time() - t0) * 1000, 2)
                yield format_sse("sources", {"sources": []})
                yield format_sse("token", {"text": intent_res.canned_response})
                yield format_sse("done", {
                    "intent": intent_res.intent.value,
                    "provenance": "INTENT_ROUTER",
                    "cache_hit": False,
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                })
                return

        # 1. Normalize Query & Check Exact Cache
        normalized_query = normalize_arabic_text_leaderboard(req.query)

        if settings.EXACT_CACHE_ENABLED and not req.skip_cache and not req.visible_fields and not req.form_schema:
            t_stage = time.time()
            exact_hit = exact_cache_service.lookup(normalized_query, user_ctx, req.scope_fingerprint)
            record_stage_duration("exact_cache", time.time() - t_stage)
            if exact_hit is not None:
                record_exact_cache_lookup(hit=True)
                record_stage_duration("total", time.time() - t0)
                latency_ms = round((time.time() - t0) * 1000, 2)
                yield format_sse("sources", {"sources": [s.model_dump() for s in exact_hit.sources]})
                yield format_sse("token", {"text": exact_hit.answer})
                yield format_sse("done", {
                    "cache_hit": True,
                    "cache_tier": "exact",
                    "provenance": "EXACT_CACHE",
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                })
                return
            record_exact_cache_lookup(hit=False)

        # 1.1b ERP Action Fast-Path
        if await self._classify_form_action_intent(req.query, req.erp_intent):
            (
                effective_fields,
                effective_schema,
                resolved_screen_key,
                resolved_page_id,
                resolved_doc_name,
            ) = resolve_and_enrich_erp_action_schema(
                req.query, req.visible_fields, req.form_schema, req.erp_key
            )

            if effective_fields or effective_schema:
                raw_extracted = await self._extract_form_fields_if_needed(
                    req.query, effective_fields, effective_schema
                )
                form_payload = build_form_fill_payload(
                    raw_extracted,
                    resolved_screen_key,
                    page_id=resolved_page_id,
                    document_name=resolved_doc_name,
                    schema=effective_schema,
                )
                if form_payload is not None:
                    record_stage_duration("total", time.time() - t0)
                    latency_ms = round((time.time() - t0) * 1000, 2)
                    logger.info(
                        "Emitting form_fill SSE event (action fast-path)",
                        fields=list(form_payload["fields"].keys()),
                        rows_count=len(form_payload["rows"]),
                        erp_key=resolved_screen_key,
                        page_id=resolved_page_id,
                    )
                    yield format_sse("sources", {"sources": []})
                    yield format_sse("form_fill", form_payload)
                    yield format_sse("token", {"text": FORM_FILL_CONFIRMATION})
                    yield format_sse("done", {
                        "thread_id": req.thread_id or str(uuid.uuid4()),
                        "provenance": "ERP_FORM_FILL",
                        "cache_hit": False,
                        "latency_ms": latency_ms,
                        "metrics": {"total_latency_ms": latency_ms},
                    })
                    return

            record_stage_duration("total", time.time() - t0)
            latency_ms = round((time.time() - t0) * 1000, 2)
            guide_msg = build_action_guide_message(
                effective_schema, effective_fields, resolved_doc_name, resolved_screen_key
            )
            logger.info("Emitting action guide SSE (pure action short-circuit)", erp_key=resolved_screen_key)
            yield format_sse("sources", {"sources": []})
            yield format_sse("token", {"text": guide_msg})
            yield format_sse("done", {
                "thread_id": req.thread_id or str(uuid.uuid4()),
                "provenance": "ERP_ACTION_GUIDE",
                "cache_hit": False,
                "latency_ms": latency_ms,
                "metrics": {"total_latency_ms": latency_ms},
            })
            return

        # 1.1c Pure Navigation Fast-Path (Only when not in pure Q&A mode)
        is_qa_only = (req.erp_intent or "").strip().lower() == "question"
        is_explicit_nav_query = bool(
            not is_qa_only
            and (req.visible_fields or req.form_schema or req.erp_key)
            and re.match(r"^\s*(اذهب|انتقل|افتح|وديني|روح)\s+", req.query)
        )
        if (req.erp_intent or "").strip().lower() == "navigate" or is_explicit_nav_query:
            record_stage_duration("total", time.time() - t0)
            latency_ms = round((time.time() - t0) * 1000, 2)
            logger.info("Emitting navigation confirmation SSE (navigate fast-path)", query=req.query)
            yield format_sse("sources", {"sources": []})
            yield format_sse("token", {"text": "✅ تم توجيهك إلى الشاشة المطلوبة في النظام."})
            yield format_sse("done", {
                "thread_id": req.thread_id or str(uuid.uuid4()),
                "provenance": "ERP_NAVIGATION",
                "cache_hit": False,
                "latency_ms": latency_ms,
                "metrics": {"total_latency_ms": latency_ms},
            })
            return

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
                yield format_sse("sources", {"sources": [s.model_dump() for s in cached_resp.sources]})
                yield format_sse("token", {"text": cached_resp.answer})
                yield format_sse("done", {
                    "cache_hit": True,
                    "cache_tier": "semantic",
                    "provenance": "SEMANTIC_CACHE",
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                })
                return
            record_cache_lookup(hit=False)

        # 2. Qdrant Hybrid Search & FlashRank Reranker
        t_vec = time.time()
        scope_filter = build_scope_filter(req)
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
            yield format_sse("sources", {"sources": []})
            yield format_sse("token", {"text": "لا تتوفر معلومات كافية في المحتوى المتاح حول هذا الموضوع."})
            yield format_sse("done", {
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

        valid_chunks = filter_valid_chunks(top_chunks)
        sources = build_source_items(valid_chunks)

        # Yield sources event first for immediate citation rendering in frontend
        yield format_sse("sources", {"sources": [s.model_dump() for s in sources]})

        # 3. Delegate Gemini SSE Streaming + Cache Persistence
        context_str = build_rag_context_str(valid_chunks)
        num_sources = len(valid_chunks) if valid_chunks else 1
        is_multi_lesson = bool(req.lesson_ids) or (req.scope in ("lessons", "multi_lesson"))

        async for sse_event in stream_gemini_rag_tokens(
            gemini_client=self._gemini_client,
            req=req,
            user_ctx=user_ctx,
            request=request,
            context_str=context_str,
            num_sources=num_sources,
            is_multi_lesson=is_multi_lesson,
            sources=sources,
            normalized_query=normalized_query,
            dense_vec=dense_vec,
            t0=t0,
            background_tasks=_background_tasks,
        ):
            yield sse_event


_background_tasks: set[asyncio.Task] = set()
search_service = SearchService()
