"""
Qdrant Service — Hybrid Search (Dense + Sparse)
================================================
Best Practices 2026:
- AsyncQdrantClient: لا يحجب الـ event loop.
- Collection تُنشأ مرة واحدة في lifespan بـ IF NOT EXISTS منطق.
- upsert بـ batch لتفادي ضغط الشبكة.
- Named vectors: "dense" + "sparse" — متوافق مع BGE-M3 + BM25.
- Payload indexes تُنشأ تلقائياً عند أول init.
"""

import uuid
import asyncio
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    VectorParams, Distance,
    SparseVectorParams, SparseIndexParams,
    PointStruct, SparseVector,
    Filter, FieldCondition, MatchAny,
    PayloadSchemaType,
    Prefetch, FusionQuery, Fusion,
)
from src.core.config import settings
from src.models.schemas import QdrantChunkPayload

logger = structlog.get_logger()

DENSE_DIM  = 1024      # BGE-M3 dense vector size
COLLECTION = settings.QDRANT_COLLECTION


class QdrantService:
    """
    مسؤولة عن: إنشاء الـ Collection، الـ upsert، والـ Hybrid Search.
    Lifecycle: initialize() يُستدعى مرة واحدة من lifespan.
    """

    def __init__(self) -> None:
        self._client: AsyncQdrantClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """ينشئ الـ client والـ collection عند startup."""
        self._client = AsyncQdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY or None,
            timeout=60,
        )
        await self._ensure_collection()
        await self._ensure_payload_indexes()
        logger.info("Qdrant service ready ✅", collection=COLLECTION)

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    # ------------------------------------------------------------------
    # Collection Setup (idempotent)
    # ------------------------------------------------------------------

    async def _ensure_collection(self) -> None:
        """ينشئ الـ collection إذا لم تكن موجودة — آمن للتكرار."""
        exists = await self._client.collection_exists(COLLECTION)  # type: ignore
        if exists:
            logger.info("Qdrant collection already exists", collection=COLLECTION)
            return

        await self._client.create_collection(  # type: ignore
            collection_name=COLLECTION,
            vectors_config={
                "dense": VectorParams(size=DENSE_DIM, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)
                ),
            },
        )
        logger.info("Qdrant collection created ✅", collection=COLLECTION)

    async def _ensure_payload_indexes(self) -> None:
        """ينشئ indexes على الحقول المستخدمة في الفلترة."""
        keyword_fields = [
            "allowed_entities", "target_roles", "content_type",
            "tenant_id", "lesson_id", "module_id", "unit_id",
            "video_id", "playlist_id",
        ]
        for field in keyword_fields:
            await self._client.create_payload_index(  # type: ignore
                collection_name=COLLECTION,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        logger.info("Qdrant payload indexes ensured ✅")

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def upsert_chunks(
        self,
        payloads: list[QdrantChunkPayload],
        dense_vectors: list[list[float]],
        sparse_vectors: list,          # list[SparseEmbedding] from fastembed
    ) -> None:
        """
        يرفع مجموعة من النقاط دفعة واحدة (batch upsert).
        dense_vectors[i] و sparse_vectors[i] مرتبطان بـ payloads[i].
        """
        assert self._client is not None, "QdrantService not initialized"

        points = [
            PointStruct(
                id=str(uuid.uuid4()),
                vector={
                    "dense": dense_vectors[i],
                    "sparse": SparseVector(
                        indices=sparse_vectors[i].indices.tolist(),
                        values=sparse_vectors[i].values.tolist(),
                    ),
                },
                payload=payloads[i].model_dump(),
            )
            for i in range(len(payloads))
        ]

        await self._client.upsert(collection_name=COLLECTION, points=points)  # type: ignore
        logger.info("Qdrant upsert complete", count=len(points))

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete_by_lesson_id(self, lesson_id: str) -> None:
        """يحذف كل نقاط درس معين — يُستخدم عند Webhook 'Deleted'."""
        assert self._client is not None
        from qdrant_client.models import FilterSelector
        await self._client.delete(  # type: ignore
            collection_name=COLLECTION,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="lesson_id", match=MatchAny(any=[lesson_id]))]
                )
            ),
        )
        logger.info("Qdrant: deleted chunks for lesson", lesson_id=lesson_id)

    # ------------------------------------------------------------------
    # Hybrid Search (RRF Fusion)
    # ------------------------------------------------------------------

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector,                  # SparseEmbedding
        user_entities: list[str],
        limit: int = 60,
        extra_filter: Filter | None = None,
    ) -> list[dict]:
        """
        بحث هجين (Dense + Sparse) مع RRF fusion وفلترة الصلاحيات.

        Returns:
            قائمة من payload dicts مرتبة بـ RRF score.
        """
        assert self._client is not None

        # فلتر الصلاحيات الأساسي
        auth_filter = Filter(
            must=[
                FieldCondition(
                    key="allowed_entities",
                    match=MatchAny(any=user_entities),
                )
            ]
        )

        # دمج الفلتر الإضافي (scope, module_id, ...) إذا وُجد
        if extra_filter and extra_filter.must:
            auth_filter.must.extend(extra_filter.must)  # type: ignore

        results = await self._client.query_points(  # type: ignore
            collection_name=COLLECTION,
            prefetch=[
                Prefetch(
                    query=dense_vector,
                    using="dense",
                    filter=auth_filter,
                    limit=limit,
                ),
                Prefetch(
                    query=SparseVector(
                        indices=sparse_vector.indices.tolist(),
                        values=sparse_vector.values.tolist(),
                    ),
                    using="sparse",
                    filter=auth_filter,
                    limit=limit,
                ),
            ],
            query=FusionQuery(fusion=Fusion.RRF),
            limit=limit,
            with_payload=True,
        )

        payloads = []
        for point in results.points:
            if point.payload is not None:
                point.payload["_qdrant_point_id"] = str(point.id)
                payloads.append(point.payload)
        return payloads


# Singleton — initialize() يُستدعى من lifespan
qdrant_service = QdrantService()
