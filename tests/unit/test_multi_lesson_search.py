# tests/unit/test_multi_lesson_search.py
"""
Unit tests for Cross-Module Multi-Lesson search capabilities.
Verifies:
1. SearchRequest schema parsing with lesson_ids and alias support (lessonIds, LessonIds).
2. Scope fingerprint determinism and sorting for cache isolation.
3. Qdrant filter generation using MatchAny across lesson_id and lesson_ids.
4. Prompt generation with multi-lesson comparative guidelines.
"""
import pytest
from qdrant_client.models import MatchAny, MatchValue, Filter

from src.models.search_models import SearchRequest
from src.services.search_service import _build_scope_filter
from src.core.prompts import get_rag_system_prompt, RAG_SYSTEM_PROMPT


def test_search_request_lesson_ids_aliases():
    """Verify SearchRequest correctly accepts and normalizes lesson_ids and camelCase aliases."""
    # Snake case
    req1 = SearchRequest(query="قارن بين الدرسين", lesson_ids=["lesson-a", "lesson-b"])
    assert req1.lesson_ids == ["lesson-a", "lesson-b"]

    # camelCase alias
    req2 = SearchRequest.model_validate({"query": "سؤال", "lessonIds": ["id1", "id2"]})
    assert req2.lesson_ids == ["id1", "id2"]

    # PascalCase alias
    req3 = SearchRequest.model_validate({"query": "سؤال", "LessonIds": ["id3", "id4"]})
    assert req3.lesson_ids == ["id3", "id4"]

    # Default empty list
    req_default = SearchRequest(query="سؤال عام")
    assert req_default.lesson_ids == []


def test_scope_normalization_multi_lesson():
    """Verify 'lessons' and 'multi_lesson' scopes are properly recognized and normalized."""
    req1 = SearchRequest(query="سؤال", scope="LESSONS")
    assert req1.scope == "lessons"

    req2 = SearchRequest(query="سؤال", scope="multi_lesson")
    assert req2.scope == "multi_lesson"


def test_scope_fingerprint_deterministic_caching():
    """Verify scope_fingerprint sorts lesson_ids so permutation doesn't cause cache misses."""
    req_order1 = SearchRequest(query="سؤال", lesson_ids=["lesson-b", "lesson-a"])
    req_order2 = SearchRequest(query="سؤال", lesson_ids=["lesson-a", "lesson-b"])
    assert req_order1.scope_fingerprint == req_order2.scope_fingerprint
    assert "lesson-a,lesson-b" in req_order1.scope_fingerprint

    # Different lessons must produce different fingerprints
    req_other = SearchRequest(query="سؤال", lesson_ids=["lesson-a", "lesson-c"])
    assert req_order1.scope_fingerprint != req_other.scope_fingerprint


def test_build_scope_filter_multi_lesson_match_any():
    """Verify _build_scope_filter constructs MatchAny conditions for both lesson_id and lesson_ids."""
    req = SearchRequest(
        query="سؤال متعدد الدروس",
        scope="lessons",
        lesson_ids=["lesson-101", "lesson-202"],
    )
    filter_obj = _build_scope_filter(req)

    assert filter_obj is not None
    assert isinstance(filter_obj, Filter)
    assert len(filter_obj.must) >= 1

    # Find the should filter targeting lesson IDs
    lesson_filter = None
    for cond in filter_obj.must:
        if isinstance(cond, Filter) and cond.should:
            lesson_filter = cond
            break

    assert lesson_filter is not None
    keys_matched = [c.key for c in lesson_filter.should]
    assert "lesson_id" in keys_matched
    assert "lesson_ids" in keys_matched

    for c in lesson_filter.should:
        assert isinstance(c.match, MatchAny)
        assert set(c.match.any) == {"lesson-101", "lesson-202"}


def test_build_scope_filter_single_lesson_match_value():
    """Verify backward compatibility: single lesson scope continues using MatchValue."""
    req = SearchRequest(
        query="سؤال درس واحد",
        scope="lesson",
        lesson_id="lesson-single",
    )
    filter_obj = _build_scope_filter(req)
    assert filter_obj is not None

    lesson_filter = None
    for cond in filter_obj.must:
        if isinstance(cond, Filter) and cond.should:
            lesson_filter = cond
            break

    assert lesson_filter is not None
    for c in lesson_filter.should:
        assert isinstance(c.match, MatchValue)
        assert c.match.value == "lesson-single"


def test_get_rag_system_prompt_multi_lesson():
    """Verify system prompt injects cross-lesson comparison instructions only when requested."""
    # Standard single-lesson/general query
    prompt_single = get_rag_system_prompt(context_str="سياق تجريبي", num_sources=2, is_multi_lesson=False)
    assert "الربط والمقارنة بين الدروس المتعددة" not in prompt_single
    assert "مرقّمة من [1] إلى [2]" in prompt_single

    # Multi-lesson query
    prompt_multi = get_rag_system_prompt(context_str="سياق تجريبي", num_sources=3, is_multi_lesson=True)
    assert "الربط والمقارنة بين الدروس المتعددة" in prompt_multi
    assert "Cross-Module Multi-Lesson" in prompt_multi
    assert "مرقّمة من [1] إلى [3]" in prompt_multi
