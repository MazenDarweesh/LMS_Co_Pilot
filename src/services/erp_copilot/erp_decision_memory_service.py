"""
ERP Decision Memory Service — Verified AI Routing Decisions (Qdrant lookup + PostgreSQL audit)
==============================================================================================
Why: screen/intent routing is decided by the AI router. Once a decision is *verified by the user*
(the form-fill card was applied successfully, or the navigation succeeded) it is remembered, so that the
same / paraphrased command can skip the LLM call entirely next time.

Two stores, one responsibility each (no duplicated logic):
- Qdrant collection `erp_decisions`  → semantic LOOKUP (verified decisions only, tenant + candidate-set scoped).
- PostgreSQL table `erp_routing_audit` → AUDIT trail of every routing decision (pending/applied/rejected)
  and persistent store for AI-resolved button roles (kind='controls').

Safety rules:
- Only decisions confirmed with outcome=applied enter the vector store (never raw AI guesses).
- Lookup is filtered by tenant_id AND candidate fingerprint → a decision silently expires when the ERP
  gains/loses screens, and tenants never see each other's decisions.
- A `rejected` outcome deletes the remembered point (self-healing).
- Every failure is logged and degrades to "no memory" — routing itself never breaks.
"""

import hashlib
import time
import uuid

import asyncpg
import structlog
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    IntegerIndexParams,
    KeywordIndexParams,
    MatchValue,
    PointIdsList,
    PointStruct,
    Range,
    VectorParams,
)

from src.core.config import settings
from src.models.erp_models import NavCandidateIn, NavResolution
from src.services.embedding_service import embedding_service
from src.services.qdrant_service import qdrant_service

logger = structlog.get_logger()

_KIND_NAVIGATION = "navigation"
_KIND_CONTROLS = "controls"


def candidate_fingerprint(items: list[tuple[str, str]]) -> str:
    """Stable hash of the (id, label) pairs offered to the AI. Changes whenever the ERP UI changes."""
    canonical = "|".join(sorted(f"{i}:{label}" for i, label in items))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def navigation_fingerprint(candidates: list[NavCandidateIn]) -> str:
    return candidate_fingerprint([(c.id, c.label) for c in candidates])


