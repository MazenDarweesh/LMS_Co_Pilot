from groq import AsyncGroq
from src.core.config import settings

class TranscriptionService:
    def __init__(self):
        # 2026 Best Practice: Reuse a single AsyncGroq client instance
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = "whisper-large-v3"

    async def transcribe(self, file_path: str) -> list[dict]:
        """Transcribes audio using Groq Whisper-v3."""
        with open(file_path, "rb") as file:
            transcription = await self.client.audio.transcriptions.create(
                file=(file_path, file.read()),
                model=self.model,
                response_format="verbose_json", # For timestamps
            )
        
        structured_text = []
        # Whisper returns segments with timestamps
        for segment in transcription.segments:
            structured_text.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"]
            })
        
        return structured_text
