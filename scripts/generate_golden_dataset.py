"""
scripts/generate_golden_dataset.py
====================================
سكريبت تفاعلي لتوليد أسئلة تقييم من محتوى Qdrant.

الاستخدام:
    uv run python scripts/generate_golden_dataset.py

الخيارات:
    --lessons   lesson-01 lesson-02   ← دروس بعينها (اختياري، الافتراضي = كل الدروس)
    --per-lesson 3                    ← عدد الأسئلة لكل درس
    --total 20                        ← حد أقصى إجمالي (يوقف لما يوصله)
    --output tests/eval/golden_dataset.jsonl

مثال:
    uv run python scripts/generate_golden_dataset.py --lessons lesson-001 lesson-002 --per-lesson 5 --total 10
"""

import sys
import os

# ─── Windows ProactorEventLoop Fix ────────────────────────────────────────────
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# ─── Standard Library ─────────────────────────────────────────────────────────
import asyncio
import json
import random
import argparse
from datetime import datetime, timezone
from pathlib import Path

# ─── Third-Party ──────────────────────────────────────────────────────────────
from google import genai
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchAny, ScrollRequest

# ─── Local ────────────────────────────────────────────────────────────────────
# نضيف الـ root للـ path عشان نقدر نـ import من src
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.core.config import settings


# ─── Gemini Setup ─────────────────────────────────────────────────────────────
gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

QUESTION_PROMPT = """\
أنت مساعد تعليمي متخصص في إنشاء أسئلة تقييم.

من النص التعليمي التالي، اكتب سؤالاً واحداً واضحاً باللغة العربية الفصحى.
الشروط:
- السؤال يُجاب عنه من هذا النص فقط
- السؤال مباشر ولا يتجاوز جملة واحدة
- لا تضع إجابة، اكتب السؤال فقط

النص:
{text}

السؤال:"""


# ─── Helpers ──────────────────────────────────────────────────────────────────
async def fetch_chunks_for_lesson(
    client: AsyncQdrantClient,
    collection: str,
    lesson_id: str,
    per_lesson: int,
) -> list[dict]:
    """يجلب chunks عشوائية لدرس معين من Qdrant."""
    
    # جلب كل الـ chunks الخاصة بالدرس
    results, _ = await client.scroll(
        collection_name=collection,
        scroll_filter=Filter(
            must=[FieldCondition(key="lesson_id", match=MatchAny(any=[lesson_id]))]
        ),
        limit=200,       # أقصى عدد chunks نجلبها
        with_payload=True,
        with_vectors=False,
    )
    
    if not results:
        return []
    
    # اختيار عشوائي — نوزع على الـ chunks المختلفة
    sample_size = min(per_lesson, len(results))
    sampled = random.sample(results, sample_size)
    
    return [
        {
            "chunk_id": str(point.id),
            "lesson_id": lesson_id,
            "text_msa": point.payload.get("text_msa", ""),
            "source_url": point.payload.get("source_url", ""),
        }
        for point in sampled
        if point.payload and point.payload.get("text_msa")
    ]


async def generate_question(text: str) -> str | None:
    """يولّد سؤالاً واحداً من نص عبر Gemini."""
    try:
        prompt = QUESTION_PROMPT.format(text=text[:1500])  # حد الـ context
        response = await asyncio.to_thread(
            gemini_client.models.generate_content,
            model=settings.GEMINI_MODEL,
            contents=prompt,
        )
        question = response.text.strip()
        # تنظيف: إزالة "السؤال:" لو Gemini كتبها
        for prefix in ["السؤال:", "سؤال:", "- "]:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()
        return question if question else None
    except Exception as e:
        print(f"  ⚠️  Gemini error: {e}")
        return None


