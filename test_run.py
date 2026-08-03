import asyncio
import json
import traceback
from src.services.pipeline_orchestrator import pipeline_orchestrator

async def run_test():
    # ضع هنا رابط لفيديو يوتيوب قصير (يفضل أقل من 5 دقائق لتسريع الاختبار)
    test_url = "https://www.youtube.com/watch?v=AyUm61M9E68&list=PLALpxYItgYIkYOCjSRfZIKTaq8YiuMuMQ&index=2" # استبدله برابطك
    lesson_id = "test_lesson_001"
    
    print(f"🚀 Starting Pipeline for video: {test_url}")
    print("⏳ This might take a few minutes (Downloading -> Chunking -> Whisper -> Gemini)...")
    
    try:
        results = await pipeline_orchestrator.run_audio_pipeline(youtube_url=test_url, lesson_id=lesson_id)
        
        print("\n✅ Pipeline Completed Successfully!\n")
        print("📊 --- Final Output JSON --- 📊")
        
        # تحويل النتائج إلى قائمة من الـ Dictionaries لطباعتها كـ JSON
        results_dict = [segment.model_dump() for segment in results]
        print(json.dumps(results_dict, ensure_ascii=False, indent=4))
        
        # حفظ النتيجة في ملف لمراجعتها بسهولة
        with open("pipeline_test_output.json", "w", encoding="utf-8") as f:
            json.dump(results_dict, f, ensure_ascii=False, indent=4)
        print("\n💾 Output saved to 'pipeline_test_output.json'")

    except Exception as e:
        print(f"\n❌ Pipeline Failed: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_test())
