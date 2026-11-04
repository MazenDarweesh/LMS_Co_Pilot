"""
RAG Service — Thin wrapper over SearchService for backward compatibility.
=========================================================================
The original /query-rag endpoint uses this service.
Now it delegates to the real SearchService with a test-friendly UserContext.
When Week 7 (Auth) is implemented, this wrapper will be replaced by
direct usage of search_service from authenticated endpoints.
"""

import structlog
from src.models.schemas import RAGQueryResponse
from src.models.search_models import SearchRequest
from src.services.search_service import search_service

logger = structlog.get_logger()


class RAGService:
    async def query_rag(self, query: str, limit: int) -> RAGQueryResponse:
        """
        Unauthenticated RAG query — for development/testing only.
        Uses broad tenant access (default_company + Admin role).
        """
        req = SearchRequest(query=query, limit=limit)

        # Temporary test context — bypasses auth for quick testing
        from src.models.auth_models import UserContext, TokenClaims, UserPermissions
        dummy_ctx = UserContext(
            claims=TokenClaims(Id="admin123", Username="admin", Role="Admin", CompanyId="default_company"),
            permissions=UserPermissions(userId="admin123"),
            user_entities=[
                "tenant:default_company",
                "role:Admin",
                "role:Student",
            ]
        )

        result = await search_service.search(req, user_ctx=dummy_ctx)

        return RAGQueryResponse(
            answer=result.answer,
            sources=[s.url or f"PDF p.{s.page}" for s in result.sources if s.url or s.page],
        )


rag_service = RAGService()
