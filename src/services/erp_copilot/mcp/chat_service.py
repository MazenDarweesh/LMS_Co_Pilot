"""
Unified General Chat + LMS + ERP Navigation Service
==================================================
Provides a tool-calling conversational assistant (`UnifiedChatService`) that:
1. Answers general questions naturally in Egyptian/MSA Arabic (and English terms).
2. Searches LMS training videos & documents via `search_lms_lessons` (reusing `search_service`),
   streaming retrieved citations into SSE `sources` events.
3. Resolves ERP screen navigation via `navigate_erp_screen` (reusing `erp_service.resolve_navigation`),
   streaming `{decision, screen, pageId, screenKey, reason}` into SSE `nav_action` events.
4. Enforces strict No-MCP honesty when `settings.MCP_ENABLED=False` (live ERP tools disabled;
   never invents live ERP invoices or balances).
5. Records structured black-box trace events via `session_telemetry.append_session_event` with
   `trace_id` and zero secret/token leakage.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
import json
import time
from typing import Any
import uuid

from fastapi import Request
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    BaseMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.utils import message_chunk_to_message
from langchain_core.tools import BaseTool, StructuredTool
import structlog

from src.core.config import settings
from src.core.prompts import (
    build_unified_chat_turn_context,
    get_unified_chat_system_prompt,
)
from src.models.auth_models import UserContext
from src.models.erp_models import NavCandidateIn, NavRequest, NavResolution
from src.models.mcp_chat_models import ChatHistoryMessage, ErpChatStreamRequest
from src.models.search_models import SearchRequest
from src.services.cognitive_search.search.memory_budget_manager import trim_messages
from src.services.cognitive_search.search_service import search_service
from src.services.erp_copilot.agentic_stepper.session_telemetry import append_session_event
from src.services.erp_copilot.erp_service import erp_service
from src.services.erp_copilot.forms_catalog_service import forms_catalog_service
from src.services.erp_copilot.mcp.client_factory import (
    BLOCKED_MUTATION_TOOLS,
    _scrub_secrets,
    filter_llm_tools,
)
from src.services.erp_copilot.mcp.llm_provider import (
    build_chat_model,
    resolve_chat_provider_and_model,
)
from src.services.shared_infrastructure import get_guest_user_context

logger = structlog.get_logger()

_SENSITIVE_ARG_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "secret",
        "authorization",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
    }
)
_MAX_TOOL_ROUNDS = 5


def _collect_secret_values() -> tuple[str, ...]:
    candidates = (
        settings.GEMINI_API_KEY,
        settings.GROQ_API_KEY,
        settings.ANTHROPIC_API_KEY,
        settings.JWT_SECRET,
        settings.SERVICE_TOKEN,
    )
    return tuple(val for val in candidates if isinstance(val, str) and len(val) >= 4)


def _redact_tool_args(args: Any) -> dict[str, Any]:
    if not isinstance(args, dict):
        return {}
    redacted: dict[str, Any] = {}
    for key, val in args.items():
        if str(key).strip().lower() in _SENSITIVE_ARG_KEYS:
            redacted[str(key)] = "[REDACTED]"
        elif isinstance(val, dict):
            redacted[str(key)] = _redact_tool_args(val)
        else:
            redacted[str(key)] = val
    return redacted


def _extract_text_from_content(content: Any) -> str:
    """Extracts plain text from string or LangChain multi-block content payloads."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                block_type = str(block.get("type") or "").lower()
                if block_type in {"text", "output_text", ""}:
                    text_val = block.get("text")
                    if isinstance(text_val, str):
                        parts.append(text_val)
        return "".join(parts)
    return ""


