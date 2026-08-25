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
_quiz_agent_compiled = None

def generate_quiz_prompt(context: dict) -> str:
    documents = context.get("documents", [])
    docs_text = "\n".join([d.get("content", "") for d in documents])
    
    return f"""
    Based on the following educational context, generate a 5-question multiple choice quiz.
    Format the output as a clean JSON array of objects, where each object has:
    - "question": string
    - "options": list of 4 strings
    - "correct_answer": string (must exactly match one of the options)
    
    Context:
    {docs_text}
    """

async def generate_quiz_node(state: AgentState) -> dict:
    context = state.get("context", {}) or {}
    prompt = generate_quiz_prompt(context)
    
    # Client instantiated here (not at module level) to ensure settings are loaded
    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    def _call_gemini():
        return client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
    
    try:
        # Task D requirement: Use asyncio.to_thread for LLM blocking calls
        response = await asyncio.to_thread(_call_gemini)
        quiz_json = response.text
        
        # Fire-and-forget: log event in background, don't block the API response
        session_id = context.get("session_id", "unknown_session")
        asyncio.create_task(event_logger_service.log_event(
            session_id=session_id,
            agent_name="QuizGeneratorAgent",
            event_type="QUIZ_GENERATED",
            payload={"token_usage": response.usage_metadata.model_dump() if response.usage_metadata else {}}
        ))
        
        return {"messages": [AIMessage(content=quiz_json)]}
        
    except Exception as e:
        logger.error("Gemini quiz generation failed", error=str(e))
        return {"messages": [AIMessage(content='{"error": "Failed to generate quiz"}')]}

def get_quiz_agent():
    """
    Builds and compiles the Quiz Agent LangGraph.
    Lazy-initialized: compiled once at first call, then cached for all subsequent requests.
    """
    global _quiz_agent_compiled
    if _quiz_agent_compiled is None:
        workflow = StateGraph(AgentState)
        workflow.add_node("generate_quiz", generate_quiz_node)
        workflow.add_edge(START, "generate_quiz")
        workflow.add_edge("generate_quiz", END)
        _quiz_agent_compiled = workflow.compile(checkpointer=agent_service.checkpointer)
    return _quiz_agent_compiled
