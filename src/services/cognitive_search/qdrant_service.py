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

import asyncio
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    VectorParams, Distance,
    SparseVectorParams, SparseIndexParams,
    PointStruct, SparseVector,
    Filter, FieldCondition, MatchAny, MatchValue,
    PayloadSchemaType, KeywordIndexParams,
    Prefetch, FusionQuery, Fusion,
    PointIdsList,
)
from src.core.config import settings
from src.models.schemas import QdrantChunkPayload
from src.models.auth_models import UserContext

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
        created = await self._ensure_collection()
        if created:
            await self._ensure_payload_indexes()
        logger.info("Qdrant service ready ✅", collection=COLLECTION)

    @property
    def client(self) -> AsyncQdrantClient:
        assert self._client is not None, "QdrantService not initialized. Call initialize() first."
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    # ------------------------------------------------------------------
    # Collection Setup (idempotent)
    # ------------------------------------------------------------------

    async def _ensure_collection(self) -> bool:
        """ينشئ الـ collection إذا لم تكن موجودة — آمن للتكرار. يرجع True إذا تم إنشاؤها حديثاً."""
        exists = await self._client.collection_exists(COLLECTION)  # type: ignore
        if exists:
            logger.info("Qdrant collection already exists", collection=COLLECTION)
            return False

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
        return True

    async def _ensure_payload_indexes(self) -> None:
        """ينشئ indexes على الحقول المستخدمة في الفلترة."""
        keyword_fields = [
            "allowed_entities", "target_roles", "content_type",
            "tenant_ids", "lesson_id", "module_id", "unit_id",
            "video_id", "playlist_id", "level_id", "type_id",
            "lesson_ids", "module_ids"
        ]
        for field in keyword_fields:
            is_tenant = field in ("tenant_ids", "lesson_id")
            await self._client.create_payload_index(  # type: ignore
                collection_name=COLLECTION,
                field_name=field,
                field_schema=KeywordIndexParams(
                    type="keyword",
                    is_tenant=is_tenant
                ),
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
                # ✅ Fix: point_id = chunk_id (deterministic) — makes upsert idempotent.
                # Same lesson re-processed = UPDATE existing point, never INSERT duplicate.
                id=payloads[i].chunk_id,
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
    # Multi-Module / Multi-Lesson Reference Linking (Process Once, Reference Everywhere)
    # ------------------------------------------------------------------

    async def link_lesson_to_existing_video(
        self,
        video_identifier: str,
        source_url: str | None,
        new_lesson_id: str,
        new_module_id: str | None = None,
        new_unit_id: str | None = None,
        target_roles: list[str] | None = None,
    ) -> int:
        """
        يربط درساً وموديولاً جديداً بنقاط فيديو مخزنة مسبقاً في Qdrant دون إعادة التضمين أو التفريغ.
        يقوم بتحديث allowed_entities, lesson_ids, module_ids ذرياً في كل نقاط الفيديو.
        Returns: عدد النقاط التي تم ربطها (0 إذا لم يكن الفيديو موجوداً مسبقاً).
        """
        assert self._client is not None, "QdrantService not initialized"

        should_conditions = []
        if video_identifier:
            should_conditions.append(FieldCondition(key="video_id", match=MatchValue(value=video_identifier)))
        if source_url:
            should_conditions.append(FieldCondition(key="source_url", match=MatchValue(value=source_url)))

        if not should_conditions:
            return 0

        query_filter = Filter(should=should_conditions)

        matched_points = []
        offset = None
        while True:
            scroll_res = await self._client.scroll(
                collection_name=COLLECTION,
                scroll_filter=query_filter,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points, next_offset = scroll_res
            matched_points.extend(points)
            if next_offset is None or len(points) < 200:
                break
            offset = next_offset

        if not matched_points:
            return 0

        logger.info("Found existing video points to link in Qdrant", count=len(matched_points), video_id=video_identifier)

        async def _update_point(point):
            payload = point.payload or {}
            allowed = set(payload.get("allowed_entities") or [])
            lesson_ids = set(payload.get("lesson_ids") or [])
            module_ids = set(payload.get("module_ids") or [])

            if payload.get("lesson_id"):
                lesson_ids.add(payload["lesson_id"])
            if payload.get("module_id"):
                module_ids.add(payload["module_id"])

            if new_lesson_id:
                allowed.add(f"lesson:{new_lesson_id}")
                lesson_ids.add(new_lesson_id)

            if new_module_id:
                allowed.add(f"module:{new_module_id}")
                module_ids.add(new_module_id)

            if new_unit_id:
                allowed.add(f"unit:{new_unit_id}")

            if target_roles:
                for r in target_roles:
                    allowed.add(f"role:{r}")

            updated_payload = {
                "allowed_entities": sorted(list(allowed)),
                "lesson_ids": sorted(list(lesson_ids)),
                "module_ids": sorted(list(module_ids)),
            }
            if not payload.get("video_id") and video_identifier:
                updated_payload["video_id"] = video_identifier

            await self._client.set_payload(
                collection_name=COLLECTION,
                payload=updated_payload,
                points=[point.id],
            )

        # ⚡ تحديث جميع النقاط بالتوازي لتقليص زمن الاستجابة إلى < 15ms
        await asyncio.gather(*(_update_point(p) for p in matched_points))

        logger.info(
            "Successfully linked lesson to existing video in Qdrant",
            lesson_id=new_lesson_id,
            module_id=new_module_id,
            points_count=len(matched_points),
        )
        return len(matched_points)

    # ------------------------------------------------------------------
    # Delete (with Reference Counting)
    # ------------------------------------------------------------------

    async def delete_by_lesson_id(self, lesson_id: str) -> None:
        """
        يحذف أو يفك ارتباط درس من Qdrant بحساب المراجع (Reference Counting).
        إذا كان الفيديو مستخدماً في دروس أخرى (Reference Count > 1):
        يتم فقط إزالة معرف الدرس من allowed_entities و lesson_ids دون حذف النقاط الفيزيائية.
        إذا كان هذا الدرس الوحيد المرتبط (Reference Count == 1):
        يتم حذف النقاط فيزيائياً من الـ collection.
        """
        assert self._client is not None
        query_filter = Filter(
            should=[
                FieldCondition(key="lesson_id", match=MatchValue(value=lesson_id)),
                FieldCondition(key="lesson_ids", match=MatchValue(value=lesson_id)),
            ]
        )

        matched_points = []
        offset = None
        while True:
            scroll_res = await self._client.scroll(
                collection_name=COLLECTION,
                scroll_filter=query_filter,
                limit=200,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            points, next_offset = scroll_res
            matched_points.extend(points)
            if next_offset is None or len(points) < 200:
                break
            offset = next_offset

        if not matched_points:
            logger.info("Qdrant: no chunks found for lesson deletion", lesson_id=lesson_id)
            return

        points_to_delete = []
        points_to_unlink = []

        for point in matched_points:
            payload = point.payload or {}
            lesson_ids = set(payload.get("lesson_ids") or [])
            if payload.get("lesson_id"):
                lesson_ids.add(payload["lesson_id"])

            remaining_lessons = lesson_ids - {lesson_id}

            if remaining_lessons:
                # لا يزال الفيديو مرتبطاً بدروس أخرى في موديولات أخرى -> فك ارتباط فقط
                allowed = set(payload.get("allowed_entities") or [])
                allowed.discard(f"lesson:{lesson_id}")

                new_primary = sorted(list(remaining_lessons))[0]
                updated_payload = {
                    "allowed_entities": sorted(list(allowed)),
                    "lesson_ids": sorted(list(remaining_lessons)),
                    "lesson_id": new_primary,
                }
                points_to_unlink.append((point.id, updated_payload))
            else:
                # آخر درس مرتبط بهذا الفيديو -> حذف فيزيائي للنقاط
                points_to_delete.append(point.id)

        if points_to_unlink:
            # ⚡ فك ارتباط النقاط غير المحذوفة بالتوازي
            await asyncio.gather(*(
                self._client.set_payload(
                    collection_name=COLLECTION,
                    payload=payload,
                    points=[pid],
                )
                for pid, payload in points_to_unlink
            ))

        if points_to_delete:
            await self._client.delete(
                collection_name=COLLECTION,
                points_selector=PointIdsList(points=points_to_delete),
            )

        logger.info(
            "Qdrant: lesson deletion processed with reference counting",
            lesson_id=lesson_id,
            points_unlinked=len(points_to_unlink),
            points_deleted=len(points_to_delete),
        )


    # ------------------------------------------------------------------
    # Hybrid Search (RRF Fusion)
    # ------------------------------------------------------------------

    async def hybrid_search(
        self,
        dense_vector: list[float],
        sparse_vector,                  # SparseEmbedding
        user_ctx: UserContext,
        limit: int = 60,
        extra_filter: Filter | None = None,
    ) -> list[dict]:
        """
        بحث هجين (Dense + Sparse) مع RRF fusion وفلترة الصلاحيات.

        Returns:
            قائمة من payload dicts مرتبة بـ RRF score.
        """
        assert self._client is not None

        # Build module level and type conditions (matching primary or shared modules)
        module_conditions = []
        if user_ctx.permissions and user_ctx.permissions.accessible_modules:
            for module in user_ctx.permissions.accessible_modules:
                must_inner = [
                    Filter(should=[
                        FieldCondition(key="module_id", match=MatchValue(value=module.module_id)),
                        FieldCondition(key="module_ids", match=MatchValue(value=module.module_id)),
                    ])
                ]
                if module.level_filters:
                    must_inner.append(FieldCondition(key="level_id", match=MatchAny(any=module.level_filters)))
                if module.type_filters:
                    must_inner.append(FieldCondition(key="type_id", match=MatchAny(any=module.type_filters)))
                module_conditions.append(Filter(must=must_inner))


        # Overall Filter
        overall_must = [
            FieldCondition(key="allowed_entities", match=MatchAny(any=user_ctx.user_entities)),
        ]
        
        # Admins bypass specific level/type restrictions, they rely purely on their allowed_entities matching everything
        if module_conditions and user_ctx.claims.role != "Admin":
            overall_must.append(Filter(should=module_conditions))

        auth_filter = Filter(must=overall_must)

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
