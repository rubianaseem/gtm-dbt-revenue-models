"""Treat CRM free text (deal descriptions, contact notes, any string in a failing row) as data, never as instructions.

Adapted from my revenue-signal-router. screen() flags instruction-like text. A flagged value is
quarantined: it never reaches a model prompt, the report or the plan, and the reviewer sees
only the record id and the pattern ids that matched.
"""
from __future__ import annotations

import re
import unicodedata

PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier|your)\s+(instructions|rules|prompts?|guidelines)",
    r"disregard\s+(the\s+|all\s+|any\s+|your\s+)?(previous|prior|above|rules|instructions|scoring|routing)",
    r"\byou\s+are\s+now\b",
    r"^\s*(system|assistant|developer)\s*:",
    r"\b(mark|treat|classify|label|flag)\s+(this|it|the\s+\w+|all\s+\w+)?\s*(account\s+)?(as\s+)?(hot|high[\s-]?priority|priority\s+high|urgent|safe|approved)\b",
    r"\b(auto[\s-]?approve|skip\s+(the\s+)?(approval|review)s?|bypass\s+(the\s+)?(approval|review|rules))\b",
    r"\b(assign|route|reassign)\s+(this|it|the\s+account|all\s+\w+)\s+to\s+\w+",
    r"\bset\s+(the\s+)?(score|priority|owner|status|amount)\s*(to|=)",
    r"\b(mark|treat)\s+(every|all|each)\s+(dbt\s+)?(tests?|checks?)\s+as\s+(passing|passed|green)",
    r"\b(print|reveal|show)\s+(the\s+|your\s+)?(system\s+prompt|instructions|api\s+key)",
    r"\bapprove\s+(this|the|all)\s+(plan|changes?|deal)",
    r"<\|?(im_start|system|endoftext)\|?>",
    r"\bnew\s+instructions?\s*:",
    r"\boverride\s+(the\s+)?(rules|policy|routing|scoring|safety)\b",
]
_RX = [re.compile(p, re.I | re.M) for p in PATTERNS]
_INVISIBLE = {"\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"}


def clean_invisible(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch not in _INVISIBLE)


def normalise(text: str) -> str:
    return unicodedata.normalize("NFKC", clean_invisible(text or ""))


def screen(text: str) -> list[str]:
    """Return the ids of matched injection patterns (empty list = clean)."""
    if not text:
        return []
    t = normalise(text)
    return [f"P{i}" for i, rx in enumerate(_RX) if rx.search(t)]
