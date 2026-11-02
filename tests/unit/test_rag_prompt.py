import pytest
from src.core.prompts import get_rag_system_prompt, RAG_SYSTEM_PROMPT


def test_rag_system_prompt_includes_procedural_guidance():
    """Verify RAG prompt directs Gemini to give educational guidance for how-to questions."""
    prompt = get_rag_system_prompt("Lecture context text", num_sources=2)
    assert "Procedural & How-To Guidance" in prompt
    assert "ERP Form Filling Action Context" not in prompt
    assert "[1] to [2]" in prompt
    assert "[3]" in prompt  # Forbidden citation index


def test_rag_system_prompt_backward_compatibility():
    """Verify get_rag_system_prompt accepts legacy keyword arguments cleanly."""
    prompt = get_rag_system_prompt(
        context_str="Sample context",
        num_sources=1,
        is_multi_lesson=True,
        visible_fields=["Customer", "Date"],
        extracted_form_fields=None,
    )
    assert "Cross-Module Multi-Lesson Synthesis" in prompt
    assert "Provided Video Lesson Context" in prompt