class ErpDecisionMemoryService:
    def __init__(self) -> None:
        self.collection_name = settings.ERP_DECISION_COLLECTION
        self.min_score = settings.ERP_DECISION_MIN_SCORE
        self.ttl_seconds = settings.ERP_DECISION_TTL_DAYS * 86400
        self.enabled = settings.ERP_DECISION_MEMORY_ENABLED
        self._pool: asyncpg.Pool | None = None

    @property
    def ready(self) -> bool:
        return self.enabled and self._pool is not None

    async def initialize(self, pool: asyncpg.Pool) -> None:
        """Binds the PostgreSQL pool and ensures the Qdrant collection + payload indexes exist."""
        self._pool = pool
        if not self.enabled:
            logger.info("ERP decision memory is disabled in settings")
            return
        client = qdrant_service.client
        if not await client.collection_exists(self.collection_name):
            await client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            )
            for field in ("tenant_id", "fingerprint"):
                await client.create_payload_index(
                    collection_name=self.collection_name,
                    field_name=field,
                    field_schema=KeywordIndexParams(type="keyword"),
                )
            await client.create_payload_index(
                collection_name=self.collection_name,
                field_name="verified_at_ts",
                field_schema=IntegerIndexParams(type="integer"),
            )
            logger.info("ERP decision collection created", collection=self.collection_name)
        logger.info("ERP decision memory ready ✅", collection=self.collection_name)

    # ── Navigation decisions (Qdrant lookup + SQL audit) ─────────────────────

    async def lookup_navigation(
        self, query: str, tenant_id: str, fingerprint: str
    ) -> tuple[NavResolution, str] | None:
        """Returns (resolution, matched_point_id) for a verified, similar past command; else None."""
        if not self.ready:
            return None
        try:
            vector = await embedding_service.get_dense_embedding(query)
            cutoff = int(time.time()) - self.ttl_seconds
            results = await qdrant_service.client.query_points(
                collection_name=self.collection_name,
                query=vector,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
                        FieldCondition(key="fingerprint", match=MatchValue(value=fingerprint)),
                        FieldCondition(key="verified_at_ts", range=Range(gte=cutoff)),
                    ]
                ),
                limit=1,
                score_threshold=self.min_score,
                with_payload=True,
            )
            if not results.points:
                return None
            hit = results.points[0]
            resolution = NavResolution.model_validate((hit.payload or {})["resolution"])
            logger.info("ERP decision memory HIT", score=round(hit.score, 4), point_id=str(hit.id))
            return resolution.model_copy(update={"source": "memory", "decision_id": None}), str(hit.id)
        except Exception as e:
            logger.warning("ERP decision memory lookup failed; falling back to AI router", error=str(e))
            return None

    async def record_navigation(
        self,
        tenant_id: str,
        user_id: str,
        query: str,
        fingerprint: str,
        resolution: NavResolution,
        matched_point_id: str | None = None,
    ) -> str | None:
        """Writes a pending audit row and returns its decision_id (used later for feedback)."""
        if not self.ready:
            return None
        top_id = resolution.candidates[0].id if resolution.candidates else None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    INSERT INTO erp_routing_audit
                        (tenant_id, user_id, kind, query_text, screen_id, fingerprint,
                         intent, source, decision, matched_point_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    RETURNING id
                    """,
                    tenant_id, user_id, _KIND_NAVIGATION, query, top_id, fingerprint,
                    resolution.intent, resolution.source, resolution.model_dump(mode="json"),
                    matched_point_id,
                )
            return str(row["id"])
        except Exception as e:
            logger.warning("Failed to write ERP routing audit row", error=str(e), tenant_id=tenant_id)
            return None

    async def apply_feedback(self, tenant_id: str, decision_id: str, outcome: str) -> bool:
        """
        applied  → mark verified and (re)store the decision in the vector memory.
        rejected → mark rejected and evict the remembered point(s).
        Returns False if the decision does not exist for this tenant.
        """
        if not self.ready:
            return False
        try:
            decision_uuid = uuid.UUID(decision_id)
        except ValueError:
            logger.warning("Invalid ERP decision_id received", decision_id=decision_id)
            return False

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE erp_routing_audit SET outcome = $3, updated_at = NOW()
                WHERE id = $1 AND tenant_id = $2 AND kind = $4
                RETURNING query_text, fingerprint, decision, source, matched_point_id
                """,
                decision_uuid, tenant_id, outcome, _KIND_NAVIGATION,
            )
        if row is None:
            return False

        try:
            if outcome == "applied":
                await self._remember(decision_id, tenant_id, row)
            else:
                point_ids = [decision_id] + ([row["matched_point_id"]] if row["matched_point_id"] else [])
                await qdrant_service.client.delete(
                    collection_name=self.collection_name,
                    points_selector=PointIdsList(points=point_ids),
                )
                logger.info("ERP decision evicted after rejection", decision_id=decision_id)
        except Exception as e:
            logger.warning("ERP decision memory update failed", error=str(e), outcome=outcome)
        return True

    async def _remember(self, decision_id: str, tenant_id: str, row: asyncpg.Record) -> None:
        resolution = NavResolution.model_validate(row["decision"])
        # Only actionable, confident decisions are worth remembering.
        if resolution.decision != "go" or resolution.intent not in ("action", "navigate"):
            return
        # A memory hit that was applied again keeps its original point id.
        point_id = row["matched_point_id"] or decision_id
        vector = await embedding_service.get_dense_embedding(row["query_text"])
        await qdrant_service.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=point_id,
                    vector=vector,
                    payload={
                        "tenant_id": tenant_id,
                        "fingerprint": row["fingerprint"],
                        "query": row["query_text"],
                        "resolution": resolution.model_copy(update={"decision_id": None}).model_dump(mode="json"),
                        "verified_at_ts": int(time.time()),
                    },
                )
            ],
        )
        logger.info("ERP decision remembered ✅", point_id=point_id, intent=resolution.intent)

    # ── Control roles (SQL only: exact fingerprint, label based) ─────────────

    async def lookup_controls(self, tenant_id: str, screen_id: str, fingerprint: str) -> dict[str, str] | None:
        """Returns {role: button_label} previously resolved for this exact set of buttons."""
        if not self.ready:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    """
                    SELECT decision FROM erp_routing_audit
                    WHERE tenant_id = $1 AND kind = $2 AND screen_id = $3 AND fingerprint = $4
                      AND outcome <> 'rejected'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    tenant_id, _KIND_CONTROLS, screen_id, fingerprint,
                )
            return dict(row["decision"]) if row else None
        except Exception as e:
            logger.warning("ERP control roles lookup failed", error=str(e))
            return None

    async def save_controls(
        self, tenant_id: str, user_id: str, screen_id: str, fingerprint: str, roles_by_label: dict[str, str]
    ) -> None:
        if not self.ready:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO erp_routing_audit
                        (tenant_id, user_id, kind, screen_id, fingerprint, source, decision, outcome)
                    VALUES ($1, $2, $3, $4, $5, 'ai', $6, 'applied')
                    """,
                    tenant_id, user_id, _KIND_CONTROLS, screen_id, fingerprint, roles_by_label,
                )
        except Exception as e:
            logger.warning("Failed to persist ERP control roles", error=str(e))


erp_decision_memory_service = ErpDecisionMemoryService()
