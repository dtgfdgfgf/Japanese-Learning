"""Japanese text normalizer for comparison and deduplication.

T020: Create Japanese text normalizer in src/lib/normalizer.py
DoD: normalize() 支援全半形轉換、假名正規化；單元測試涵蓋 10+ 案例
"""

import re
import unicodedata

import jaconv


def normalize_for_key(text: str) -> str:
    """Normalize text for use as deduplication key.

    Applies aggressive normalization for consistent keys:
    - Lowercase
    - Full-width to half-width (except kana)
    - Remove whitespace
    - NFKC normalization

    Args:
        text: Input text

    Returns:
        Normalized text for key generation
    """
    if not text:
        return ""

    # NFKC normalization (handles most full-width -> half-width)
    normalized = unicodedata.normalize("NFKC", text)

    # Lowercase
    normalized = normalized.lower()

    # Remove all whitespace
    normalized = re.sub(r"\s+", "", normalized)

    return normalized


def normalize_for_compare(text: str) -> str:
    """Normalize text for answer comparison.

    Applies normalization suitable for grading:
    - Full-width to half-width (except kana)
    - Katakana to Hiragana
    - Lowercase
    - Trim whitespace

    Args:
        text: Input text (user answer)

    Returns:
        Normalized text for comparison
    """
    if not text:
        return ""

    # Trim whitespace
    normalized = text.strip()

    # NFKC normalization
    normalized = unicodedata.normalize("NFKC", normalized)

    # Katakana to Hiragana for consistent comparison（僅對含日文假名的文字執行）
    if any(0x30A0 <= ord(c) <= 0x30FF for c in normalized):
        normalized = jaconv.kata2hira(normalized)

    # Lowercase (for romaji and alphabets)
    normalized = normalized.lower()

    return normalized


def kanji_to_reading_variants(surface: str, reading: str) -> list[str]:
    """Generate acceptable answer variants for a vocab item.

    Args:
        surface: Kanji/dictionary form (e.g., "考える")
        reading: Hiragana reading (e.g., "かんがえる")

    Returns:
        List of acceptable answer forms
    """
    variants = set()

    # Original forms
    variants.add(surface)
    variants.add(reading)

    # Katakana version of reading
    katakana_reading = jaconv.hira2kata(reading)
    variants.add(katakana_reading)

    # Normalized versions
    variants.add(normalize_for_compare(surface))
    variants.add(normalize_for_compare(reading))

    return list(variants)


def is_correct_answer(
    user_answer: str,
    expected_answers: str | list[str],
    strict: bool = False,
) -> bool:
    """Check if user answer matches any expected answer.

    Args:
        user_answer: User's response
        expected_answers: Single expected answer or list of acceptable answers
        strict: If True, require exact match; if False, use normalized comparison

    Returns:
        True if answer matches, False otherwise
    """
    # Normalize input to list
    if isinstance(expected_answers, str):
        expected_answers = [expected_answers]
    
    # Handle empty input edge cases
    if not expected_answers:
        return False
    
    # Empty user answer only matches empty expected
    if not user_answer:
        return any(not exp for exp in expected_answers)

    if strict:
        return user_answer in expected_answers

    # Normalize user answer
    normalized_user = normalize_for_compare(user_answer)

    # Check against normalized expected answers
    for expected in expected_answers:
        if normalize_for_compare(expected) == normalized_user:
            return True

    return False


def detect_language(text: str) -> str:
    """Detect primary language of text.

    Simple heuristic based on character ranges.

    Args:
        text: Input text

    Returns:
        "ja" for Japanese, "en" for English, "mixed" for mixed content, "unknown" otherwise
    """
    if not text:
        return "unknown"

    # 計算各類字元數
    hiragana_count = 0
    katakana_count = 0
    kanji_count = 0
    ascii_alpha_count = 0
    other_count = 0

    for char in text:
        code = ord(char)
        if 0x3040 <= code <= 0x309F:  # Hiragana
            hiragana_count += 1
        elif 0x30A0 <= code <= 0x30FF:  # Katakana
            katakana_count += 1
        elif 0x4E00 <= code <= 0x9FFF:  # CJK Unified Ideographs (Kanji)
            kanji_count += 1
        elif char.isascii() and char.isalpha():  # ASCII 英文字母
            ascii_alpha_count += 1
        elif not char.isspace():
            other_count += 1

    japanese_count = hiragana_count + katakana_count + kanji_count
    total_count = japanese_count + ascii_alpha_count + other_count

    if total_count == 0:
        return "unknown"

    japanese_ratio = japanese_count / total_count
    english_ratio = ascii_alpha_count / total_count

    if japanese_ratio >= 0.5:
        return "ja"
    elif english_ratio >= 0.5:
        return "en"
    elif japanese_ratio > 0 and english_ratio > 0:
        return "mixed"
    elif japanese_ratio > 0:
        return "mixed"
    elif english_ratio > 0:
        return "en"
    else:
        return "unknown"


def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    """Truncate text to maximum length with suffix.

    Args:
        text: Input text
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncating

    Returns:
        Truncated text
    """
    if not text or len(text) <= max_length:
        return text

    return text[: max_length - len(suffix)] + suffix


def extract_vocab_key(surface: str) -> str:
    """Generate vocab deduplication key.

    Args:
        surface: Vocab surface form

    Returns:
        Key in format "vocab:{normalized_surface}"
    """
    return f"vocab:{normalize_for_key(surface)}"


def extract_grammar_key(pattern: str) -> str:
    """Generate grammar deduplication key.

    Args:
        pattern: Grammar pattern

    Returns:
        Key in format "grammar:{normalized_pattern}"
    """
    # Normalize pattern notation (〜 vs ~ vs ～)
    normalized = pattern.replace("~", "〜").replace("～", "〜")
    return f"grammar:{normalize_for_key(normalized)}"
