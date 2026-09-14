# tests/unit/test_dotnet_compatibility.py
"""
Unit Tests for .NET 10 & LMS Integration Contract v3.0.0 Compatibility
========================================================================
Verifies that the Python AI Co-Pilot engine strictly satisfies the contract:
1. Dual Route Registration (/v1 and /api) without 404s.
2. Quiz DTO Serialization contains C# property names (question_text, question_number, option_id).
3. Summary DTO contains mandatory 'overview' field.
4. WebhookPayload handles both camelCase (lessonId) and snake_case (lesson_id) with case-insensitive action.
5. TokenClaims handles Id/sub/nameid and string/array Role claims.
"""
import pytest
from src.main import app
from src.models.schemas import QuizOption, QuizQuestion, GeneratedQuiz, GeneratedSummary, WebhookPayload
from src.models.auth_models import TokenClaims


def test_dual_routes_registered_in_fastapi():
    """Verify that endpoints exist under both /v1 and /api prefixes."""
    paths = app.openapi()["paths"]
    
    # Quiz endpoint
    assert "/v1/admin/lessons/{lesson_id}/generate-quiz" in paths
    assert "/api/admin/lessons/{lesson_id}/generate-quiz" in paths
    
    # Summary endpoint
    assert "/v1/admin/lessons/{lesson_id}/generate-summary" in paths
    assert "/api/admin/lessons/{lesson_id}/generate-summary" in paths
    
    # Webhook endpoint
    assert "/v1/webhooks/lesson-updated" in paths
    assert "/api/webhooks/lesson-updated" in paths


def test_quiz_dto_compatibility_fields():
    """Verify QuizOption and QuizQuestion serialize both Python and C# compatible names."""
    option = QuizOption(id="a", text="Option Text")
    dump = option.model_dump()
    assert dump["id"] == "a"
    assert dump["option_id"] == "a"
    assert dump["text"] == "Option Text"
    assert dump["option_text"] == "Option Text"

    question = QuizQuestion(
        id=1,
        question="What is ERP?",
        options=[option],
        correct_answer_id="a",
        explanation="Explanation text"
    )
    q_dump = question.model_dump()
    assert q_dump["id"] == 1
    assert q_dump["question_number"] == 1
    assert q_dump["question"] == "What is ERP?"
    assert q_dump["question_text"] == "What is ERP?"
    assert q_dump["options"][0]["option_id"] == "a"


def test_summary_dto_has_overview():
    """Verify GeneratedSummary contains mandatory overview field."""
    summary = GeneratedSummary(
        lesson_id="lesson-123",
        overview="This is a comprehensive overview of the POS module.",
        topics=[]
    )
    dump = summary.model_dump()
    assert "overview" in dump
    assert dump["overview"] == "This is a comprehensive overview of the POS module."


def test_webhook_payload_resilience():
    """Verify WebhookPayload accepts camelCase and snake_case."""
    # camelCase (.NET standard)
    p1 = WebhookPayload.model_validate({"lessonId": "guid-123", "action": "Updated"})
    assert p1.lesson_id == "guid-123"
    assert p1.lessonId == "guid-123"
    assert p1.action == "Updated"

    # snake_case
    p2 = WebhookPayload.model_validate({"lesson_id": "guid-456", "action": "deleted"})
    assert p2.lesson_id == "guid-456"
    assert p2.lessonId == "guid-456"


def test_token_claims_resilience():
    """Verify TokenClaims accepts various .NET JWT claim patterns."""
    # Pattern 1: PascalCase from .NET TokenService
    c1 = TokenClaims.model_validate({
        "Id": "user-1",
        "Role": "Admin",
        "CompanyId": "comp-1",
        "DepartmentId": "dep-1"
    })
    assert c1.user_id == "user-1"
    assert c1.role == "Admin"
    assert c1.company_id == "comp-1"

    # Pattern 2: Standard JWT with 'sub' and array Role
    c2 = TokenClaims.model_validate({
        "sub": "user-2",
        "role": ["Teacher", "Staff"],
        "tenant_id": "comp-2"
    })
    assert c2.user_id == "user-2"
    assert c2.role == "Teacher"
    assert c2.company_id == "comp-2"


def test_search_request_scope_lesson():
    """Verify SearchRequest accepts scope='lesson' as required by Angular lesson viewer."""
    from src.models.search_models import SearchRequest
    req = SearchRequest(
        query="كيف أقوم بتعديل صلاحيات الكاشير؟",
        lesson_id="3fa85f64-5717-4562-b3fc-2c963f66afa6",
        scope="lesson"
    )
    assert req.scope == "lesson"
    assert req.lesson_id == "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def test_feedback_request_case_insensitive_rating():
    """Verify FeedbackRequest accepts lowercase 'up' and 'down' from Angular clients."""
    from src.models.search_models import FeedbackRequest, FeedbackRating
    
    # lowercase 'up'
    f1 = FeedbackRequest(
        query="كيف أسجل قيد؟",
        answer="من شاشة الحسابات العامة",
        rating="up"
    )
    assert f1.rating == FeedbackRating.UP
    
    # lowercase 'down'
    f2 = FeedbackRequest(
        query="كيف أسجل قيد؟",
        answer="من شاشة الحسابات العامة",
        rating="down"
    )
    assert f2.rating == FeedbackRating.DOWN