def _build_system_message(system_prompt: str, provider: str) -> SystemMessage:
    """
    Wraps the static system prompt.
    For Anthropic (`claude-*`) with prompt caching enabled, attaches the official
    `cache_control: {"type": "ephemeral"}` breakpoint on the system block, which
    caches both `tools` and `system` in Anthropic's `Tools -> System -> Messages` order.
    """
    if settings.CHAT_PROMPT_CACHE_ENABLED and provider == "anthropic":
        return SystemMessage(
            content=[
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        )
    return SystemMessage(content=system_prompt)


def _build_history_messages(
    history: Sequence[ChatHistoryMessage],
    query: str,
    turn_context: str = "",
) -> list[BaseMessage]:
    """
    Converts client history to LangChain messages (ignoring client-injected system messages)
    and enforces `settings.AGENT_MAX_HISTORY_MESSAGES` + token budget via `trim_messages`.
    Per-turn dynamic ERP/LMS context is prepended to the final `HumanMessage` so the
    leading `Tools + System` prefix remains 100% static for provider prompt caching.
    """
    lc_messages: list[BaseMessage] = []
    for item in history:
        text = (item.content or "").strip()
        if not text:
            continue
        if item.role == "user":
            lc_messages.append(HumanMessage(content=text))
        elif item.role == "assistant":
            lc_messages.append(AIMessage(content=text))

    user_text = query.strip()
    if turn_context:
        user_text = f"{turn_context}\n\n{user_text}"
    lc_messages.append(HumanMessage(content=user_text))
    max_msgs = max(1, int(settings.AGENT_MAX_HISTORY_MESSAGES))
    return trim_messages(
        messages=lc_messages,
        max_messages=max_msgs,
        max_tokens_approx=settings.AGENT_MAX_CONTEXT_TOKENS,
    )


def _build_catalog_nav_candidates(limit: int = 1200) -> list[NavCandidateIn]:
    """Builds fallback `NavCandidateIn` entries from the ERP screens catalog when UI candidates are absent."""
    forms_catalog_service._ensure_loaded()
    candidates: list[NavCandidateIn] = []
    seen_ids: set[str] = set()

    for pid, meta in forms_catalog_service._screens_catalog_by_id.items():
        if len(candidates) >= limit:
            break
        id_str = str(pid)
        label = str(meta.get("name_ar") or meta.get("screen_key") or "").strip()
        if not label or id_str in seen_ids:
            continue
        seen_ids.add(id_str)
        module = str(meta.get("module") or "").strip()
        candidates.append(
            NavCandidateIn(
                id=id_str,
                label=label,
                path=[module] if module else [],
            )
        )
    return candidates


def _resolve_nav_metadata(
    top_id: str,
    candidates: Sequence[NavCandidateIn],
) -> tuple[str | None, int | None, str | None]:
    """Resolves `(screen_label, page_id, screen_key)` for a chosen navigation candidate ID."""
    forms_catalog_service._ensure_loaded()
    matched_cand = next((c for c in candidates if c.id == top_id), None)

    cat_entry: dict[str, Any] | None = None
    page_id: int | None = None
    clean_id = top_id.strip()

    if clean_id.isdigit():
        page_id = int(clean_id)
        cat_entry = (
            forms_catalog_service._screens_catalog_by_id.get(page_id)
            or forms_catalog_service.get_form_by_page_id(page_id)
        )
        screen_key = (
            str(cat_entry.get("screen_key")).strip()
            if cat_entry and cat_entry.get("screen_key")
            else clean_id
        )
    else:
        cat_entry = (
            forms_catalog_service._screens_catalog_by_key.get(clean_id.lower())
            or forms_catalog_service.get_form_by_screen_key(clean_id)
        )
        raw_pid = (
            (cat_entry.get("default_page_id") or cat_entry.get("page_id"))
            if cat_entry
            else None
        )
        if raw_pid is not None and str(raw_pid).isdigit():
            page_id = int(raw_pid)
        screen_key = (
            str(cat_entry.get("screen_key")).strip()
            if cat_entry and cat_entry.get("screen_key")
            else clean_id
        )

    screen_label = (
        (matched_cand.label if matched_cand else None)
        or (str(cat_entry.get("name_ar")).strip() if cat_entry and cat_entry.get("name_ar") else None)
        or clean_id
    )
    return screen_label, page_id, screen_key


def _has_arabic(text: str) -> bool:
    return any("\u0600" <= ch <= "\u06FF" for ch in (text or ""))


def _is_no_info_answer(answer: str) -> bool:
    """True when the RAG answer states no matching course content exists and cites no sources."""
    clean = (answer or "").strip()
    if not clean:
        return True
    if "[1]" in clean:
        return False
    neg_markers = (
        "لا تتوفر",
        "لا توجد معلومات",
        "لا يوجد في الدروس",
        "غير مذكور",
        "لم يتم ذكر",
        "لم يرد في الدروس",
        "لا تحتوي الدروس",
        "لا تتناول الدروس",
    )
    return any(m in clean for m in neg_markers)


def _is_transient_provider_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    return any(tok in msg for tok in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "OVERLOADED"))


