"""
Cognitive Search Domain Services (Agentic & Cognitive-Oriented Subsystem).
========================================================================
Contains services powering hybrid vector retrieval, dense/sparse embeddings,
quantized cross-encoder reranking, semantic and exact LRU caching,
intent routing, and conversational RAG generation.
"""

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

__all__ = [
    "EmbeddingService",
    "embedding_service",
    "QdrantService",
    "qdrant_service",
    "COLLECTION",
    "DENSE_DIM",
    "RerankerService",
    "reranker_service",
    "ExactCacheService",
    "exact_cache_service",
    "CachedEntry",
    "SemanticCacheService",
    "semantic_cache_service",
    "IntentRouterService",
    "intent_router",
    "IntentType",
    "IntentResult",
    "_normalize_arabizi_and_text",
    "SearchService",
    "search_service",
    "_build_scope_filter",
    "_filter_valid_chunks",
    "_build_rag_context_str",
    "_build_source_items",
    "_trim_messages",
    "_write_search_debug_file",
    "_format_sse",
    "_build_form_fill_payload",
    "_build_schema_from_catalog",
    "RAGService",
    "rag_service",
]
