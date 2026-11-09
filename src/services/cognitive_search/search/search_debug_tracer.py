"""
Diagnostic Search Debug Tracer Module.
Persists structured JSON trace logs to `downloads/search_debugs/` when `SEARCH_DEBUG_ENABLED` is active.
"""

from datetime import datetime, timezone
import json
import os
import structlog
from src.core.config import settings

logger = structlog.get_logger()


def write_search_debug_file(
    query: str,
    candidates: list[dict],
    reranked: list[dict],
    prompt: str,
    answer: str,
    metrics: dict | None = None,
    token_usage: dict | None = None,
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
                "source_url": c.get("source_url"),
            }
            for c in candidates
        ],
        "reranker_results": [
            {
                "point_id": r.get("_qdrant_point_id"),
                "chunk_id": r.get("chunk_id"),
                "content_type": r.get("content_type"),
                "text_msa": r.get("text_msa"),
                "source_url": r.get("source_url"),
                "reranker_score": r.get("_reranker_score"),
            }
            for r in reranked
        ],
        "prompt_sent_to_gemini": prompt,
        "gemini_answer": answer,
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(debug_data, f, ensure_ascii=False, indent=4)
    logger.info("Search debug file written", path=file_path)

