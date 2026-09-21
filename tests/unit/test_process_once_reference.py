import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from qdrant_client.models import PointStruct, ScoredPoint, Record, Filter, FieldCondition, MatchValue

from src.models.schemas import (
    extract_video_id,
    LessonMetadata,
    QdrantChunkPayload,
    WebhookPayload,
    LessonReferenceRequest,
    LessonReferenceResponse,
)
from src.models.entities import ContentType, SourceType
from src.services.pipeline_orchestrator import make_chunk_id
from src.services.search_service import _build_scope_filter
from src.models.search_models import SearchRequest
from src.services.qdrant_service import QdrantService


def test_extract_video_id():
    """التحقق من استخراج معرف الفيديو من مختلف صيغ الروابط بدقة وحتمية."""
    # Standard YouTube watch URL
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    # Short youtu.be URL
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=42s") == "dQw4w9WgXcQ"
    # Direct mp4 / custom URL falls back to deterministic SHA256 (16 chars)
    custom_url = "https://cdn.example.com/videos/lecture_01.mp4"
    h1 = extract_video_id(custom_url)
    h2 = extract_video_id(custom_url)
    assert len(h1) == 16
    assert h1 == h2
    assert extract_video_id("") == ""


def test_make_chunk_id_deterministic_by_video():
    """
    التحقق من أن معرف الـ Chunk حتمي ومبني على الفيديو:
    درسان مختلفان بنفس الفيديو سينتجان نفس الـ chunk_id للقطعة 0،
    مما يمنع تكرار النقاط في Qdrant.
    """
    vid_id = "dQw4w9WgXcQ"
    chunk_0_a = make_chunk_id(vid_id, 0)
    chunk_0_b = make_chunk_id(vid_id, 0)
    chunk_1 = make_chunk_id(vid_id, 1)

    assert chunk_0_a == chunk_0_b
    assert chunk_0_a != chunk_1


def test_qdrant_chunk_payload_multi_reference_sync():
    """التحقق من التزامن التلقائي بين lesson_id و lesson_ids وبين module_id و module_ids."""
    payload = QdrantChunkPayload(
        chunk_id="chunk_test_123",
        lesson_id="lesson-uuid-1",
        content_type=ContentType.VIDEO_CHUNK,
        source_type=SourceType.YOUTUBE,
        source_url="https://youtu.be/dQw4w9WgXcQ",
        text_msa="نص تجريبي للدرس",
        text_original="نص تجريبي",
        tenant_ids=["default"],
        module_id="mod-uuid-1",
        target_roles=["Student"],
        allowed_entities=["lesson:lesson-uuid-1", "module:mod-uuid-1"],
    )

    # Automatically synced in validator
    assert "lesson-uuid-1" in payload.lesson_ids
    assert "mod-uuid-1" in payload.module_ids

    # Multiple references
    payload_multi = QdrantChunkPayload(
        chunk_id="chunk_test_456",
        lesson_id="lesson-1",
        lesson_ids=["lesson-1", "lesson-2"],
        content_type=ContentType.VIDEO_CHUNK,
        source_type=SourceType.YOUTUBE,
        source_url="https://youtu.be/dQw4w9WgXcQ",
        text_msa="نص تجريبي 2",
        text_original="نص تجريبي 2",
        tenant_ids=["default"],
        module_id="mod-1",
        module_ids=["mod-1", "mod-2"],
        target_roles=["Student"],
        allowed_entities=[],
    )
    assert payload_multi.lesson_ids == ["lesson-1", "lesson-2"]
    assert payload_multi.module_ids == ["mod-1", "mod-2"]


def test_lesson_metadata_build_allowed_entities_multi():
    """التحقق من أن build_allowed_entities يجمع كل الموديولات والدروس المتعددة في allowed_entities."""
    meta = LessonMetadata(
        lesson_id="lesson-1",
        lesson_ids=["lesson-2", "lesson-3"],
        tenant_ids=["default"],
        module_id="mod-1",
        module_ids=["mod-2"],
        target_roles=["Admin", "Student"],
    )
    meta.build_allowed_entities()

    assert "lesson:lesson-1" in meta.allowed_entities
    assert "lesson:lesson-2" in meta.allowed_entities
    assert "lesson:lesson-3" in meta.allowed_entities
    assert "module:mod-1" in meta.allowed_entities
    assert "module:mod-2" in meta.allowed_entities
    assert "tenant:default" in meta.allowed_entities
    assert "role:Student" in meta.allowed_entities


def test_scope_filter_matches_both_single_and_multi_reference():
    """التحقق من أن فلتر البحث يطابق lesson_id و lesson_ids (وكذلك module_id و module_ids)."""
    # 1. Lesson scope
    req_lesson = SearchRequest(query="كيف يعمل النظام؟", scope="lesson", lesson_id="lesson-shared-1")
    scope_filter = _build_scope_filter(req_lesson)
    assert scope_filter is not None
    assert len(scope_filter.must) >= 1
    found_lesson_should = False
    for condition in scope_filter.must:
        if isinstance(condition, Filter) and condition.should:
            keys = [c.key for c in condition.should if hasattr(c, "key")]
            if "lesson_id" in keys and "lesson_ids" in keys:
                found_lesson_should = True
    assert found_lesson_should, "Scope filter must match both lesson_id and lesson_ids"

    # 2. Module scope
    req_module = SearchRequest(query="كيف يعمل النظام؟", scope="module", module_id="mod-shared-1")
    mod_filter = _build_scope_filter(req_module)
    assert mod_filter is not None
    found_mod_should = False
    for condition in mod_filter.must:
        if isinstance(condition, Filter) and condition.should:
            keys = [c.key for c in condition.should if hasattr(c, "key")]
            if "module_id" in keys and "module_ids" in keys:
                found_mod_should = True
    assert found_mod_should, "Scope filter must match both module_id and module_ids"


