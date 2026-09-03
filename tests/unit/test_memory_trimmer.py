# tests/unit/test_memory_trimmer.py
"""
Unit Tests — _trim_messages (Sliding Window Memory Trimmer)
============================================================
لا يحتاج Docker أو services أو Qdrant. Pure Python functions.
يمكن تشغيله في أي وقت: uv run pytest tests/unit/ -v
"""
import pytest
from langchain_core.messages import HumanMessage, AIMessage

from src.services.search_service import _trim_messages


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_conversation(n_pairs: int) -> list:
    """ينشئ محادثة وهمية من n_pairs أزواج (سؤال + جواب)."""
    msgs = []
    for i in range(n_pairs):
        msgs.append(HumanMessage(content=f"سؤال رقم {i + 1}"))
        msgs.append(AIMessage(content=f"إجابة رقم {i + 1}"))
    return msgs


# ─── Layer 1: Sliding Window (message count) ──────────────────────────────────

def test_trim_returns_all_when_under_limit():
    """لو الرسائل أقل من الحد → يرجع كلها بدون تقليم."""
    msgs = make_conversation(2)  # 4 رسائل
    result = _trim_messages(msgs, max_messages=6, max_tokens_approx=10_000)
    assert len(result) == 4


def test_trim_cuts_old_messages_when_over_limit():
    """لو الرسائل أكثر من الحد → يحتفظ بآخر max_messages فقط."""
    msgs = make_conversation(5)  # 10 رسائل
    result = _trim_messages(msgs, max_messages=6, max_tokens_approx=10_000)
    assert len(result) == 6


def test_trim_preserves_message_order():
    """الترتيب الزمني للرسائل يجب أن يُحفظ بعد التقليم."""
    msgs = make_conversation(4)  # 8 رسائل: سؤال1..4 + جواب1..4
    result = _trim_messages(msgs, max_messages=4, max_tokens_approx=10_000)
    # max_messages=4 → يُبقي آخر 4: سؤال3، جواب3، سؤال4، جواب4
    assert result[0].content == "سؤال رقم 3"
    assert result[-1].content == "إجابة رقم 4"


def test_trim_exact_limit_keeps_all():
    """عدد الرسائل يساوي الحد بالظبط → لا تقليم."""
    msgs = make_conversation(3)  # 6 رسائل
    result = _trim_messages(msgs, max_messages=6, max_tokens_approx=10_000)
    assert len(result) == 6


# ─── Layer 2: Token Budget Guard (character count) ────────────────────────────

def test_budget_guard_trims_when_chars_exceed_limit():
    """لو الحروف تتجاوز budget → يقص من الأقدم."""
    msgs = [
        AIMessage(content="x" * 1000),    # 1000 حرف قديم
        HumanMessage(content="y" * 1000), # 1000 حرف قديم
        AIMessage(content="z" * 1000),    # 1000 حرف قديم
        HumanMessage(content="سؤال جديد قصير"),  # صغيرة — يجب الحفاظ عليها
    ]
    # budget = 100 tokens * 4 chars = 400 chars — أقل من مجموع الكبيرة
    result = _trim_messages(msgs, max_messages=10, max_tokens_approx=100)
    assert result[-1].content == "سؤال جديد قصير"
    assert len(result) < 4  # تم التقليم من الأقدم


def test_budget_guard_keeps_all_when_within_budget():
    """لو كل الحروف ضمن البادجت → لا تقليم."""
    msgs = [
        AIMessage(content="قصيرة"),
        HumanMessage(content="قصيرة أيضاً"),
    ]
    result = _trim_messages(msgs, max_messages=10, max_tokens_approx=10_000)
    assert len(result) == 2


# ─── Edge Cases ───────────────────────────────────────────────────────────────

def test_trim_empty_list_returns_empty():
    """قائمة فارغة → يرجع قائمة فارغة بدون خطأ."""
    result = _trim_messages([], max_messages=6, max_tokens_approx=3000)
    assert result == []


def test_trim_always_keeps_last_message_even_if_huge():
    """
    حتى لو الرسالة الأخيرة ضخمة جداً وتتجاوز البادجت →
    لا يُحذف السؤال الأخير أبداً (الطالب يجب أن يحصل على إجابة).
    """
    huge_last_msg = HumanMessage(content="س" * 50_000)  # 50k حرف!
    msgs = [
        AIMessage(content="إجابة قديمة صغيرة"),
        huge_last_msg,
    ]
    result = _trim_messages(msgs, max_messages=6, max_tokens_approx=10)
    assert result[-1] == huge_last_msg
    assert len(result) == 1  # حذف القديمة، حافظ على الأخيرة


def test_trim_single_message_never_deleted():
    """لو كانت رسالة واحدة فقط → لا تُحذف أبداً بغض النظر عن الحجم."""
    single_msg = HumanMessage(content="رسالة وحيدة")
    result = _trim_messages([single_msg], max_messages=6, max_tokens_approx=1)
    assert result == [single_msg]
