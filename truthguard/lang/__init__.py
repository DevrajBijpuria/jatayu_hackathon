"""Shared language helpers — number normaliser, language detection.

Used by Phases 1–4. See AGENTS.md §6 (Phase 1, tasks 12 and 5).
"""
from __future__ import annotations

import re

# Devanagari digit map
_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Hindi number words (extend as needed)
_HINDI_WORDS: dict[str, float] = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5,
    "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "बीस": 20, "तीस": 30, "चालीस": 40, "पचास": 50,
    "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
    "सौ": 100, "हज़ार": 1_000, "हजार": 1_000,
    "लाख": 100_000, "करोड़": 10_000_000,
}


def normalise_number(text: str) -> float | None:
    """Return the numeric value from a string, or None if it cannot be parsed.

    Handles: plain integers, comma-grouped (Indian and Western), currency
    prefixes (₹, Rs., $), Devanagari digits, Hindi number words, lakh/crore.
    """
    # Translate Devanagari digits
    text = text.translate(_DEVA_DIGITS).strip()

    # Strip currency symbols
    text = re.sub(r"[₹$€£]|Rs\.?\s*|INR\s*", "", text, flags=re.IGNORECASE).strip()

    # Remove commas used as thousand separators (handles Indian lakhs too)
    text_no_comma = text.replace(",", "")

    # Plain number
    try:
        return float(text_no_comma)
    except ValueError:
        pass

    # "k" / "K" suffix
    m = re.fullmatch(r"([\d.]+)\s*[kK]", text_no_comma)
    if m:
        return float(m.group(1)) * 1_000

    # Hindi number words: try to parse compound like "तीन हज़ार"
    value = _parse_hindi_words(text)
    if value is not None:
        return value

    return None


def _parse_hindi_words(text: str) -> float | None:
    tokens = text.lower().split()
    total = 0.0
    current = 0.0
    matched = False
    for token in tokens:
        v = _HINDI_WORDS.get(token)
        if v is None:
            continue
        matched = True
        if v >= 100:
            # multiplier
            current = current * v if current else v
            if v >= 100_000:
                total += current
                current = 0.0
        else:
            current += v
    result = total + current
    return result if matched else None


def detect_language(text: str) -> str:
    """Return 'en', 'hi', or 'mixed' based on script heuristics."""
    devanagari = len(re.findall(r"[ऀ-ॿ]", text))
    latin = len(re.findall(r"[a-zA-Z]", text))
    total = devanagari + latin
    if total == 0:
        return "en"
    ratio = devanagari / total
    if ratio > 0.8:
        return "hi"
    if ratio < 0.2:
        return "en"
    return "mixed"
