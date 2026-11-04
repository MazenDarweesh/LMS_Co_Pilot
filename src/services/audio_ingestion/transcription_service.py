import re
import aiofiles
from groq import AsyncGroq
from src.core.config import settings
from src.core.prompts import WHISPER_ERP_DOMAIN_PROMPT

class TranscriptionService:
    def __init__(self):
        # 2026 Best Practice: Reuse a single AsyncGroq client instance
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)
        self.model = "whisper-large-v3"

    async def transcribe(self, file_path: str) -> list[dict]:
        """Transcribes audio using Groq Whisper-v3 with ERP domain prompt and non-blocking I/O."""
        async with aiofiles.open(file_path, "rb") as file:
            file_bytes = await file.read()

        transcription = await self.client.audio.transcriptions.create(
            file=(file_path, file_bytes),
            model=self.model,
            prompt=WHISPER_ERP_DOMAIN_PROMPT,
            response_format="verbose_json",  # For timestamps
        )
        
        structured_text = []
        # Whisper returns segments with timestamps
        for segment in transcription.segments:
            clean_text = re.sub(r"[\u0E00-\u0E7F]", "", segment["text"])
            structured_text.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": clean_text
            })
        
        return structured_text
