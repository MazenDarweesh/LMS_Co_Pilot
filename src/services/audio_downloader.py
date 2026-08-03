import os
import asyncio
import structlog
from typing import List, Any
import yt_dlp
from pydub import AudioSegment

logger = structlog.get_logger()

class AudioDownloaderService:
    def __init__(self, output_dir: str = "downloads"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    # ---------------------------------------------------------
    # 1. الدوال المتزامنة (Synchronous Blocking Functions)
    # ---------------------------------------------------------
    def _download_youtube_audio_sync(self, youtube_url: str) -> str:
        """يقوم بتحميل ملف الصوت بأفضل جودة أصلية مدعومة (m4a/webm) دون إعادة تحويل (لزيادة السرعة القصوى)."""
        outtmpl = os.path.join(self.output_dir, "%(id)s.%(ext)s")
        ydl_opts = {
            'format': 'm4a/bestaudio/best', # الأفضل لـ Whisper والأسرع لعدم الحاجة لتحويله
            'outtmpl': outtmpl,
            'quiet': True,
            'no_warnings': True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            # استرجاع المسار النهائي للملف المحمل بالامتداد الأصلي (m4a أو webm)
            file_path = ydl.prepare_filename(info)
            return file_path

    def _chunk_audio_file_sync(self, file_path: str, chunk_duration_ms: int = 15 * 60 * 1000) -> List[str]:
        """يقوم بتقطيع ملف الصوت الكبير إلى أجزاء لتجنب قيود حجم ملفات الـ API (25MB)."""
        audio: Any = AudioSegment.from_file(file_path)
        
        # 1. Best Practice: تحويل الصوت إلى Mono (قناة واحدة) لتقليل حجم الملف للنصف لأن Whisper لا يحتاج للـ Stereo
        audio = audio.set_channels(1)

        chunks = []
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # 2. Best Practice: إضافة تداخل (Overlap) بمقدار ثانيتين لمنع قطع الكلمات في المنتصف بين المقاطع
        overlap_ms = 2000 

        for i, start_ms in enumerate(range(0, len(audio), chunk_duration_ms)):
            # تمديد نهاية المقطع لتشمل التداخل (إلا إذا تجاوز طول الملف الأصلي)
            end_ms = min(start_ms + chunk_duration_ms + overlap_ms, len(audio))
            chunk = audio[start_ms:end_ms]

            chunk_path = os.path.join(self.output_dir, f"{base_name}_chunk_{i}.mp3")
            
            # 3. Best Practice: تصدير الصوت بمعدل نقل بيانات منخفض (64k) مخصص للكلام البشري لتصغير حجم الملف للربع
            chunk.export(chunk_path, format="mp3", parameters=["-b:a", "64k"])
            chunks.append(chunk_path)

        return chunks

    # ---------------------------------------------------------
    # 2. الدوال غير المتزامنة (Async Wrappers)
    # ---------------------------------------------------------
    async def download_audio(self, youtube_url: str) -> str:
        """واجهة غير متزامنة لتحميل الصوت بدون تجميد السيرفر."""
        logger.info("Starting audio download", url=youtube_url)
        file_path = await asyncio.to_thread(self._download_youtube_audio_sync, youtube_url)
        logger.info("Audio downloaded successfully", file_path=file_path)
        return file_path

    async def chunk_audio(self, file_path: str) -> List[str]:
        """واجهة غير متزامنة لتقطيع الصوت."""
        logger.info("Starting audio chunking", file_path=file_path)
        chunks = await asyncio.to_thread(self._chunk_audio_file_sync, file_path)
        logger.info("Audio chunked successfully", chunks_count=len(chunks))
        return chunks

audio_downloader = AudioDownloaderService()