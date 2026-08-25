import asyncio
import structlog
from langgraph.graph import StateGraph, START, END
from google import genai
from google.genai import types
from langchain_core.messages import AIMessage

from src.core.config import settings
from src.agents.base_agent import AgentState, agent_service
from src.services.event_logger import event_logger_service

logger = structlog.get_logger()

# Lazy-initialized compiled graph — built once at first call (not at import time)
_summarizer_agent_compiled = None

def generate_summary_prompt(context: dict) -> str:
    transcript = context.get("transcript", "")
    return f"""
    Summarize the following video transcript into key educational bullet points.
    Make it concise and easy to read.
    
    Transcript:
    {transcript}
    """

async def generate_summary_node(state: AgentState) -> dict:
    context = state.get("context", {}) or {}
    prompt = generate_summary_prompt(context)

    # Client instantiated here (not at module level) to ensure settings are loaded
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _call_gemini():
        return client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3
            )
        )
    
    try:
        # Task D requirement: Use asyncio.to_thread for LLM blocking calls
        response = await asyncio.to_thread(_call_gemini)
        summary = response.text
        
        # Fire-and-forget: log event in background, don't block the API response
        session_id = context.get("session_id", "unknown_session")
        asyncio.create_task(event_logger_service.log_event(
            session_id=session_id,
            agent_name="SummarizerAgent",
            event_type="SUMMARY_GENERATED",
            payload={"token_usage": response.usage_metadata.model_dump() if response.usage_metadata else {}}
        ))
        
        return {"messages": [AIMessage(content=summary)]}
        
    except Exception as e:
        logger.error("Gemini summarization failed", error=str(e))
        return {"messages": [AIMessage(content="Error generating summary.")]}

def get_summarizer_agent():
    """
    Builds and compiles the Summarizer Agent LangGraph.
    Lazy-initialized: compiled once at first call, then cached for all subsequent requests.
    """
    global _summarizer_agent_compiled
    if _summarizer_agent_compiled is None:
        workflow = StateGraph(AgentState)
        workflow.add_node("generate_summary", generate_summary_node)
        workflow.add_edge(START, "generate_summary")
        workflow.add_edge("generate_summary", END)
        _summarizer_agent_compiled = workflow.compile(checkpointer=agent_service.checkpointer)
    return _summarizer_agent_compiled
