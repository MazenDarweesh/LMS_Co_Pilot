import asyncio
import os
import json
import time
from datetime import datetime
import structlog
from google import genai
from google.genai import types
from src.core.config import settings
from src.models.search_models import SearchRequest, SearchResponse, SourceItem
from src.services.embedding_service import embedding_service
from src.services.qdrant_service import qdrant_service
from src.services.reranker_service import reranker_service
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
        
    # 2. Scope ID Filtering
    if req.lesson_id:
        must.append(FieldCondition(key="lesson_id", match=MatchValue(value=req.lesson_id)))
    if req.unit_id:
        must.append(FieldCondition(key="unit_id", match=MatchValue(value=req.unit_id)))
    if req.module_id:
        must.append(FieldCondition(key="module_id", match=MatchValue(value=req.module_id)))
    if req.playlist_id:
        must.append(FieldCondition(key="playlist_id", match=MatchValue(value=req.playlist_id)))
    if req.video_id:
        must.append(FieldCondition(key="video_id", match=MatchValue(value=req.video_id)))
        
    return Filter(must=must) if must else None

def _build_rag_prompt(query: str, chunks: list[dict]) -> str:
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

    context_str = "\n\n".join(context_blocks)
    return f"""أنت مساعد تعليمي ذكي متخصص في الإجابة عن أسئلة الطلاب باللغة العربية الفصحى.

## التعليمات:
- أجب **حصراً** بناءً على المقاطع المُقدَّمة أدناه.
- استشهد بالمصادر برقمها [1] [2] في نهاية كل جملة مستنِدة إلى مصدر.

## سؤال الطالب:
{query}

## المقاطع التعليمية المسترجعة:
{context_str}

## الإجابة:"""

def _write_search_debug_file(
    query: str, 
    candidates: list[dict], 
    reranked: list[dict], 
    prompt: str, 
    answer: str,
    metrics: dict | None = None,
    token_usage: dict | None = None
) -> None:
    """حفظ تفاصيل عملية البحث بالكامل في ملف JSON منفصل في مجلد downloads/search_debugs/"""
    debug_dir = "downloads/search_debugs"
    os.makedirs(debug_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_path = os.path.join(debug_dir, f"search_{timestamp}.json")
    
    debug_data = {
        "timestamp": datetime.now().isoformat(),
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

class SearchService:
    def __init__(self):
        self._gemini_client = None

    def initialize(self):
        self._gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def search(self, req: SearchRequest, user_entities: list[str]) -> SearchResponse:
        logger.info("Search started", query=req.query, scope=req.scope, user_entities_count=len(user_entities))
        metrics = {}
        
        t0 = time.time()
        # ──────────────────────────────────────────────
        # 1. Normalize query → Embed → Dense + Sparse
        # ──────────────────────────────────────────────
        # 2026 Best Practice (Arabic Speech AI Research §13.6 & §17):
        # Apply Leaderboard-standard normalization to the query BEFORE embedding.
        # This closes the semantic gap between colloquial student queries
        # (e.g. "إزاي أعمل الـ Database؟") and MSA-normalized indexed text,
        # which directly improves Cosine Similarity accuracy in Qdrant.
        normalized_query = normalize_arabic_text_leaderboard(req.query)
        logger.debug("Query normalized for embedding", original=req.query, normalized=normalized_query)
        dense_vec, sparse_vec = await embedding_service.get_both_embeddings(normalized_query)
        metrics["embedding_latency_ms"] = round((time.time() - t0) * 1000, 2)

        scope_filter = _build_scope_filter(req)

        t1 = time.time()
        candidates = await qdrant_service.hybrid_search(
            dense_vector=dense_vec,
            sparse_vector=sparse_vec,
            user_entities=user_entities,
            limit=60,
            extra_filter=scope_filter,
        )
        metrics["qdrant_latency_ms"] = round((time.time() - t1) * 1000, 2)

        if not candidates:
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
            )

        logger.info("Qdrant candidates returned", count=len(candidates), ms=metrics["qdrant_latency_ms"])

        t2 = time.time()
        top_chunks = await reranker_service.rerank(
            query=req.query,
            passages=candidates,
            top_n=min(req.limit, 10),
            text_field="text_msa",
        )
        metrics["reranker_latency_ms"] = round((time.time() - t2) * 1000, 2)
        logger.info("Reranked results", top_n=len(top_chunks), ms=metrics["reranker_latency_ms"])

        # ──────────────────────────────────────────────
        # 5. Build prompt with tagged sources
        # ──────────────────────────────────────────────
        # Note: we pass the ORIGINAL query to the LLM prompt (not the normalized one)
        # so Gemini can understand the student's intent in their own words.
        prompt = _build_rag_prompt(req.query, top_chunks)

        assert self._gemini_client is not None
        t3 = time.time()
        response = await asyncio.to_thread(
            self._gemini_client.models.generate_content,
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=1024),
        )
        metrics["gemini_latency_ms"] = round((time.time() - t3) * 1000, 2)
        metrics["total_latency_ms"] = round((time.time() - t0) * 1000, 2)
        
        answer_text = response.text.strip()
        logger.info("Gemini answer generated", answer_length=len(answer_text), ms=metrics["gemini_latency_ms"])

        token_usage = {}
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            token_usage = {
                "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
                "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
                "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
            }

        # Write trace log file asynchronously
        await asyncio.to_thread(
            _write_search_debug_file,
            query=req.query,
            candidates=candidates,
            reranked=top_chunks,
            prompt=prompt,
            answer=answer_text,
            metrics=metrics,
            token_usage=token_usage
        )

        sources = []
        for chunk in top_chunks:
            c_type = chunk.get("content_type")
            if c_type in ["video_chunk", "standalone_video_chunk", "playlist_video_chunk"] and chunk.get("source_url"):
                sources.append(SourceItem(
                    type="video",
                    url=chunk["source_url"],
                    start=chunk.get("start_time"),
                    end=chunk.get("end_time"),
                ))
            elif c_type == "pdf_chunk":
                sources.append(SourceItem(
                    type="pdf",
                    page=chunk.get("page_number"),
                    section=chunk.get("section_title"),
                ))

        return SearchResponse(answer=answer_text, sources=sources, query_used=req.query)

search_service = SearchService()
