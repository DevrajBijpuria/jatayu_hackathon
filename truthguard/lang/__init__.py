"""Shared language helpers for number normalisation, grounding checks, and language detection.

Used by Phases 1-4. See AGENTS.md section 6 (Phase 1, tasks 5 and 12).
"""
from __future__ import annotations

import re

_DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

_HINDI_WORDS: dict[str, float] = {
    "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5,
    "छह": 6, "छः": 6, "सात": 7, "आठ": 8, "नौ": 9, "दस": 10,
    "ग्यारह": 11, "बारह": 12, "तेरह": 13, "चौदह": 14, "पंद्रह": 15,
    "सोलह": 16, "सत्रह": 17, "अठारह": 18, "उन्नीस": 19,
    "बीस": 20, "तीस": 30, "चालीस": 40, "पचास": 50,
    "साठ": 60, "सत्तर": 70, "अस्सी": 80, "नब्बे": 90,
    "सौ": 100, "हज़ार": 1_000, "हजार": 1_000,
    "लाख": 100_000, "करोड़": 10_000_000, "करोड": 10_000_000,
}

_NUM_PATTERNS = [
    re.compile(
        r"(?:[₹$€£]|Rs\.?\s*|INR\s*|रु\.?\s*|रुपये?\s*)?"
        r"\d{1,3}(?:,\d{2,3})+"
        r"(?:\.\d+)?",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:[₹$€£]|Rs\.?\s*|INR\s*|रु\.?\s*|रुपये?\s*)?"
        r"\d+(?:\.\d+)?"
        r"(?:\s*(?:lakh|crore|k))?",
        re.IGNORECASE,
    ),
]


def normalise_number(text: str) -> float | None:
    text = text.translate(_DEVA_DIGITS).strip()
    text = re.sub(r"[₹$€£]|Rs\.?\s*|INR\s*|रु\.?\s*|रुपये?\s*", "", text, flags=re.IGNORECASE).strip()
    text_nc = text.replace(",", "")
    try:
        return float(text_nc)
    except ValueError:
        pass
    m = re.fullmatch(r"([\d.]+)\s*[kK]", text_nc)
    if m:
        return float(m.group(1)) * 1_000
    m = re.fullmatch(r"([\d.]+)\s*lakh", text_nc, re.IGNORECASE)
    if m:
        return float(m.group(1)) * 100_000
    m = re.fullmatch(r"([\d.]+)\s*crore", text_nc, re.IGNORECASE)
    if m:
        return float(m.group(1)) * 10_000_000
    return _parse_hindi_words(text)


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
            current = current * v if current else v
            if v >= 100_000:
                total += current
                current = 0.0
        else:
            current += v
    result = total + current
    return result if matched else None


def numbers_in_text(text: str) -> list[float]:
    """Extract every distinct numeric value present in *text*, normalised."""
    text_norm = text.translate(_DEVA_DIGITS)
    found: set[float] = set()
    for pat in _NUM_PATTERNS:
        for m in pat.finditer(text_norm):
            v = normalise_number(m.group(0))
            if v is not None and v > 0:
                found.add(v)
    tokens = text.split()
    for size in (3, 2, 1):
        for start in range(len(tokens) - size + 1):
            phrase = " ".join(tokens[start : start + size])
            v = _parse_hindi_words(phrase)
            if v is not None and v > 0:
                found.add(v)
    return list(found)


def grounding_check(value_num: float, source_text: str) -> bool:
    """Return True if *value_num* appears in *source_text* in any normalised form."""
    nums = numbers_in_text(source_text)
    return any(abs(n - value_num) < 0.01 for n in nums)


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