def _resolve_fallback_provider_model(provider: str, model: str) -> tuple[str, str] | None:
    if provider == "google":
        if model != "gemini-2.5-flash":
            return ("google", "gemini-2.5-flash")
        if (settings.GROQ_API_KEY or "").strip():
            return ("groq", "llama-3.3-70b-versatile")
    elif provider == "groq" and (settings.GEMINI_API_KEY or "").strip():
        return ("google", "gemini-2.5-flash")
    return None


def _format_nav_action(
    resolution: NavResolution,
    candidates: Sequence[NavCandidateIn],
) -> dict[str, Any]:
    """Maps `NavResolution` to the frontend `nav_action` SSE contract with strict assistant instructions."""
    top = resolution.candidates[0] if resolution.candidates else None
    if top is None:
        return {
            "decision": resolution.decision,
            "status": "not_found",
            "screen": None,
            "pageId": None,
            "screenKey": None,
            "reason": "يرجى توضيح اسم الشاشة المطلوبة في النظام.",
            "assistant_instruction": "لم يتم العثور على شاشة مطابقة ولم يتم فتح أي شاشة. أخبر المستخدم بوضوح أن الشاشة غير موجودة أو اطلب توضيح اسمها.",
        }

    screen_label, page_id, screen_key = _resolve_nav_metadata(top.id, candidates)
    if resolution.decision == "go":
        status = "navigated"
        instruction = f"تم فتح شاشة «{screen_label}» فعلياً. أكد للمستخدم بالاسم العربي فقط دون ذكر أي كود إنجليزي."
    elif resolution.decision == "ask":
        status = "needs_user_choice"
        instruction = "لم يتم فتح أي شاشة بعد لأن الطلب يحتمل أكثر من شاشة. اطلب من المستخدم اختيار الشاشة المطلوبة من الأزرار الظاهرة ولا تقل أنه تم فتحها."
    else:
        status = "not_found"
        instruction = "لم يتم فتح أي شاشة لأن الطلب غير واضح. اطلب من المستخدم تحديد اسم الشاشة بدقة."

    payload: dict[str, Any] = {
        "decision": resolution.decision,
        "status": status,
        "screen": screen_label,
        "pageId": page_id,
        "screenKey": screen_key,
        "reason": top.reason,
        "assistant_instruction": instruction,
    }
    if resolution.decision == "ask" and len(resolution.candidates) > 1:
        options: list[dict[str, Any]] = []
        for cand in resolution.candidates[:3]:
            opt_label, opt_pid, opt_key = _resolve_nav_metadata(cand.id, candidates)
            options.append(
                {
                    "id": cand.id,
                    "label": opt_label,
                    "screen": opt_label,
                    "pageId": opt_pid,
                    "screenKey": opt_key,
                    "confidence": cand.confidence,
                    "reason": cand.reason,
                }
            )
        payload["candidates"] = options
    return payload


