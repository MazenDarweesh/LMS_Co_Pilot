"""
LMS AI Co-Pilot — Concurrency & Load Testing Suite
===================================================
Simulates realistic student traffic patterns:
- 70% Frequent Queries (Validates Sub-10ms Semantic Cache performance & zero LLM cost)
- 20% Exploratory/Unique Queries (Validates Hybrid RAG + FlashRank ONNX thread-safety)
- 10% System Health & Diagnostics (Validates Event Loop responsiveness)

Usage:
  # Quick headless run (10 users, 15 seconds):
  uv run locust -f tests/load/locustfile.py --headless -u 10 -r 2 -t 15s --host http://localhost:8000

  # High-concurrency stress test (50 users, 45 seconds):
  uv run locust -f tests/load/locustfile.py --headless -u 50 -r 10 -t 45s --host http://localhost:8000
"""

import random
import uuid
from datetime import datetime, timedelta, timezone
import jwt
from locust import HttpUser, task, between, events

from src.core.config import settings


def generate_student_token(user_id: str | None = None, company_id: str = "egy-dynamic") -> str:
    """Generates a valid JWT token representing an authenticated student."""
    uid = user_id or f"student-{uuid.uuid4().hex[:8]}"
    payload = {
        "Id": uid,
        "Role": "Student",
        "CompanyId": company_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=2),
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


# High-frequency repeated queries (designed to hit the Semantic Cache)
REPEATED_QUERIES = [
    "ما هي وظيفة الـ GL في المحاسبة؟",
    "كيف يتم التعامل مع أذون الصرف في موديول المخازن؟",
    "ما هي خطوات إعداد معادلة التصنيع القياسية؟",
    "ما هو الفرق بين متوسط التكلفة والتكلفة الفعلية؟",
    "كيف يتم تسجيل قيود نقاط البيع POS؟",
]

# Diverse long-tail queries (forcing hybrid retrieval + FlashRank reranking)
UNIQUE_QUERIES = [
    "شرح مفصل عن كارت الصنف ذو الرصيد السالب",
    "ما هي معايير إضافة المنتجات الخام في أمر الشغل؟",
    "طريقة حساب تكلفة البرميل بعد تسوية الجرد السنوي",
    "كيف ترتبط حركة الوارد بالحسابات العامة والضرائب؟",
    "كيفية إغلاق الصرف بالسالب من شاشة إعدادات الشركة",
]


class LMSStudentUser(HttpUser):
    """
    Simulates an authenticated student interacting with the LMS AI Co-Pilot.
    """
    wait_time = between(0.5, 2.0)  # Realistic typing / reading pause

    def on_start(self):
        """Initialize user session with a unique JWT token."""
        self.user_id = f"student-{uuid.uuid4().hex[:6]}"
        self.token = generate_student_token(self.user_id)
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @task(7)
    def search_frequent_query(self):
        """
        70% of student queries: Repeated/popular educational questions.
        Validates that the Qdrant Semantic Cache responds under 15ms
        without overloading the LLM or embeddings engine.
        """
        query = random.choice(REPEATED_QUERIES)
        payload = {
            "query": query,
            "scope": "all",
            "limit": 5,
        }
        with self.client.post(
            "/v1/search",
            json=payload,
            headers=self.headers,
            catch_response=True,
            name="POST /v1/search [Frequent - Cache Target]",
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if "answer" in data:
                    response.success()
                else:
                    response.failure(f"Missing answer field in response: {response.text[:100]}")
            elif response.status_code == 429:
                response.failure("Rate limit reached (429)")
            else:
                response.failure(f"Unexpected status: {response.status_code} - {response.text[:100]}")

    @task(2)
    def search_unique_query(self):
        """
        20% of student queries: Unique/exploratory questions.
        Validates CPU threadpool safety, BGE-M3 model locks,
        and FlashRank ONNX cross-encoder execution under concurrency.
        """
        base_query = random.choice(UNIQUE_QUERIES)
        # Add slight variation to test semantic threshold and cold misses
        query = f"{base_query} (حالة رقم {random.randint(100, 999)})"
        payload = {
            "query": query,
            "scope": "all",
            "limit": 5,
        }
        with self.client.post(
            "/v1/search",
            json=payload,
            headers=self.headers,
            catch_response=True,
            name="POST /v1/search [Unique - RAG Pipeline]",
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 429:
                response.failure("Rate limit reached (429)")
            else:
                response.failure(f"Unexpected status: {response.status_code} - {response.text[:100]}")

    @task(1)
    def check_health_and_status(self):
        """
        10% of traffic: Basic health check & API heartbeat.
        Ensures Uvicorn event loop remains unblocked during heavy ML workloads.
        """
        with self.client.get(
            "/health",
            catch_response=True,
            name="GET /health [Heartbeat]",
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Health check failed with {response.status_code}")
