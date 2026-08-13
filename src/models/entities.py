from enum import StrEnum

class ContentType(StrEnum):
    """نوع المقطع المخزّن في Qdrant — يُحدد مصدره وسياقه."""
    VIDEO_CHUNK            = "video_chunk"
    PDF_CHUNK              = "pdf_chunk"
    STANDALONE_VIDEO_CHUNK = "standalone_video_chunk"
    PLAYLIST_VIDEO_CHUNK   = "playlist_video_chunk"

class SourceType(StrEnum):
    YOUTUBE = "youtube"
    PDF     = "pdf"
