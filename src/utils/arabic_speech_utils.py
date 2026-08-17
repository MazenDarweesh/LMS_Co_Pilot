import re

# Arabic diacritics regex pattern
ARABIC_DIACRITICS = re.compile(r"[\u064b-\u0652\u0640]")

# Arabic and English punctuation pattern
PUNCTUATION = re.compile(
    r"[؟،؛!.,;:?۔\-\_()\[\]\{\}\"\'\/\\|+=*&%$#@\^~<>]|[\u201c\u201d\u2018\u2019\u2022]"
)

# Map Eastern Arabic numerals to Western numerals
EASTERN_TO_WESTERN_NUMERALS = {
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"
}

def normalize_arabic_text_leaderboard(text: str) -> str:
    """
    Normalizes Arabic text according to the de-facto recipe of the
    Open Universal Arabic ASR Leaderboard:
    1. Strip diacritics (tashkeel & tatweel).
    2. Strip punctuation.
    3. Normalize Hamza variants (أ, إ, آ, ٱ) to bare Alif (ا).
    4. Normalize Alif Maqsura (ى) to Ya (ي) and Taa Marbuta (ة) to Haa (ه).
    5. Unify numerals (convert Eastern Arabic digits to Western digits).
    6. Collapse whitespace.
    """
    if not text:
        return ""
    
    # 1. Strip diacritics
    text = ARABIC_DIACRITICS.sub("", text)
    
    # 2. Strip punctuation
    text = PUNCTUATION.sub(" ", text)
    
    # 3. Unify numerals (Eastern to Western)
    for eastern, western in EASTERN_TO_WESTERN_NUMERALS.items():
        text = text.replace(eastern, western)
        
    # 4. Normalize Hamza and other orthographic variations
    # Replace Alif with Hamza above/below, Alif Madda, Alif Wasla with plain Alif
    text = re.sub(r"[أإآٱ]", "ا", text)
    
    # Unify Alif Maqsura (ى) to Ya (ي)
    text = re.sub(r"ى", "ي", text)
    
    # Unify Taa Marbuta (ة) to Haa (ه)
    text = re.sub(r"ة", "ه", text)
    
    # 5. Clean up whitespaces
    text = re.sub(r"\s+", " ", text).strip()
    
    return text

def levenshtein_distance(ref: list, hyp: list) -> int:
    """
    Calculates the minimum edit distance (Levenshtein distance) between two sequences.
    Used for both word-level (WER) and character-level (CER) computations.
    """
    n = len(ref)
    m = len(hyp)
    if n == 0:
        return m
    if m == 0:
        return n
    
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
        
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = min(
                    dp[i - 1][j] + 1,      # Deletion
                    dp[i][j - 1] + 1,      # Insertion
                    dp[i - 1][j - 1] + 1   # Substitution
                )
    return dp[n][m]

def calculate_wer_cer(reference: str, hypothesis: str, normalize: bool = True) -> dict:
    """
    Calculates Word Error Rate (WER) and Character Error Rate (CER) between reference and hypothesis.
    Optionally applies Open Universal ASR Leaderboard normalization recipe before evaluation.
    """
    if normalize:
        ref_clean = normalize_arabic_text_leaderboard(reference)
        hyp_clean = normalize_arabic_text_leaderboard(hypothesis)
    else:
        ref_clean = re.sub(r"\s+", " ", reference).strip()
        hyp_clean = re.sub(r"\s+", " ", hypothesis).strip()
        
    ref_words = ref_clean.split()
    hyp_words = hyp_clean.split()
    
    # Calculate word distance
    word_distance = levenshtein_distance(ref_words, hyp_words)
    wer = word_distance / len(ref_words) if ref_words else (0.0 if not hyp_words else 1.0)
    
    # Calculate character distance
    ref_chars = list(ref_clean.replace(" ", ""))
    hyp_chars = list(hyp_clean.replace(" ", ""))
    
    char_distance = levenshtein_distance(ref_chars, hyp_chars)
    cer = char_distance / len(ref_chars) if ref_chars else (0.0 if not hyp_chars else 1.0)
    
    return {
        "reference_normalized": ref_clean,
        "hypothesis_normalized": hyp_clean,
        "word_distance": word_distance,
        "char_distance": char_distance,
        "reference_word_count": len(ref_words),
        "reference_char_count": len(ref_chars),
        "wer": round(wer, 4),
        "cer": round(cer, 4)
    }

def tafqit_arabic(num: int) -> str:
    """
    Converts integer numbers to their Arabic word equivalents (Tafqit).
    Supports numbers from 0 up to 999,999,999,999 (999 Billion).
    Useful for Challenge 13.5 (digit rendering & TTS normalization).
    """
    if num < 0:
        return "سالب " + tafqit_arabic(abs(num))
    if num == 0:
        return "صفر"
        
    units = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
    tens = ["", "عشرة", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
    hundreds = ["", "مئة", "مئتان", "ثلاثمئة", "أربعمئة", "خمسمئة", "ستمئة", "سبعمئة", "ثمانمئة", "تسعمئة"]
    
    def parse_under_100(val: int) -> str:
        if val == 0:
            return ""
        if val < 10:
            return units[val]
        if val == 10:
            return "عشرة"
        if val == 11:
            return "أحد عشر"
        if val == 12:
            return "اثنا عشر"
        if val < 20:
            return f"{units[val - 10]} عشر"
            
        unit_part = val % 10
        ten_part = val // 10
        if unit_part == 0:
            return tens[ten_part]
        else:
            # e.g., 23 -> "ثلاثة وعشرون"
            return f"{units[unit_part]} و{tens[ten_part]}"
            
    def parse_under_1000(val: int) -> str:
        if val == 0:
            return ""
        hundred_part = val // 100
        rem = val % 100
        
        hundred_str = hundreds[hundred_part]
        rem_str = parse_under_100(rem)
        
        if hundred_str and rem_str:
            return f"{hundred_str} و{rem_str}"
        return hundred_str or rem_str

    chunks = []
    
    # Billions
    billions = num // 1000000000
    num %= 1000000000
    if billions > 0:
        if billions == 1:
            chunks.append("مليار")
        elif billions == 2:
            chunks.append("ملياران")
        elif 3 <= billions <= 10:
            chunks.append(f"{parse_under_1000(billions)} مليارات")
        else:
            chunks.append(f"{parse_under_1000(billions)} مليار")
            
    # Millions
    millions = num // 1000000
    num %= 1000000
    if millions > 0:
        if millions == 1:
            chunks.append("مليون")
        elif millions == 2:
            chunks.append("مليونان")
        elif 3 <= millions <= 10:
            chunks.append(f"{parse_under_1000(millions)} ملايين")
        else:
            chunks.append(f"{parse_under_1000(millions)} مليون")
            
    # Thousands
    thousands = num // 1000
    num %= 1000
    if thousands > 0:
        if thousands == 1:
            chunks.append("ألف")
        elif thousands == 2:
            chunks.append("ألفان")
        elif 3 <= thousands <= 10:
            chunks.append(f"{parse_under_1000(thousands)} آلاف")
        else:
            chunks.append(f"{parse_under_1000(thousands)} ألف")
            
    # Units, Tens, Hundreds
    if num > 0:
        chunks.append(parse_under_1000(num))
        
    return " و".join(chunks)
