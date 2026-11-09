"""
RAG Context & Scope Filter Builder Module.
Responsible for translating SearchRequest scopes into Qdrant filters,
validating retrieved chunks, compiling context strings, and constructing SourceItem DTOs.
"""

from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue
from src.models.search_models import SearchRequest, SourceItem


def build_scope_filter(req: SearchRequest) -> Filter | None:
    must = []

    # 1. Scope Content Type Filtering
    if req.scope == "course":
        must.append(FieldCondition(key="content_type", match=MatchAny(any=["video_chunk", "pdf_chunk"])))
    elif req.scope == "standalone":
        must.append(FieldCondition(key="content_type", match=MatchValue(value="standalone_video_chunk")))
    elif req.scope == "playlist":
        must.append(FieldCondition(key="content_type", match=MatchValue(value="playlist_video_chunk")))

    # 2. Hierarchical Scope ID Filtering
    # Explicit binding: only filter by lesson/unit/module when scope specifically targets that level.
    # Matches both single fields and multi-reference array fields (Process Once, Reference Everywhere).
    if (req.scope in ("lessons", "multi_lesson") or req.lesson_ids) and req.lesson_ids:
        must.append(Filter(should=[
            FieldCondition(key="lesson_id", match=MatchAny(any=req.lesson_ids)),
            FieldCondition(key="lesson_ids", match=MatchAny(any=req.lesson_ids)),
        ]))
    elif req.scope == "lesson" and req.lesson_id:
        must.append(Filter(should=[
            FieldCondition(key="lesson_id", match=MatchValue(value=req.lesson_id)),
            FieldCondition(key="lesson_ids", match=MatchValue(value=req.lesson_id)),
        ]))
    elif req.scope == "unit" and req.unit_id:
        must.append(FieldCondition(key="unit_id", match=MatchValue(value=req.unit_id)))
    elif req.scope == "module" and req.module_id:
        must.append(Filter(should=[
            FieldCondition(key="module_id", match=MatchValue(value=req.module_id)),
            FieldCondition(key="module_ids", match=MatchValue(value=req.module_id)),
        ]))
    elif req.scope not in {"all", "module", "unit", "lesson", "lessons", "multi_lesson"}:
        # Backward compatibility for direct ID queries or legacy playlist/video requests
        if req.lesson_ids:
            must.append(Filter(should=[
                FieldCondition(key="lesson_id", match=MatchAny(any=req.lesson_ids)),
                FieldCondition(key="lesson_ids", match=MatchAny(any=req.lesson_ids)),
            ]))
        elif req.lesson_id:
            must.append(Filter(should=[
                FieldCondition(key="lesson_id", match=MatchValue(value=req.lesson_id)),
                FieldCondition(key="lesson_ids", match=MatchValue(value=req.lesson_id)),
            ]))
        elif req.unit_id:
            must.append(FieldCondition(key="unit_id", match=MatchValue(value=req.unit_id)))
        elif req.module_id:
            must.append(Filter(should=[
                FieldCondition(key="module_id", match=MatchValue(value=req.module_id)),
                FieldCondition(key="module_ids", match=MatchValue(value=req.module_id)),
            ]))

    if req.playlist_id:
        must.append(FieldCondition(key="playlist_id", match=MatchValue(value=req.playlist_id)))
    if req.video_id:
        must.append(FieldCondition(key="video_id", match=MatchValue(value=req.video_id)))

    # 3. Level & Content Type Filtering
    if req.level_id:
        must.append(FieldCondition(key="level_id", match=MatchValue(value=req.level_id)))
    if req.type_id:
        must.append(FieldCondition(key="type_id", match=MatchValue(value=req.type_id)))

    return Filter(must=must) if must else None


def filter_valid_chunks(chunks: list[dict]) -> list[dict]:
    """
    تصفية المقاطع لاستبعاد أي مقطع غير مكتمل التوصيف قبل بناء السياق والمصادر.
    تضمن هذه الخطوة المطابقة الكاملة بين عدد وأرقام المقاطع المرسلة إلى Gemini
    وبين المصفوفة النهائية للمصادر المرجعة للواجهة الأمامية.
    """
    valid = []
    for chunk in chunks:
        c_type = chunk.get("content_type")
        if c_type in ["video_chunk", "standalone_video_chunk", "playlist_video_chunk"]:
            if chunk.get("source_url"):
                valid.append(chunk)
        elif c_type == "pdf_chunk":
            valid.append(chunk)
    return valid


def build_rag_context_str(chunks: list[dict]) -> str:
    context_blocks = []
    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text_msa", "")
        url = chunk.get("source_url", "")
        start_time = chunk.get("start_time")
        end_time = chunk.get("end_time")

        source_info = f"[{i}] {text}\n(المصدر: {url}"
        if start_time is not None:
            source_info += f" - من {start_time} إلى {end_time} ثانية"
        source_info += ")"
        context_blocks.append(source_info)

    return "\n\n".join(context_blocks)


def build_source_items(chunks: list[dict]) -> list[SourceItem]:
    """
    ينشئ كائنات SourceItem مهيكلة مرتبة متسلسلاً من 1 إلى N بناءً على المقاطع المصفاة.
    يضمن توفير حقل 'title' لعرضه مباشرة في بطاقات المصادر بالواجهة.
    """
    sources: list[SourceItem] = []
    for i, chunk in enumerate(chunks, 1):
        c_type = chunk.get("content_type")
        if c_type in ["video_chunk", "standalone_video_chunk", "playlist_video_chunk"]:
            start_s = chunk.get("start_time")
            end_s = chunk.get("end_time")
            if start_s is not None and end_s is not None:
                s_min, s_sec = divmod(int(start_s), 60)
                e_min, e_sec = divmod(int(end_s), 60)
                title = f"المصدر [{i}] — مقطع فيديو ({s_min:02d}:{s_sec:02d} - {e_min:02d}:{e_sec:02d})"
            else:
                title = f"المصدر [{i}] — مقطع فيديو"
            sources.append(SourceItem(
                type="video",
                url=chunk.get("source_url"),
                title=title,
                start=start_s,
                end=end_s,
                lesson_id=chunk.get("lesson_id"),
            ))
        elif c_type == "pdf_chunk":
            section = chunk.get("section_title")
            page = chunk.get("page_number")
            if section:
                title = f"المصدر [{i}] — {section}"
            elif page:
                title = f"المصدر [{i}] — صفحة {page}"
            else:
                title = f"المصدر [{i}] — مستند PDF"
            sources.append(SourceItem(
                type="pdf",
                title=title,
                page=page,
                section=section,
                lesson_id=chunk.get("lesson_id"),
            ))
    return sources

