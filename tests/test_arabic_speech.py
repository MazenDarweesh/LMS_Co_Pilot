import pytest
from src.utils.arabic_speech_utils import (
    normalize_arabic_text_leaderboard,
    calculate_wer_cer,
    tafqit_arabic
)

def test_normalize_arabic_text_leaderboard():
    # Test stripping diacritics
    text_diacritics = "الْحَمْدُ لِلَّهِ رَبِّ الْعَالَمِينَ"
    assert normalize_arabic_text_leaderboard(text_diacritics) == "الحمد لله رب العالمين"
    
    # Test stripping punctuation and collapsing space
    text_punctuation = "مرحبا، كيف حالك؟ أنا بخير والحمد لله!."
    assert normalize_arabic_text_leaderboard(text_punctuation) == "مرحبا كيف حالك انا بخير والحمد لله"
    
    # Test Eastern to Western numerals conversion
    text_numerals = "التعداد في سنة ٢٠٢٦ وصل إلى ٥٠ مليون نسمة"
    assert normalize_arabic_text_leaderboard(text_numerals) == "التعداد في سنه 2026 وصل الي 50 مليون نسمه"
    
    # Test Hamza and Alif/Ya/Taa-Marbuta normalization
    text_orthography = "أكرمتُ الفتاةَ التي رأيتُها في المدرسةِ"
    assert normalize_arabic_text_leaderboard(text_orthography) == "اكرمت الفتاه التي رايتها في المدرسه"
    
    # Empty inputs
    assert normalize_arabic_text_leaderboard("") == ""
    assert normalize_arabic_text_leaderboard(None) == ""


def test_calculate_wer_cer():
    ref = "ذهب الطالب إلى المدرسة في الصباح الباكر"
    hyp = "ذهب طالب الي المدرسه في الصباح الباكر"
    
    # With normalization (should ignore hamza difference 'إلى' vs 'الي', and taa-marbuta 'المدرسة' vs 'المدرسه')
    metrics = calculate_wer_cer(ref, hyp, normalize=True)
    
    # The normalized versions will be:
    # Ref: "ذهب الطالب الي المدرسه في الصباح الباكر"
    # Hyp: "ذهب طالب الي المدرسه في الصباح الباكر"
    # Difference: "الطالب" vs "طالب" -> 1 substitution / insertion / deletion
    assert metrics["word_distance"] == 1
    assert metrics["reference_word_count"] == 7
    assert metrics["wer"] == round(1 / 7, 4)
    
    # Without normalization, it should count 'إلى' vs 'الي' and 'المدرسة' vs 'المدرسه' as errors too
    metrics_no_norm = calculate_wer_cer(ref, hyp, normalize=False)
    assert metrics_no_norm["word_distance"] == 3  # (الطالب vs طالب), (إلى vs الي), (المدرسة vs المدرسه)
    assert metrics_no_norm["wer"] == round(3 / 7, 4)


def test_tafqit_arabic():
    assert tafqit_arabic(0) == "صفر"
    assert tafqit_arabic(5) == "خمسة"
    assert tafqit_arabic(10) == "عشرة"
    assert tafqit_arabic(11) == "أحد عشر"
    assert tafqit_arabic(12) == "اثنا عشر"
    assert tafqit_arabic(19) == "تسعة عشر"
    assert tafqit_arabic(20) == "عشرون"
    assert tafqit_arabic(23) == "ثلاثة وعشرون"
    assert tafqit_arabic(99) == "تسعة وتسعون"
    assert tafqit_arabic(100) == "مئة"
    assert tafqit_arabic(115) == "مئة وخمسة عشر"
    assert tafqit_arabic(1000) == "ألف"
    assert tafqit_arabic(2000) == "ألفان"
    assert tafqit_arabic(3500) == "ثلاثة آلاف وخمسمئة"
    assert tafqit_arabic(1000000) == "مليون"
    assert tafqit_arabic(2000000) == "مليونان"
    assert tafqit_arabic(15000000) == "خمسة عشر مليون"
    assert tafqit_arabic(1000000000) == "مليار"
    assert tafqit_arabic(-45) == "سالب خمسة وأربعون"
