# tests/unit/test_filter_scoping.py
"""
Unit Tests for LMS AI Co-Pilot Hierarchical Scoping & Filtering
================================================================
Verifies that:
1. SearchRequest correctly parses Angular/DOTNET JSON payloads (with camelCase and snake_case).
2. _build_scope_filter binds ID conditions strictly to the active scope (module, unit, lesson).
3. Scope 'all' ignores lingering UI IDs to prevent scope leakage.
4. Level and Type filters are applied properly across all scopes.
5. Exact and Semantic Cache keys are deterministically isolated via scope_fingerprint.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest
from qdrant_client.models import Filter, FieldCondition, MatchValue
from src.models.search_models import SearchRequest
from src.models.auth_models import UserContext, TokenClaims
from src.services.exact_cache_service import exact_cache_service
from src.services.search_service import _build_scope_filter


def test_handoff_exact_payload():
    """Test parsing the exact JSON payload sent by Angular / .NET in the handoff spec."""
    payload = {
        "query": "ما هي خطوات إنشاء أمر تشغيل في موديول الإنتاج؟",
        "scope": "module",
        "moduleId": "b53f6081-305f-4613-a4e9-11440d463ef1",
        "module_id": "b53f6081-305f-4613-a4e9-11440d463ef1",
        "unitId": None,
        "unit_id": None,
        "lessonId": None,
        "lesson_id": None,
        "levelId": "1c55208f-2f74-4b53-906d-7419f4476ce2",
        "level_id": "1c55208f-2f74-4b53-906d-7419f4476ce2",
        "typeId": None,
        "type_id": None,
        "threadId": "conv-987654",
        "thread_id": "conv-987654",
        "skipCache": False,
        "skip_cache": False,
    }
    req = SearchRequest.model_validate(payload)
    assert req.query == "ما هي خطوات إنشاء أمر تشغيل في موديول الإنتاج؟"
    assert req.scope == "module"
    assert req.module_id == "b53f6081-305f-4613-a4e9-11440d463ef1"
    assert req.unit_id is None
    assert req.lesson_id is None
    assert req.level_id == "1c55208f-2f74-4b53-906d-7419f4476ce2"
    assert req.type_id is None
    assert req.thread_id == "conv-987654"
    assert req.skip_cache is False

    # Check Qdrant filter output
    q_filter = _build_scope_filter(req)
    assert q_filter is not None
    assert len(q_filter.must) == 2
    keys = {c.key: c.match.value for c in q_filter.must}
    assert keys["module_id"] == "b53f6081-305f-4613-a4e9-11440d463ef1"
    assert keys["level_id"] == "1c55208f-2f74-4b53-906d-7419f4476ce2"


def test_scope_all_ignores_lingering_ids():
    """Verify that when scope is 'all', residual IDs from previous selections are cleanly ignored."""
    req = SearchRequest(
        query="سؤال عام عن الدورة",
        scope="all",
        moduleId="residual-module-uuid",
        unitId="residual-unit-uuid",
        lessonId="residual-lesson-uuid",
        levelId="beginner",
        typeId="video",
    )
    q_filter = _build_scope_filter(req)
    assert q_filter is not None
    # Only level_id and type_id should be present — NOT module_id, unit_id, or lesson_id
    assert len(q_filter.must) == 2
    keys = {c.key: c.match.value for c in q_filter.must}
    assert "module_id" not in keys
    assert "unit_id" not in keys
    assert "lesson_id" not in keys
    assert keys["level_id"] == "beginner"
    assert keys["type_id"] == "video"


def test_hierarchical_scopes_isolation():
    """Verify that module, unit, and lesson scopes only filter by their corresponding target ID."""
    # 1. Module scope
    req_mod = SearchRequest(query="q", scope="module", moduleId="mod-erp", unitId="u-1", lessonId="les-1")
    f_mod = _build_scope_filter(req_mod)
    assert f_mod is not None
    assert len(f_mod.must) == 1
    assert f_mod.must[0].key == "module_id"
    assert f_mod.must[0].match.value == "mod-erp"

    # 2. Unit scope
    req_unit = SearchRequest(query="q", scope="unit", moduleId="mod-erp", unitId="u-1", lessonId="les-1")
    f_unit = _build_scope_filter(req_unit)
    assert f_unit is not None
    assert len(f_unit.must) == 1
    assert f_unit.must[0].key == "unit_id"
    assert f_unit.must[0].match.value == "u-1"

    # 3. Lesson scope
    req_les = SearchRequest(query="q", scope="lesson", moduleId="mod-erp", unitId="u-1", lessonId="les-1")
    f_les = _build_scope_filter(req_les)
    assert f_les is not None
    assert len(f_les.must) == 1
    assert f_les.must[0].key == "lesson_id"
    assert f_les.must[0].match.value == "les-1"


def test_scope_fingerprint_deterministic_partitioning():
    """Verify that scope_fingerprint creates distinct hash keys for cache isolation."""
    req_all = SearchRequest(query="q", scope="all", moduleId="mod-1")
    req_mod = SearchRequest(query="q", scope="module", moduleId="mod-1")
    req_unit = SearchRequest(query="q", scope="unit", unitId="u-1")
    req_les = SearchRequest(query="q", scope="lesson", lessonId="les-1")

    # Scope 'all' should ignore lingering mod-1
    assert req_all.scope_fingerprint.startswith("all::::")
    assert req_mod.scope_fingerprint.startswith("module:mod-1:::")
    assert req_unit.scope_fingerprint.startswith("unit::u-1::")
    assert req_les.scope_fingerprint.startswith("lesson:::les-1:")

    # Verify exact cache key SHA256 isolation
    user_ctx = UserContext(
        claims=TokenClaims(user_id="u1", role="Student", company_id="c1")
    )
    k_all = exact_cache_service._compute_key("ما هي المحاسبة؟", user_ctx, req_all.scope_fingerprint)
    k_mod = exact_cache_service._compute_key("ما هي المحاسبة؟", user_ctx, req_mod.scope_fingerprint)
    k_unit = exact_cache_service._compute_key("ما هي المحاسبة؟", user_ctx, req_unit.scope_fingerprint)
    k_les = exact_cache_service._compute_key("ما هي المحاسبة؟", user_ctx, req_les.scope_fingerprint)

    assert len({k_all, k_mod, k_unit, k_les}) == 4, "All cache keys must be uniquely isolated"


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    print("Running test_handoff_exact_payload...", flush=True)
    test_handoff_exact_payload()
    print("Running test_scope_all_ignores_lingering_ids...", flush=True)
    test_scope_all_ignores_lingering_ids()
    print("Running test_hierarchical_scopes_isolation...", flush=True)
    test_hierarchical_scopes_isolation()
    print("Running test_scope_fingerprint_deterministic_partitioning...", flush=True)
    test_scope_fingerprint_deterministic_partitioning()
    print("ALL 4 UNIT TESTS PASSED SUCCESSFULLY! 🚀", flush=True)
