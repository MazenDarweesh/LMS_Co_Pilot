# tests/unit/test_citations_and_sources.py
"""
Unit tests for citation boundaries and source title formatting.
Ensures LLM prompt strictly bounds citations to retrieved chunks [1]..[N],
and SourceItem objects contain human-friendly, readable titles for the frontend.
"""
from src.core.prompts import RAG_SYSTEM_PROMPT, get_rag_system_prompt
from src.models.search_models import SourceItem
from src.services.search_service import _build_source_items
from src.api.v1.router import _SOURCE_FIELDS


def test_rag_prompt_dynamic_boundaries():
    """Verify system prompt explicitly bounds citations to the number of retrieved sources."""
    prompt = get_rag_system_prompt(context_str="[1] محتوى اختباري", num_sources=3)
    assert "You have exactly 3 retrieved source(s)" in prompt
    assert "[1] to [3]" in prompt
    assert "citation [4] is strictly forbidden" in prompt


def test_safe_rag_prompt_backwards_compatibility():
    """Verify legacy .format(context_str=...) calls do not crash and supply defaults."""
    formatted = RAG_SYSTEM_PROMPT.format(context_str="محتوى قديم")
    assert "You have exactly 1 retrieved source(s)" in formatted
    assert "[1] to [1]" in formatted
    assert "citation [2] is strictly forbidden" in formatted


def test_build_source_items_video_formatting():
    """Verify video chunks produce friendly titles with minute:second timestamps."""
    chunks = [
        {
            "content_type": "video_chunk",
            "source_url": "https://youtu.be/test?t=75s",
            "start_time": 75,
            "end_time": 150,
            "lesson_id": "lesson-1",
        },
        {
            "content_type": "video_chunk",
            "source_url": "https://youtu.be/test2",
            "start_time": None,
            "end_time": None,
            "lesson_id": "lesson-2",
        },
    ]
    items = _build_source_items(chunks)
    assert len(items) == 2
    assert items[0].title == "المصدر [1] — مقطع فيديو (01:15 - 02:30)"
    assert items[0].start == 75
    assert items[0].end == 150
    assert items[1].title == "المصدر [2] — مقطع فيديو"


def test_build_source_items_pdf_formatting():
    """Verify PDF chunks produce friendly titles with section or page numbers."""
    chunks = [
        {
            "content_type": "pdf_chunk",
            "section_title": "مقدمة عن المحاسبة المالية",
            "page_number": 3,
            "lesson_id": "lesson-3",
        },
        {
            "content_type": "pdf_chunk",
            "section_title": None,
            "page_number": 12,
            "lesson_id": "lesson-4",
        },
    ]
    items = _build_source_items(chunks)
    assert len(items) == 2
    assert items[0].title == "المصدر [1] — مقدمة عن المحاسبة المالية"
    assert items[1].title == "المصدر [2] — صفحة 12"


def test_source_item_serialization_and_router_whitelist():
    """Verify SourceItem title serializes correctly and is accepted in router whitelist."""
    item = SourceItem(
        type="video",
        url="https://youtu.be/test",
        title="المصدر [1] — مقطع فيديو",
        lesson_id="lesson-01",
    )
    dumped = item.model_dump()
    assert dumped["title"] == "المصدر [1] — مقطع فيديو"
    assert "title" in _SOURCE_FIELDS


def test_valid_chunks_filtering_and_sequential_reindexing():
    """
    Verify that _filter_valid_chunks discards incomplete chunks (e.g. video without source_url)
    and _build_source_items + _build_rag_context_str re-index valid chunks sequentially 1..N.
    """
    from src.services.search_service import _filter_valid_chunks, _build_rag_context_str

    raw_chunks = [
        {"content_type": "video_chunk", "source_url": "http://v1", "text_msa": "chunk 1"},
        {"content_type": "video_chunk", "source_url": None, "text_msa": "chunk 2 missing url"},
        {"content_type": "video_chunk", "source_url": "http://v3", "text_msa": "chunk 3"},
        {"content_type": "pdf_chunk", "section_title": "القسم 4", "text_msa": "chunk 4 pdf"},
    ]

    valid = _filter_valid_chunks(raw_chunks)
    assert len(valid) == 3

    context_str = _build_rag_context_str(valid)
    assert "[1] chunk 1" in context_str
    assert "[2] chunk 3" in context_str
    assert "[3] chunk 4 pdf" in context_str
    assert "[4]" not in context_str

    items = _build_source_items(valid)
    assert len(items) == 3
    assert items[0].title == "المصدر [1] — مقطع فيديو"
    assert items[1].title == "المصدر [2] — مقطع فيديو"
    assert items[2].title == "المصدر [3] — القسم 4"


def test_search_request_skip_cache_aliases():
    """Verify SearchRequest accepts skip_cache via various aliases (skipCache, bypass_cache, retry)."""
    from src.models.search_models import SearchRequest

    req1 = SearchRequest.model_validate({"query": "سؤال", "skip_cache": True})
    assert req1.skip_cache is True

    req2 = SearchRequest.model_validate({"query": "سؤال", "skipCache": True})
    assert req2.skip_cache is True

    req3 = SearchRequest.model_validate({"query": "سؤال", "retry": True})
    assert req3.skip_cache is True

    req4 = SearchRequest.model_validate({"query": "سؤال"})
    assert req4.skip_cache is False


def test_admin_cache_clear_dual_routes_registered():
    """Verify /admin/cache/clear is registered under both /v1 and /api."""
    from src.main import app
    paths = app.openapi()["paths"]
    assert "/v1/admin/cache/clear" in paths
    assert "/api/admin/cache/clear" in paths


def test_search_response_provenance_and_latency():
    """Verify SearchResponse includes provenance, cache_hit, and latency_ms with correct serialization."""
    from src.models.search_models import SearchResponse

    resp = SearchResponse(
        answer="إجابة تجريبية",
        sources=[],
        query_used="سؤال تجريبي",
        provenance="SEMANTIC_CACHE",
        cache_hit=True,
        latency_ms=12.4,
    )
    dump = resp.model_dump()
    assert dump["provenance"] == "SEMANTIC_CACHE"
    assert dump["cache_hit"] is True
    assert dump["latency_ms"] == 12.4