@pytest.mark.asyncio
async def test_qdrant_link_lesson_to_existing_video():
    """اختبار ربط درس وموديول جديد بنقاط فيديو مخزنة مسبقاً في Qdrant."""
    svc = QdrantService()
    svc._client = AsyncMock()

    mock_point = Record(
        id="chunk-01",
        payload={
            "chunk_id": "chunk-01",
            "video_id": "dQw4w9WgXcQ",
            "lesson_id": "lesson-1",
            "lesson_ids": ["lesson-1"],
            "module_id": "mod-1",
            "module_ids": ["mod-1"],
            "allowed_entities": ["tenant:default", "lesson:lesson-1", "module:mod-1"],
        },
        vector=None,
    )

    svc._client.scroll = AsyncMock(return_value=([mock_point], None))
    svc._client.set_payload = AsyncMock()

    count = await svc.link_lesson_to_existing_video(
        video_identifier="dQw4w9WgXcQ",
        source_url=None,
        new_lesson_id="lesson-2",
        new_module_id="mod-2",
    )

    assert count == 1
    assert svc._client.set_payload.called
    call_args = svc._client.set_payload.call_args[1]
    payload_sent = call_args["payload"]
    assert "lesson:lesson-2" in payload_sent["allowed_entities"]
    assert "module:mod-2" in payload_sent["allowed_entities"]
    assert "lesson-2" in payload_sent["lesson_ids"]
    assert "mod-2" in payload_sent["module_ids"]


@pytest.mark.asyncio
async def test_qdrant_delete_by_lesson_id_reference_counting():
    """
    اختبار حذف الدرس بنظام حساب المراجع:
    إذا كان الدرس مشتركاً بين درسين، يتم فك الارتباط دون حذف النقطة.
    إذا كان هذا آخر درس يستخدم الفيديو، يتم حذف النقطة فيزيائياً.
    """
    svc = QdrantService()
    svc._client = AsyncMock()

    # Case 1: Point shared between lesson-1 and lesson-2
    shared_point = Record(
        id="chunk-shared",
        payload={
            "chunk_id": "chunk-shared",
            "lesson_id": "lesson-1",
            "lesson_ids": ["lesson-1", "lesson-2"],
            "allowed_entities": ["tenant:default", "lesson:lesson-1", "lesson:lesson-2"],
        },
        vector=None,
    )

    svc._client.scroll = AsyncMock(return_value=([shared_point], None))
    svc._client.set_payload = AsyncMock()
    svc._client.delete = AsyncMock()

    # Delete lesson-1
    await svc.delete_by_lesson_id("lesson-1")

    # Verify: Physical delete must NOT be called because lesson-2 still references it!
    assert not svc._client.delete.called
    # Verify: set_payload was called to unlink lesson-1 and keep lesson-2
    assert svc._client.set_payload.called
    call_payload = svc._client.set_payload.call_args[1]["payload"]
    assert "lesson-1" not in call_payload["lesson_ids"]
    assert "lesson-2" in call_payload["lesson_ids"]
    assert "lesson:lesson-1" not in call_payload["allowed_entities"]
    assert "lesson:lesson-2" in call_payload["allowed_entities"]

    # Case 2: Now delete lesson-2 (last remaining reference)
    single_point = Record(
        id="chunk-shared",
        payload={
            "chunk_id": "chunk-shared",
            "lesson_id": "lesson-2",
            "lesson_ids": ["lesson-2"],
            "allowed_entities": ["tenant:default", "lesson:lesson-2"],
        },
        vector=None,
    )
    svc._client.scroll = AsyncMock(return_value=([single_point], None))
    svc._client.set_payload.reset_mock()
    svc._client.delete.reset_mock()

    await svc.delete_by_lesson_id("lesson-2")

    # Verify: Now physical delete IS called because 0 references remain!
    assert svc._client.delete.called
    assert not svc._client.set_payload.called


def test_webhook_payload_referenced_action():
    """التحقق من أن WebhookPayload يقبل الحدث 'referenced' مع حقول الفيديو والموديول."""
    payload = WebhookPayload(
        lesson_id="new-lesson-uuid",
        action="Referenced",
        video_url="https://youtu.be/dQw4w9WgXcQ",
        module_id="new-module-uuid",
    )
    assert payload.lesson_id == "new-lesson-uuid"
    assert payload.action == "Referenced"
    assert payload.video_url == "https://youtu.be/dQw4w9WgXcQ"
    assert payload.module_id == "new-module-uuid"
