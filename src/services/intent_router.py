"""
Fast Ingress Intent Router Service
===================================
Best Practices Applied (2026):
- Sub-millisecond (< 1ms) heuristic intent classification using precompiled regexes and token sets.
- Zero-Token / Zero-Embedding bypass:
  - GREETING: Instant welcoming educational prompt.
  - OUT_OF_SCOPE: Polite canned refusal clarifying LMS boundary.
  - RAG_QUERY: Educational query routed to hybrid search pipeline.
- Non-blocking, pure CPU regex matching without heavy ML or external network calls.
- Integrated with Prometheus metrics for real-time intent telemetry.
"""

import re
from enum import Enum
from pydantic import BaseModel
import structlog

from src.core.config import settings
from src.core.metrics import record_intent_classified
from src.core.prompts import GREETING_RESPONSE, OUT_OF_SCOPE_RESPONSE, INVALID_QUERY_RESPONSE

logger = structlog.get_logger()


class IntentType(str, Enum):
    GREETING = "GREETING"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    RAG_QUERY = "RAG_QUERY"
    INVALID_QUERY = "INVALID_QUERY"


class IntentResult(BaseModel):
    intent: IntentType
    canned_response: str | None = None
    confidence: float = 1.0


class IntentRouterService:
    """
    Fast Ingress Intent Classifier.
    Routes queries in < 1ms to prevent wasteful LLM token generation on non-educational traffic.
    """

    def __init__(self) -> None:
        self._enabled = settings.INTENT_ROUTER_ENABLED

        # 1. Greetings regex patterns (Arabic dialects + English)
        self._greeting_pattern = re.compile(
            r"^\s*("
            r"أهلاً|اهلا|مرحبا|مرحباً|مرحبتين|سلام|السلام\s+عليكم(\s+ورحمة\s+الله(\s+وبركاته)?)?|سلام\s+عليكم|"
            r"هلا|يا\s+هلا|كيفك|شلونك|وش\s+أخبارك|ازيك|إزيك|ازي\s+حضرتك|عامل\s+ايه|"
            r"صباح\s+الخير|مساء\s+الخير|"
            r"ألو|الو|هاي|هلو|"
            r"hello|hi|hey|good\s+morning|good\s+evening|howdy|greetings|how\s+are\s+you"
            r")(\s+(يا\s+[\w]+|والله|وغلا|there|all|everyone))?[\s!.,؟?]*$",
            re.IGNORECASE | re.UNICODE,
        )

        # 2. Obvious Out-of-Scope triggers (Weather, explicit jokes, Politics, General gossip)
        self._out_of_scope_patterns = [
            re.compile(r"(الطقس|درجة\s+الحرارة|حالة\s+الجو|weather|temperature)", re.IGNORECASE),
            re.compile(r"(قولي\s+نكتة|احكيلي\s+نكتة|احكِ\s+لي\s+نكتة|قول\s+نكتة|اضحكني|ضحكني|tell\s+me\s+a\s+joke|joke\s+please)", re.IGNORECASE),
            re.compile(r"(مين\s+رئيس|من\s+هو\s+رئيس|الانتخابات|political|politics|president\s+of)", re.IGNORECASE),
            re.compile(r"(سعر\s+الدولار|سعر\s+الذهب|gold\s+price|dollar\s+rate)", re.IGNORECASE),
            re.compile(r"(نتيجة\s+مباراة|ماتش\s+النهاردة|دوري\s+أبطال|football\s+match|who\s+won\s+the\s+match)", re.IGNORECASE),
            re.compile(r"(طريقة\s+عمل\s+البيتزا|وصفة\s+طبخ|recipe|how\s+to\s+cook)", re.IGNORECASE),
        ]

    def initialize(self) -> None:
        """Called during FastAPI lifespan startup."""
        logger.info("Fast Ingress Intent Router ready ✅", enabled=self._enabled)

    def close(self) -> None:
        """Called during application shutdown."""
        logger.info("Fast Ingress Intent Router closed 🛑")

    def classify(self, query: str) -> IntentResult:
        """
        Classifies incoming query in < 1ms.
        Returns:
            IntentResult with intent type and canned response if applicable.
        """
        if not self._enabled:
            return IntentResult(intent=IntentType.RAG_QUERY, confidence=1.0)

        cleaned = query.strip()
        if not cleaned:
            record_intent_classified(IntentType.INVALID_QUERY.value)
            logger.info("Intent classified: INVALID_QUERY ⚠️")
            return IntentResult(
                intent=IntentType.INVALID_QUERY,
                canned_response=INVALID_QUERY_RESPONSE,
                confidence=1.0,
            )

        # Step 1: Check Greetings
        if self._greeting_pattern.match(cleaned):
            record_intent_classified(IntentType.GREETING.value)
            logger.info("Intent classified: GREETING 🤝", query_snippet=cleaned[:50])
            return IntentResult(
                intent=IntentType.GREETING,
                canned_response=GREETING_RESPONSE,
                confidence=0.99,
            )

        # Step 2: Check Out-Of-Scope topics
        for pattern in self._out_of_scope_patterns:
            if pattern.search(cleaned):
                record_intent_classified(IntentType.OUT_OF_SCOPE.value)
                logger.info("Intent classified: OUT_OF_SCOPE 🚫", query_snippet=cleaned[:50])
                return IntentResult(
                    intent=IntentType.OUT_OF_SCOPE,
                    canned_response=OUT_OF_SCOPE_RESPONSE,
                    confidence=0.95,
                )

        # Step 3: Default to RAG Educational Search
        record_intent_classified(IntentType.RAG_QUERY.value)
        return IntentResult(intent=IntentType.RAG_QUERY, confidence=1.0)


# Module-level singleton instance
intent_router = IntentRouterService()