def append_to_jsonl(path: Path, entry: dict) -> None:
    """يُضيف entry واحد لملف JSONL — آمن للـ append حتى لو الملف كبير."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_existing_chunk_ids(path: Path) -> set[str]:
    """يقرأ الـ chunk_ids الموجودة لتجنب التكرار."""
    if not path.exists():
        return set()
    ids = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    ids.add(json.loads(line)["chunk_id"])
                except (json.JSONDecodeError, KeyError):
                    pass
    return ids


async def list_all_lesson_ids(
    client: AsyncQdrantClient,
    collection: str,
) -> list[str]:
    """يجلب كل الـ lesson_ids الموجودة في Qdrant."""
    # نستخدم facet/scroll للحصول على القيم الفريدة
    results, _ = await client.scroll(
        collection_name=collection,
        limit=1000,
        with_payload=True,
        with_vectors=False,
    )
    lesson_ids = {
        point.payload.get("lesson_id")
        for point in results
        if point.payload and point.payload.get("lesson_id")
    }
    return sorted(lesson_ids)


# ─── Main ──────────────────────────────────────────────────────────────────────
async def main(args: argparse.Namespace) -> None:
    output_path = Path(args.output)
    
    print("\n🔌 Connecting to Qdrant...")
    client = AsyncQdrantClient(
        url=settings.QDRANT_URL,
        api_key=settings.QDRANT_API_KEY or None,
        timeout=30,
    )
    collection = settings.QDRANT_COLLECTION
    
    # ─── تحديد الدروس المستهدفة ──────────────────────────────────────────
    if args.lessons:
        lesson_ids = args.lessons
        print(f"📚 Target lessons: {lesson_ids}")
    else:
        print("📚 No lessons specified — scanning Qdrant for all lessons...")
        lesson_ids = await list_all_lesson_ids(client, collection)
        if not lesson_ids:
            print("❌ No lessons found in Qdrant. Make sure the collection has data.")
            return
        print(f"📚 Found {len(lesson_ids)} lessons: {lesson_ids}")
    
    # ─── تحميل الـ IDs الموجودة لتجنب التكرار ────────────────────────────
    existing_ids = load_existing_chunk_ids(output_path)
    if existing_ids:
        print(f"♻️  Found {len(existing_ids)} existing entries — skipping duplicates")
    
    # ─── الـ Loop الرئيسي ─────────────────────────────────────────────────
    total_generated = 0
    total_limit = args.total

    print(f"\n🚀 Generating up to {args.per_lesson} questions per lesson (max total: {total_limit})")
    print(f"💾 Output: {output_path}\n")
    print("─" * 60)
    
    for lesson_id in lesson_ids:
        if total_generated >= total_limit:
            print(f"\n✅ Reached total limit of {total_limit}. Stopping.")
            break
        
        print(f"\n📖 Lesson: {lesson_id}")
        
        chunks = await fetch_chunks_for_lesson(
            client, collection, lesson_id, args.per_lesson
        )
        
        if not chunks:
            print(f"  ⚠️  No chunks found for lesson '{lesson_id}' — skipping")
            continue
        
        print(f"  📦 Found {len(chunks)} chunks → generating questions...")
        
        lesson_count = 0
        for chunk in chunks:
            if total_generated >= total_limit:
                break
            if chunk["chunk_id"] in existing_ids:
                print(f"  ↩️  Chunk {chunk['chunk_id'][:8]}... already in dataset — skipping")
                continue
            
            question = await generate_question(chunk["text_msa"])
            if not question:
                continue
            
            entry = {
                "chunk_id":    chunk["chunk_id"],
                "lesson_id":   lesson_id,
                "question":    question,
                "context":     chunk["text_msa"],
                "ground_truth": None,       # تُملأ لاحقاً يدوياً أو بـ ragas
                "source_url":  chunk["source_url"],
                "created_at":  datetime.now(timezone.utc).isoformat(),
            }
            
            append_to_jsonl(output_path, entry)
            existing_ids.add(chunk["chunk_id"])
            
            total_generated += 1
            lesson_count += 1
            print(f"  ✅ [{total_generated}/{total_limit}] Q: {question[:70]}...")
        
        print(f"  📊 Generated {lesson_count} questions for '{lesson_id}'")
    
    await client.close()
    
    # ─── الملخص النهائي ────────────────────────────────────────────────────
    print("\n" + "─" * 60)
    print(f"🎉 Done! Generated {total_generated} new questions.")
    print(f"📁 Saved to: {output_path.resolve()}")
    
    # اعرض آخر 3 أسئلة كمثال
    if output_path.exists():
        lines = output_path.read_text(encoding="utf-8").strip().splitlines()
        if lines:
            print("\n📝 Sample from dataset:")
            for line in lines[-3:]:
                entry = json.loads(line)
                print(f"  • [{entry['lesson_id']}] {entry['question']}")


# ─── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Golden Evaluation Dataset from Qdrant chunks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # توليد 5 أسئلة من كل درس، بحد أقصى 20 سؤال
  uv run python scripts/generate_golden_dataset.py --per-lesson 5 --total 20

  # توليد 10 أسئلة من دروس بعينها
  uv run python scripts/generate_golden_dataset.py --lessons lesson-001 lesson-002 --per-lesson 10 --total 20

  # توليد وحفظ في مكان مخصص
  uv run python scripts/generate_golden_dataset.py --per-lesson 3 --total 30 --output data/my_eval.jsonl
        """
    )
    parser.add_argument(
        "--lessons",
        nargs="+",
        default=None,
        metavar="LESSON_ID",
        help="Lesson IDs to generate from (default: all lessons in Qdrant)",
    )
    parser.add_argument(
        "--per-lesson",
        type=int,
        default=3,
        dest="per_lesson",
        metavar="N",
        help="Max questions per lesson (default: 3)",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=30,
        metavar="N",
        help="Max total questions to generate (default: 30)",
    )
    parser.add_argument(
        "--output",
        default="tests/eval/golden_dataset.jsonl",
        metavar="PATH",
        help="Output JSONL file path (default: tests/eval/golden_dataset.jsonl)",
    )
    
    parsed = parser.parse_args()
    asyncio.run(main(parsed))
