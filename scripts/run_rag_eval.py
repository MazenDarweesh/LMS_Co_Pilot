"""
scripts/run_rag_eval.py
========================
سكريبت تقييم جودة الـ RAG باستخدام مكتبة Ragas.

الاستخدام:
    uv run python scripts/run_rag_eval.py
    uv run python scripts/run_rag_eval.py --limit 10
    uv run python scripts/run_rag_eval.py --no-recall
"""
import sys, os

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncio
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

# --- MOCK FIX FOR RAGAS 0.4.x BUG ---
import types
if 'langchain_community.chat_models.vertexai' not in sys.modules:
    sys.modules['langchain_community.chat_models.vertexai'] = types.ModuleType('langchain_community.chat_models.vertexai')
    sys.modules['langchain_community.chat_models.vertexai'].ChatVertexAI = None
# -----------------------------------

from datasets import Dataset
from ragas import evaluate
from ragas.metrics.collections import faithfulness, answer_relevancy, context_recall
from ragas.llms import LangchainLLMWrapper
from langchain_google_genai import ChatGoogleGenerativeAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.core.config import settings
from src.models.search_models import SearchRequest
from src.models.auth_models import UserContext
from src.services.embedding_service import embedding_service
from src.services.qdrant_service import qdrant_service
from src.services.reranker_service import reranker_service
from src.agents.base_agent import agent_service
from src.services.search_service import search_service

DATASET_PATH = Path("tests/eval/golden_dataset.jsonl")
RESULTS_DIR  = Path("tests/eval/results")

EVAL_USER_CTX = UserContext(
    claims={"Id": "eval-admin-1", "Role": "Admin", "CompanyId": "default_company"},
    permissions={"userId": "eval-admin-1"},
    user_entities=["role:Admin", "tenant:default_company"]
)


async def initialize_services() -> None:
    print("🔌 Initializing services...")
    await embedding_service.initialize()
    await reranker_service.initialize()
    await qdrant_service.initialize()
    await agent_service.initialize()
    search_service.initialize()
    print("✅ All services ready\n")


def load_golden_dataset(path: Path, limit: int | None = None) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(
            f"Golden dataset not found at {path}\n"
            "Run: uv run python scripts/generate_golden_dataset.py"
        )
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    if limit:
        entries = entries[:limit]
    print(f"📚 Loaded {len(entries)} questions from golden dataset")
    return entries


async def collect_rag_results(entries: list[dict]) -> list[dict]:
    results = []
    total = len(entries)
    for i, entry in enumerate(entries, 1):
        question     = entry["question"]
        ground_truth = entry.get("ground_truth")
        context      = entry.get("context", "")
        print(f"  [{i}/{total}] {question[:60]}...")
        try:
            req = SearchRequest(query=question, scope="all", limit=5)
            response = await search_service.search(req, user_ctx=EVAL_USER_CTX)
            result = {
                "question": question,
                "answer":   response.answer,
                "contexts": [context],
            }
            if ground_truth:
                result["ground_truth"] = ground_truth
            results.append(result)
        except Exception as e:
            print(f"     ❌ ERROR: {e}")
            results.append({
                "question":     question,
                "answer":       "ERROR",
                "contexts":     [context],
                "ground_truth": ground_truth or "",
            })
    return results


def run_ragas_evaluation(results: list[dict], include_recall: bool = True) -> dict:
    print(f"\n🧪 Running Ragas evaluation (using {settings.GEMINI_MODEL})...")
    
    # نستخدم الموديل المعرف في settings حسب طلبك لترشيد الاستهلاك
    judge_llm = LangchainLLMWrapper(
        ChatGoogleGenerativeAI(
            model=settings.GEMINI_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
        )
    )
    
    from ragas.metrics import Faithfulness, AnswerRelevancy, ContextRecall
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from ragas.embeddings import LangchainEmbeddingsWrapper

    judge_embeddings = LangchainEmbeddingsWrapper(
        GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=settings.GEMINI_API_KEY,
        )
    )
    
    metrics = [Faithfulness(), AnswerRelevancy(strictness=1)]
    if include_recall and any(r.get("ground_truth") for r in results):
        metrics.append(ContextRecall())
    else:
        print("  ⚠️ Skipping Context Recall (no ground_truth available)")

    dataset = Dataset.from_list(results)
    return evaluate(dataset=dataset, metrics=metrics, llm=judge_llm, embeddings=judge_embeddings)


def _extract_scores(eval_results) -> dict:
    """Helper to extract metric mean scores from EvaluationResult or dict."""
    import math
    if hasattr(eval_results, "_repr_dict"):
        return {k: float(v) for k, v in eval_results._repr_dict.items() if v is not None and not math.isnan(v)}
    if hasattr(eval_results, "_scores_dict"):
        scores = {}
        for k, vals in eval_results._scores_dict.items():
            valid_vals = [v for v in vals if v is not None and not math.isnan(v)]
            if valid_vals:
                scores[k] = sum(valid_vals) / len(valid_vals)
        return scores
    if isinstance(eval_results, dict):
        return {k: float(v) for k, v in eval_results.items() if isinstance(v, (int, float)) and not math.isnan(v)}
    return {}


def print_report(eval_results, n_questions: int) -> None:
    print("\n" + "=" * 60)
    print("📊 RAG Quality Evaluation Report")
    print(f"   Questions: {n_questions}")
    print(f"   Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    score_map = {
        "faithfulness":     ("🛡️  Faithfulness (Anti-Hallucination)", 0.80),
        "answer_relevancy": ("🎯 Answer Relevancy",                  0.75),
        "context_recall":   ("🔍 Context Recall (Qdrant Quality)",   0.70),
    }
    scores = _extract_scores(eval_results)
    for key, (label, threshold) in score_map.items():
        score = scores.get(key)
        if score is None:
            continue
        bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
        status = "✅ OK" if score >= threshold else "⚠️ BELOW THRESHOLD"
        print(f"\n  {label}")
        print(f"  [{bar}] {score:.2f}  {status}")

    print("\n" + "=" * 60 + "\n")


def save_results(eval_results, n_questions: int) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RESULTS_DIR / f"eval_{ts}.json"
    scores = _extract_scores(eval_results)
    saved = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "n_questions": n_questions,
        "scores":      scores,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)
    print(f"💾 Results saved to: {path}")


async def main(args: argparse.Namespace) -> None:
    await initialize_services()
    try:
        entries    = load_golden_dataset(DATASET_PATH, limit=args.limit)
        rag_results = await collect_rag_results(entries)
        eval_results = run_ragas_evaluation(
            rag_results,
            include_recall=not args.no_recall,
        )
        print_report(eval_results, len(entries))
        save_results(eval_results, len(entries))
    finally:
        await qdrant_service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit",     type=int, default=None)
    parser.add_argument("--no-recall", action="store_true")
    asyncio.run(main(parser.parse_args()))
