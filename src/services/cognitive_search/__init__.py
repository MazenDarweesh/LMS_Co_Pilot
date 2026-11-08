"""
Cognitive Search Domain Services (Agentic & Cognitive-Oriented Subsystem).
========================================================================
Contains services powering hybrid vector retrieval, dense/sparse embeddings,
quantized cross-encoder reranking, semantic and exact LRU caching,
intent routing, and conversational RAG generation.

Uses PEP 562 lazy attribute loading (__getattr__) so importing a single lightweight
submodule (e.g. exact_cache_service or intent_router) never eagerly loads heavy ML
dependencies (torch, sentence_transformers, fastembed, vertexai) unless accessed.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.services.cognitive_search.embedding_service import (
        EmbeddingService,
        embedding_service,
    )
    from src.services.cognitive_search.exact_cache_service import (
        CachedEntry,
        ExactCacheService,
        exact_cache_service,
    )
    from src.services.cognitive_search.intent_router import (
        IntentResult,
        IntentRouterService,
        IntentType,
        _normalize_arabizi_and_text,
        intent_router,
    )
    from src.services.cognitive_search.qdrant_service import (
        COLLECTION,
        DENSE_DIM,
        QdrantService,
        qdrant_service,
    )
    from src.services.cognitive_search.rag_service import (
        RAGService,
        rag_service,
    )
    from src.services.cognitive_search.reranker_service import (
        RerankerService,
        reranker_service,
    )
    from src.services.cognitive_search.search_service import (
        SearchService,
        _build_form_fill_payload,
        _build_rag_context_str,
        _build_schema_from_catalog,
        _build_scope_filter,
        _build_source_items,
        _filter_valid_chunks,
        _format_sse,
        _trim_messages,
        _write_search_debug_file,
        search_service,
    )
    from src.services.cognitive_search.semantic_cache_service import (
        SemanticCacheService,
        semantic_cache_service,
    )

_LAZY_ATTR_MAP: dict[str, str] = {
    "EmbeddingService": "src.services.cognitive_search.embedding_service",
    "embedding_service": "src.services.cognitive_search.embedding_service",
    "QdrantService": "src.services.cognitive_search.qdrant_service",
    "qdrant_service": "src.services.cognitive_search.qdrant_service",
    "COLLECTION": "src.services.cognitive_search.qdrant_service",
    "DENSE_DIM": "src.services.cognitive_search.qdrant_service",
    "RerankerService": "src.services.cognitive_search.reranker_service",
    "reranker_service": "src.services.cognitive_search.reranker_service",
    "ExactCacheService": "src.services.cognitive_search.exact_cache_service",
    "exact_cache_service": "src.services.cognitive_search.exact_cache_service",
    "CachedEntry": "src.services.cognitive_search.exact_cache_service",
    "SemanticCacheService": "src.services.cognitive_search.semantic_cache_service",
    "semantic_cache_service": "src.services.cognitive_search.semantic_cache_service",
    "IntentRouterService": "src.services.cognitive_search.intent_router",
    "intent_router": "src.services.cognitive_search.intent_router",
    "IntentType": "src.services.cognitive_search.intent_router",
    "IntentResult": "src.services.cognitive_search.intent_router",
    "_normalize_arabizi_and_text": "src.services.cognitive_search.intent_router",
    "SearchService": "src.services.cognitive_search.search_service",
    "search_service": "src.services.cognitive_search.search_service",
    "_build_scope_filter": "src.services.cognitive_search.search_service",
    "_filter_valid_chunks": "src.services.cognitive_search.search_service",
    "_build_rag_context_str": "src.services.cognitive_search.search_service",
    "_build_source_items": "src.services.cognitive_search.search_service",
    "_trim_messages": "src.services.cognitive_search.search_service",
    "_write_search_debug_file": "src.services.cognitive_search.search_service",
    "_format_sse": "src.services.cognitive_search.search_service",
    "_build_form_fill_payload": "src.services.cognitive_search.search_service",
    "_build_schema_from_catalog": "src.services.cognitive_search.search_service",
    "RAGService": "src.services.cognitive_search.rag_service",
    "rag_service": "src.services.cognitive_search.rag_service",
}

__all__ = list(_LAZY_ATTR_MAP.keys())


def __getattr__(name: str) -> Any:
    module_path = _LAZY_ATTR_MAP.get(name)
    if module_path is not None:
        mod = import_module(module_path)
        for attr_name, attr_mod in _LAZY_ATTR_MAP.items():
            if attr_mod == module_path:
                globals()[attr_name] = getattr(mod, attr_name)
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
