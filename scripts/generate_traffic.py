"""
LMS AI Co-Pilot — Live Observability Traffic Generator
======================================================
Sends continuous or batch requests to the running LMS Co-Pilot API
to generate realistic telemetry in Prometheus & Grafana.

Usage:
    # Run a quick 20-request burst:
    python scripts/generate_traffic.py

    # Run continuous traffic loop (watch Grafana in real-time):
    python scripts/generate_traffic.py --continuous

    # Control delay between requests (default 0.5s):
    python scripts/generate_traffic.py --delay 0.2
"""

import sys
import os
import time
import argparse
import random
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
import jwt

# Ensure UTF-8 output on Windows consoles
if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.config import settings


def generate_token(role: str = "Admin", user_id: str = "demo-admin-01") -> str:
    payload = {
        "Id": user_id,
        "Role": role,
        "CompanyId": "EFA605AB-4262-4701-A0E5-DBA154EA50B1",
        "exp": datetime.now(timezone.utc) + timedelta(hours=2),
    }
    if settings.JWT_ISSUER:
        payload["iss"] = settings.JWT_ISSUER
    if settings.JWT_AUDIENCE:
        payload["aud"] = settings.JWT_AUDIENCE
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


SAMPLE_QUERIES = [
    # Targeted educational questions matching indexed content in Qdrant:
    "إذن الإضافة وأوامر الشغل والتصنيع",
    "إذن الإضافة وأوامر الشغل والتصنيع",  # Repeated: guarantees instant Semantic Cache Hit!
    "كيف يعرض النظام الوارد والصادر لكل حركة؟",
    "كيف يعرض النظام الوارد والصادر لكل حركة؟",  # Repeated: guarantees instant Semantic Cache Hit!
    "طريقة تعديل الكميات في أوامر الشغل",
    "كيفية حساب الفارق بين التكلفة الفعلية والكميات المنتجة",
]


def send_request(url: str, method: str = "GET", data: dict | None = None, headers: dict | None = None) -> tuple[int, float, str]:
    headers = headers or {}
    body = json.dumps(data).encode("utf-8") if data else None
    if body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            elapsed = time.perf_counter() - start
            res_json = {}
            try:
                res_json = json.loads(resp.read().decode("utf-8"))
            except Exception:
                pass
            info = ""
            if res_json.get("cached"):
                info = "⚡ [CACHE HIT]"
            elif "sources" in res_json:
                info = f"🧠 [RAG: {len(res_json.get('sources', []))} chunks]"
            return resp.status, elapsed, info
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - start
        return e.code, elapsed, ""
    except Exception as e:
        elapsed = time.perf_counter() - start
        return 0, elapsed, ""


def main():
    parser = argparse.ArgumentParser(description="Generate live traffic for Grafana metrics")
    parser.add_argument("--count", type=int, default=20, help="Number of requests in batch mode (default: 20)")
    parser.add_argument("--continuous", action="store_true", help="Run indefinitely until stopped (Ctrl+C)")
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds (default: 0.5)")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API Base URL (default: http://localhost:8000)")
    args = parser.parse_args()

    token = generate_token()
    auth_headers = {"Authorization": f"Bearer {token}"}

    print("\n" + "=" * 65)
    print("🚀 LMS AI Co-Pilot — Live Telemetry Generator")
    print(f"🎯 Target URL: {args.base_url}")
    print(f"📊 Mode: {'Continuous Loop (Ctrl+C to stop)' if args.continuous else f'Batch ({args.count} requests)'}")
    print(f"⏱️ Delay: {args.delay}s")
    print("=" * 65 + "\n")

    total_sent = 0
    success_count = 0
    cache_hits_count = 0

    try:
        while True:
            total_sent += 1
            choice = random.random()

            if choice < 0.65:
                # 65% Search Requests (Cache + RAG)
                q = random.choice(SAMPLE_QUERIES)
                status, latency, info = send_request(
                    f"{args.base_url}/v1/search",
                    method="POST",
                    data={"query": q, "scope": "all"},
                    headers=auth_headers
                )
                type_label = "🔍 Search"
            elif choice < 0.85:
                # 20% Speech Utility (Tafqit)
                num = random.randint(100, 99999)
                status, latency, info = send_request(
                    f"{args.base_url}/v1/speech/tafqit",
                    method="POST",
                    data={"number": num},
                    headers=auth_headers
                )
                type_label = "🎙️ Speech"
            else:
                # 15% Health Heartbeat
                status, latency, info = send_request(f"{args.base_url}/health")
                type_label = "💓 Health"

            status_icon = "✅" if 200 <= status < 300 else "⚠️"
            if 200 <= status < 300:
                success_count += 1
            if "CACHE HIT" in info:
                cache_hits_count += 1

            print(f"[{total_sent:03d}] {status_icon} {status} | {type_label:10} | {latency * 1000:6.1f}ms | {info}")

            if not args.continuous and total_sent >= args.count:
                break

            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n🛑 Stopped by user.")

    print("\n" + "-" * 60)
    print(f"📊 Summary: Sent {total_sent} requests | Success: {success_count}/{total_sent} ({success_count / max(total_sent, 1) * 100:.1f}%)")
    print("👉 Check your Grafana dashboard at: http://localhost:3001/d/lms-ai-copilot-overview")
    print("-" * 60 + "\n")


if __name__ == "__main__":
    main()
