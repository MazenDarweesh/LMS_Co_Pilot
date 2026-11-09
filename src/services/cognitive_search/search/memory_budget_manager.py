"""
Conversational Memory & Token Budget Manager Module.
Handles sliding-window history trimming, character-based token budget guards,
and LangGraph agent node invocation.
"""

import asyncio
import time
import structlog
from google import genai
from google.genai import types
from langchain_core.messages import AIMessage, HumanMessage

from src.agents.base_agent import AgentState
from src.core.config import settings
from src.core.prompts import get_rag_system_prompt

logger = structlog.get_logger()


def trim_messages(
    messages: list,
    max_messages: int,
    max_tokens_approx: int,
) -> list:
    """
    Sliding Window Memory Trimmer — 2026 Best Practice.

    Strategy (two-layer defense):
    Layer 1: Keep only the last `max_messages` (hard message count limit).
    Layer 2: If total chars still too large, trim further from the oldest.

    Note: We use character count as a cheap proxy for tokens (1 token ≈ 4 chars
    in Arabic/English mixed text). This avoids the overhead of a full tokenizer call.

    Always preserves the LAST message (the new student question) intact.
    """
    if not messages:
        return messages

    # Layer 1: Sliding Window — trim by message count
    trimmed = list(messages[-max_messages:]) if len(messages) > max_messages else list(messages)

    # Layer 2: Token Budget Guard — trim by approximate character budget
    # 1 token ≈ 4 chars (conservative estimate for Arabic)
    char_budget = max_tokens_approx * 4
    total_chars = sum(len(getattr(m, "content", "")) for m in trimmed)

    while total_chars > char_budget and len(trimmed) > 1:
        # Always drop from the oldest end (index 0), never drop the last message
        removed = trimmed.pop(0)
        total_chars -= len(getattr(removed, "content", ""))

    return trimmed


async def execute_langgraph_agent_node(
    state: AgentState,
    gemini_client: genai.Client | None,
) -> dict:
    raw_messages = state["messages"]
    context_str = state["context"].get("context_str", "") if state.get("context") else ""

    # Apply Sliding Window + Token Budget trimming before sending to Gemini
    messages = trim_messages(
        messages=raw_messages,
        max_messages=settings.AGENT_MAX_HISTORY_MESSAGES,
        max_tokens_approx=settings.AGENT_MAX_CONTEXT_TOKENS,
    )

    if len(raw_messages) != len(messages):
        logger.debug(
            "Memory trimmed",
            original_count=len(raw_messages),
            trimmed_count=len(messages),
        )

    gemini_contents = []
    for msg in messages:
        role = "user" if isinstance(msg, HumanMessage) else "model"
        gemini_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=msg.content)]))

    num_sources = state["context"].get("num_sources", 1) if state.get("context") else 1
    is_multi_lesson = state["context"].get("is_multi_lesson", False) if state.get("context") else False
    visible_fields = state["context"].get("visible_fields") if state.get("context") else None
    system_instruction = get_rag_system_prompt(
        context_str=context_str,
        num_sources=num_sources,
        is_multi_lesson=is_multi_lesson,
        visible_fields=visible_fields,
    )

    t0 = time.time()
    client = gemini_client or genai.Client(api_key=settings.GEMINI_API_KEY)
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=settings.GEMINI_MODEL,
        contents=gemini_contents,
        config=types.GenerateContentConfig(
            temperature=0.2,
            max_output_tokens=1024,
            system_instruction=system_instruction,
        ),
    )
    gemini_latency_ms = round((time.time() - t0) * 1000, 2)

    token_usage = {}
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        token_usage = {
            "prompt_tokens": getattr(response.usage_metadata, "prompt_token_count", 0),
            "completion_tokens": getattr(response.usage_metadata, "candidates_token_count", 0),
            "total_tokens": getattr(response.usage_metadata, "total_token_count", 0),
        }

    if token_usage.get("total_tokens", 0) > settings.AGENT_MAX_CONTEXT_TOKENS * 0.85:
        logger.warning(
            "Token usage approaching budget limit",
            total_tokens=token_usage.get("total_tokens"),
            budget=settings.AGENT_MAX_CONTEXT_TOKENS,
        )

    return {
        "messages": [AIMessage(content=response.text)],
        "context": {
            "token_usage": token_usage,
            "gemini_latency_ms": gemini_latency_ms,
            "system_prompt_used": system_instruction,
        },
    }