class UnifiedChatService:
    """Singleton orchestrator for general conversational AI, LMS search, and ERP navigation."""

    def __init__(
        self,
        *,
        model_factory: Callable[..., BaseChatModel] = build_chat_model,
        search_svc: Any = search_service,
        erp_svc: Any = erp_service,
    ) -> None:
        self._model_factory = model_factory
        self._search_service = search_svc
        self._erp_service = erp_svc
        self._initialized = False

    def initialize(self) -> None:
        """Called from FastAPI lifespan — never performs network I/O."""
        self._initialized = True
        provider, model = resolve_chat_provider_and_model()
        logger.info(
            "Unified Chat service ready ✅",
            provider=provider,
            model=model,
            mcp_enabled=settings.MCP_ENABLED,
        )

    async def close(self) -> None:
        self._initialized = False

    def _select_safe_mcp_tools(self, mcp_tools: Sequence[BaseTool] | None) -> list[BaseTool]:
        """Enforces `MCP_ENABLED` gating and excludes all mutation tools."""
        if not settings.MCP_ENABLED or not mcp_tools:
            return []
        filtered = filter_llm_tools(mcp_tools)
        return [t for t in filtered if t.name not in BLOCKED_MUTATION_TOOLS]

    def _build_builtin_tools(
        self,
        req: ErpChatStreamRequest,
        effective_user: UserContext,
        thread_id: str,
        side_events: list[dict[str, Any]],
        collected_sources: list[dict[str, Any]],
    ) -> list[BaseTool]:
        seen_source_keys: set[tuple[Any, ...]] = set()
        search_svc = self._search_service
        erp_svc = self._erp_service

        async def search_lms_lessons(query: str) -> str:
            """
            ابحث في فيديوهات وملفات منصة DynamicPro Learn التعليمية للإجابة عن أسئلة شرح النظام والمنصة والدروس.
            استخدم هذه الأداة فقط عندما يسأل المستخدم عن كيفية استخدام شاشة أو خطوة في النظام أو محتوى الدروس التدريبية.
            """
            scope = "lessons" if req.lesson_ids else ("lesson" if req.lesson_id else "all")
            search_req = SearchRequest(
                query=query,
                scope=scope,
                lesson_id=req.lesson_id,
                lesson_ids=list(req.lesson_ids),
                erp_key=req.erp_key or req.active_screen_key,
                thread_id=thread_id,
            )
            try:
                resp = await search_svc.search(search_req, effective_user)
            except Exception as exc:
                safe_err = _scrub_secrets(str(exc), _collect_secret_values())
                logger.warning("search_lms_lessons failed", error=safe_err)
                return f"تعذر البحث في محتوى الدروس حالياً ({safe_err})."

            if _is_no_info_answer(resp.answer):
                return resp.answer

            new_sources_added = False
            for src in resp.sources:
                src_dict = src.model_dump()
                src_key = (
                    src_dict.get("type"),
                    src_dict.get("url"),
                    src_dict.get("start"),
                    src_dict.get("page"),
                    src_dict.get("lesson_id"),
                    src_dict.get("title"),
                )
                if src_key not in seen_source_keys:
                    seen_source_keys.add(src_key)
                    collected_sources.append(src_dict)
                    new_sources_added = True

            if new_sources_added or resp.sources:
                side_events.append(
                    {
                        "event": "sources",
                        "data": {"sources": list(collected_sources)},
                    }
                )

            if not resp.sources:
                return resp.answer

            source_lines = []
            for idx, src in enumerate(resp.sources, start=1):
                loc = src.url or (f"صفحة {src.page}" if src.page else "")
                title = src.title or f"المصدر [{idx}]"
                source_lines.append(f"[{idx}] {title}" + (f" ({loc})" if loc else ""))

            return f"{resp.answer}\n\nالمصادر:\n" + "\n".join(source_lines)

        async def navigate_erp_screen(target_screen: str) -> str:
            """
            وجّه المستخدم أو افتح شاشة محددة داخل نظام DynamicPro ERP بناءً على اسم الشاشة أو وصفها المطلوب.
            استخدم هذه الأداة عندما يطلب المستخدم فتح شاشة أو الانتقال إلى صفحة داخل النظام.
            """
            effective_candidates = list(req.candidates) if req.candidates else _build_catalog_nav_candidates()
            active_screen = (req.active_screen_key or req.erp_key or "").strip()
            current_path = [active_screen] if active_screen else []
            # If the LLM translated target_screen to English while the user wrote Arabic, preserve the Arabic query for catalog/ambiguity matching
            effective_query = (
                req.query.strip()
                if (not _has_arabic(target_screen) and _has_arabic(req.query))
                else target_screen
            )[:500]

            if effective_candidates:
                nav_req = NavRequest(
                    user_message=effective_query,
                    candidates=effective_candidates[:1200],
                    current_path=current_path,
                )
            else:
                nav_req = NavRequest.model_construct(
                    user_message=effective_query,
                    candidates=[],
                    current_path=current_path,
                )

            resolution = await erp_svc.resolve_navigation(
                nav_req,
                tenant_id=effective_user.tenant_id,
                user_id=effective_user.user_id,
                known_intent="navigate",
            )
            nav_payload = _format_nav_action(resolution, effective_candidates)
            if resolution.decision in ("go", "ask"):
                side_events.append({"event": "nav_action", "data": nav_payload})
            return json.dumps(nav_payload, ensure_ascii=False)

        return [
            StructuredTool.from_function(
                coroutine=search_lms_lessons,
                name="search_lms_lessons",
                description=(
                    "MANDATORY for any how-to, step-by-step, or screen usage question about DynamicPro ERP "
                    "(e.g., إزاي أعمل..., كيف أضيف..., خطوات...). Searches training videos and PDFs."
                ),
            ),
            StructuredTool.from_function(
                coroutine=navigate_erp_screen,
                name="navigate_erp_screen",
                description=(
                    "Resolve and open an ERP screen when the user asks to open, go to, or switch to a screen. "
                    "Always pass target_screen in the user's original Arabic wording without translating."
                ),
            ),
        ]

    async def _stream_model_turn(
        self,
        runnable: Any,
        messages: list[BaseMessage],
        request: Request | None,
    ) -> AsyncIterator[tuple[str, Any]]:
        """
        Streams a single model round and yields `("token", text)` deltas followed by
        a single `("message", final_ai_message)` tuple (or `("disconnected", None)`).
        """
        if not hasattr(runnable, "astream"):
            result = await runnable.ainvoke(messages)
            text = _extract_text_from_content(getattr(result, "content", result))
            if text:
                yield ("token", text)
            yield ("message", result)
            return

        accumulated: BaseMessageChunk | None = None
        explicit_tool_calls: list[dict[str, Any]] = []

        async for chunk in runnable.astream(messages):
            if request is not None and await request.is_disconnected():
                yield ("disconnected", None)
                return

            if isinstance(chunk, str):
                if chunk:
                    yield ("token", chunk)
                chunk_msg = AIMessageChunk(content=chunk)
                accumulated = chunk_msg if accumulated is None else accumulated + chunk_msg
                continue

            if isinstance(chunk, BaseMessageChunk):
                accumulated = chunk if accumulated is None else accumulated + chunk
            elif isinstance(chunk, AIMessage):
                accumulated = AIMessageChunk(
                    content=chunk.content,
                    tool_calls=list(chunk.tool_calls or []),
                    additional_kwargs=dict(chunk.additional_kwargs or {}),
                    response_metadata=dict(chunk.response_metadata or {}),
                )

            chunk_tc = getattr(chunk, "tool_calls", None)
            if chunk_tc and not getattr(chunk, "tool_call_chunks", None):
                for tc in chunk_tc:
                    explicit_tool_calls.append(dict(tc))

            text_delta = _extract_text_from_content(getattr(chunk, "content", ""))
            if text_delta:
                yield ("token", text_delta)

        if accumulated is None:
            yield ("message", AIMessage(content=""))
            return

        final_msg = message_chunk_to_message(accumulated)
        if explicit_tool_calls and not getattr(final_msg, "tool_calls", None):
            final_msg = AIMessage(
                content=final_msg.content,
                tool_calls=explicit_tool_calls,
                additional_kwargs=dict(getattr(final_msg, "additional_kwargs", {}) or {}),
                response_metadata=dict(getattr(final_msg, "response_metadata", {}) or {}),
            )
        yield ("message", final_msg)

    async def stream_chat(
        self,
        req: ErpChatStreamRequest,
        *,
        user: UserContext | None = None,
        request: Request | None = None,
        mcp_tools: Sequence[BaseTool] | None = None,
        llm: BaseChatModel | Any | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Streams unified chat SSE events as dicts: `{"event": <name>, "data": <dict>}`.
        """
        t0 = time.perf_counter()
        thread_id = (req.thread_id or "").strip() or f"chat_{uuid.uuid4().hex[:12]}"
        trace_id = (req.trace_id or "").strip() or f"trc_{uuid.uuid4().hex[:12]}"
        active_screen = (req.active_screen_key or req.erp_key or "").strip() or None
        effective_user = user or get_guest_user_context()
        secret_values = _collect_secret_values()

        resolved_provider = (provider or settings.CHAT_LLM_PROVIDER or "google").strip().lower()
        resolved_model = (model or settings.CHAT_LLM_MODEL or settings.GEMINI_MODEL or "").strip()

        try:
            resolved_provider, resolved_model = resolve_chat_provider_and_model(
                provider=provider,
                model=model,
            )
            chat_model = llm if llm is not None else self._model_factory(
                provider=resolved_provider,
                model=resolved_model,
            )
        except Exception as exc:
            safe_err = _scrub_secrets(str(exc), secret_values)
            logger.error(
                "Failed to initialize chat LLM provider",
                provider=resolved_provider,
                trace_id=trace_id,
                error=safe_err,
            )
            append_session_event(
                thread_id,
                "ERROR",
                "CHAT.ERROR",
                "Chat model initialization failed",
                {
                    "provider": resolved_provider,
                    "error": safe_err,
                },
                trace_id=trace_id,
                screen_key=active_screen,
            )
            yield {
                "event": "error",
                "data": {
                    "message": f"تعذر تهيئة نموذج المحادثة ({resolved_provider}): {safe_err}",
                    "trace_id": trace_id,
                },
            }
            return

        safe_mcp_tools = self._select_safe_mcp_tools(mcp_tools)
        mcp_active = bool(settings.MCP_ENABLED and safe_mcp_tools)

        append_session_event(
            thread_id,
            "INFO",
            "CHAT.START",
            "Unified chat stream started",
            {
                "provider": resolved_provider,
                "model": resolved_model,
                "mcp_enabled": bool(settings.MCP_ENABLED),
                "mcp_tools_count": len(safe_mcp_tools),
                "query_len": len(req.query),
                "history_count": len(req.history),
                "candidates_count": len(req.candidates),
            },
            trace_id=trace_id,
            screen_key=active_screen,
        )

        side_events: list[dict[str, Any]] = []
        collected_sources: list[dict[str, Any]] = []
        builtin_tools = self._build_builtin_tools(
            req=req,
            effective_user=effective_user,
            thread_id=thread_id,
            side_events=side_events,
            collected_sources=collected_sources,
        )
        all_tools: list[BaseTool] = [*builtin_tools, *safe_mcp_tools]
        tools_by_name: dict[str, BaseTool] = {t.name: t for t in all_tools}

        lesson_scope_hint = (
            ",".join(req.lesson_ids)
            if req.lesson_ids
            else (req.lesson_id or None)
        )
        system_prompt = get_unified_chat_system_prompt(mcp_enabled=mcp_active)
        turn_context = build_unified_chat_turn_context(
            active_screen_key=req.active_screen_key,
            erp_key=req.erp_key,
            has_candidates=bool(req.candidates),
            lesson_scope_hint=lesson_scope_hint,
        )
        conversation = _build_history_messages(req.history, req.query, turn_context=turn_context)
        messages: list[BaseMessage] = [_build_system_message(system_prompt, resolved_provider), *conversation]

        bound_model = (
            chat_model.bind_tools(all_tools)
            if all_tools and hasattr(chat_model, "bind_tools")
            else chat_model
        )

        disconnected = False
        has_nav_action = False
        round_streamed_chars = 0

        try:
            for _round in range(_MAX_TOOL_ROUNDS):
                ai_message: BaseMessage | None = None
                round_streamed_chars = 0

                for attempt in range(2):
                    try:
                        async for kind, val in self._stream_model_turn(bound_model, messages, request):
                            if kind == "disconnected":
                                disconnected = True
                                break
                            if kind == "token":
                                round_streamed_chars += len(val)
                                yield {"event": "token", "data": {"text": val}}
                            elif kind == "message":
                                ai_message = val
                        break
                    except Exception as round_exc:
                        if not _is_transient_provider_error(round_exc):
                            raise
                        if round_streamed_chars >= 120:
                            logger.warning(
                                "Transient provider error after substantive stream; closing gracefully",
                                trace_id=trace_id,
                                streamed_chars=round_streamed_chars,
                                error=_scrub_secrets(str(round_exc), secret_values),
                            )
                            ai_message = AIMessage(content="")
                            break
                        if attempt == 0 and round_streamed_chars == 0 and llm is None:
                            fallback = _resolve_fallback_provider_model(resolved_provider, resolved_model)
                            if fallback is not None:
                                fb_provider, fb_model = fallback
                                logger.warning(
                                    "Transient provider error before tokens; falling back to secondary model",
                                    trace_id=trace_id,
                                    from_model=resolved_model,
                                    to_provider=fb_provider,
                                    to_model=fb_model,
                                )
                                resolved_provider, resolved_model = fb_provider, fb_model
                                chat_model = self._model_factory(provider=resolved_provider, model=resolved_model)
                                messages[0] = _build_system_message(system_prompt, resolved_provider)
                                bound_model = (
                                    chat_model.bind_tools(all_tools)
                                    if all_tools and hasattr(chat_model, "bind_tools")
                                    else chat_model
                                )
                                continue
                        raise

                if disconnected:
                    return

                if ai_message is None:
                    break

                tool_calls = list(getattr(ai_message, "tool_calls", None) or [])
                if not tool_calls:
                    break

                messages.append(ai_message)

                for tc in tool_calls:
                    if request is not None and await request.is_disconnected():
                        return

                    tc_name = str(tc.get("name") or "").strip()
                    tc_args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
                    tc_id = str(tc.get("id") or f"call_{uuid.uuid4().hex[:8]}")
                    safe_args = _redact_tool_args(tc_args)

                    yield {
                        "event": "tool_start",
                        "data": {
                            "tool": tc_name,
                            "args": safe_args,
                            "trace_id": trace_id,
                        },
                    }

                    t_tool = time.perf_counter()
                    tool_obj = tools_by_name.get(tc_name)
                    if tool_obj is None:
                        tool_status = "error"
                        tool_output = f"Tool '{tc_name}' is not available or blocked by policy."
                    else:
                        try:
                            raw_output = await tool_obj.ainvoke(tc_args)
                            tool_output = (
                                raw_output
                                if isinstance(raw_output, str)
                                else json.dumps(raw_output, ensure_ascii=False)
                            )
                            tool_status = "ok"
                        except Exception as tool_exc:
                            tool_status = "error"
                            safe_tool_err = _scrub_secrets(str(tool_exc), secret_values)
                            tool_output = f"حدث خطأ أثناء تنفيذ الأداة {tc_name}: {safe_tool_err}"
                            logger.warning(
                                "Unified chat tool execution failed",
                                tool=tc_name,
                                trace_id=trace_id,
                                error=safe_tool_err,
                            )

                    while side_events:
                        ev = side_events.pop(0)
                        if ev["event"] == "nav_action":
                            has_nav_action = True
                        yield ev

                    tool_ms = round((time.perf_counter() - t_tool) * 1000, 2)
                    append_session_event(
                        thread_id,
                        "INFO" if tool_status == "ok" else "WARN",
                        "CHAT.TOOL_CALL",
                        f"Tool {tc_name} {tool_status}",
                        {
                            "tool_name": tc_name,
                            "args": safe_args,
                            "status": tool_status,
                            "duration_ms": tool_ms,
                        },
                        trace_id=trace_id,
                        screen_key=active_screen,
                    )

                    yield {
                        "event": "tool_end",
                        "data": {
                            "tool": tc_name,
                            "status": tool_status,
                            "duration_ms": tool_ms,
                            "trace_id": trace_id,
                        },
                    }
                    messages.append(
                        ToolMessage(
                            content=tool_output,
                            tool_call_id=tc_id,
                            name=tc_name,
                        )
                    )
            else:
                # Tool round budget reached; request one final synthesis turn without tools.
                async for kind, val in self._stream_model_turn(chat_model, messages, request):
                    if kind == "disconnected":
                        return
                    if kind == "token":
                        yield {"event": "token", "data": {"text": val}}

            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            append_session_event(
                thread_id,
                "INFO",
                "CHAT.DONE",
                "Unified chat stream completed",
                {
                    "provider": resolved_provider,
                    "model": resolved_model,
                    "mcp_enabled": bool(settings.MCP_ENABLED),
                    "sources_count": len(collected_sources),
                    "has_nav_action": has_nav_action,
                    "latency_ms": latency_ms,
                },
                trace_id=trace_id,
                screen_key=active_screen,
            )
            yield {
                "event": "done",
                "data": {
                    "thread_id": thread_id,
                    "trace_id": trace_id,
                    "mcp_enabled": bool(settings.MCP_ENABLED),
                    "provider": resolved_provider,
                    "model": resolved_model,
                    "latency_ms": latency_ms,
                    "metrics": {"total_latency_ms": latency_ms},
                },
            }
        except Exception as exc:
            safe_err = _scrub_secrets(str(exc), secret_values)
            logger.error(
                "Unified chat stream failed",
                trace_id=trace_id,
                provider=resolved_provider,
                error=safe_err,
            )
            append_session_event(
                thread_id,
                "ERROR",
                "CHAT.ERROR",
                "Unified chat stream failed",
                {
                    "provider": resolved_provider,
                    "model": resolved_model,
                    "error": safe_err,
                },
                trace_id=trace_id,
                screen_key=active_screen,
            )
            yield {
                "event": "error",
                "data": {
                    "message": f"حدث خطأ أثناء معالجة المحادثة: {type(exc).__name__}: {safe_err}",
                    "trace_id": trace_id,
                },
            }


# Module-level singleton — initialize() called from FastAPI lifespan
unified_chat_service = UnifiedChatService()
