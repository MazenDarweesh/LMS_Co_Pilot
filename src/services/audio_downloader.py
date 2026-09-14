import os
import asyncio
import structlog
import glob
import yt_dlp

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
            'noplaylist': True, # منع تحميل قائمة التشغيل بالكامل إذا كان الرابط جزءاً من قائمة تشغيل
            # 🚀 2026 Best Practice: Bypass YouTube 403 by using mobile clients (correct dict format)
            'extractor_args': {
                'youtube': {
                    'player_client': ['android'],
                    'player_skip': ['webpage'],
                }
            },
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            
            # إذا كان الرابط يحتوي على معلومات قائمة تشغيل، فإن yt-dlp قد يعيد هيكل قائمة تحتوي على entries
            if info and 'entries' in info:
                # نأخذ بيانات الفيديو الأول الفعلي الذي تم تحميله
                info = info['entries'][0]

            # استرجاع المسار النهائي للملف المحمل بالامتداد الأصلي (m4a أو webm)
            file_path = ydl.prepare_filename(info)
            return file_path

    def _chunk_audio_file_sync(self, file_path: str, chunk_duration_ms: int = 120 * 1000) -> list[str]:
        """يقوم بتقطيع ملف الصوت الكبير إلى أجزاء لتجنب قيود حجم ملفات الـ API (25MB)."""
        import subprocess
        
        base_name = os.path.splitext(os.path.basename(file_path))[0]
        
        # Fast-Path Caching: تخطي التقطيع إذا كانت المقاطع موجودة مسبقاً
        existing_chunks = sorted(glob.glob(os.path.join(self.output_dir, f"{base_name}_chunk_*.mp3")))
        if existing_chunks:
            return existing_chunks

        chunk_pattern = os.path.join(self.output_dir, f"{base_name}_chunk_%03d.mp3")
        
        # 🚀 2026 Best Practice: استخدام FFmpeg مباشرة لتقطيع الملف بدون استهلاك الرامات (عملية شبه لحظية)
        # -ac 1: تحويل الصوت إلى Mono لتقليل الحجم
        # -b:a 64k: معدل نقل منخفض مخصص للكلام البشري
        # -f segment -segment_time 120: تقطيع كل 120 ثانية
        cmd = [
            "ffmpeg", "-y", "-i", file_path,
            "-f", "segment", "-segment_time", str(chunk_duration_ms // 1000),
            "-c:a", "libmp3lame", "-b:a", "64k", "-ac", "1",
            chunk_pattern
        ]
        
        try:
            # تشغيل الأمر وانتظار انتهائه
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            logger.error("FFmpeg chunking failed", error=str(e))
            raise RuntimeError(f"FFmpeg chunking failed: {e}")
            
        # بعد الانتهاء، نجلب جميع المقاطع التي تم توليدها
        generated_chunks = sorted(glob.glob(os.path.join(self.output_dir, f"{base_name}_chunk_*.mp3")))
        return generated_chunks

    # ---------------------------------------------------------
    # 2. الدوال غير المتزامنة (Async Wrappers)
    # ---------------------------------------------------------
    async def download_audio(self, youtube_url: str) -> str:
        """واجهة غير متزامنة لتحميل الصوت بدون تجميد السيرفر."""
        logger.info("Starting audio download", url=youtube_url)
        file_path = await asyncio.to_thread(self._download_youtube_audio_sync, youtube_url)
        logger.info("Audio downloaded successfully", file_path=file_path)
        return file_path

    async def chunk_audio(self, file_path: str) -> list[str]:
        """واجهة غير متزامنة لتقطيع الصوت."""
        logger.info("Starting audio chunking", file_path=file_path)
        chunks = await asyncio.to_thread(self._chunk_audio_file_sync, file_path)
        logger.info("Audio chunked successfully", chunks_count=len(chunks))
        return chunks

audio_downloader = AudioDownloaderService()