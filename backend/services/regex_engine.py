"""
Regex PII detection engine.
Stateless — takes text in, returns list[PIIFinding].
Runs independently of the LLM; merge happens upstream.
"""

import re
from typing import List

from backend.models.schemas import PIIFinding, PIIType


# ---------------------------------------------------------------------------
# Built-in patterns
# (pattern, PIIType, confidence)
# ---------------------------------------------------------------------------

_BUILTIN_PATTERNS: List[tuple] = [
    # SSN: exactly DDD-DD-DDDD (not DDD-DDD-DDDD which is a phone)
    (r"\b\d{3}-\d{2}-\d{4}\b", PIIType.SSN, "high"),

    # Email
    (r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", PIIType.EMAIL, "high"),

    # Phone — parentheses format: (555) 123-4567
    (r"\(\d{3}\)\s?\d{3}-\d{4}", PIIType.PHONE, "high"),

    # Phone — dash format: 555-123-4567  (three digits dash three digits dash four)
    # Use negative lookahead to avoid matching SSN (DDD-DD-DDDD)
    (r"\b\d{3}-\d{3}-\d{4}\b", PIIType.PHONE, "high"),

    # Phone — dot format: 555.123.4567
    (r"\b\d{3}\.\d{3}\.\d{4}\b", PIIType.PHONE, "high"),

    # Phone — international: +1XXXXXXXXXX
    (r"\+1\d{10}\b", PIIType.PHONE, "high"),

    # ZIP code: 5 digits, optionally +4.  Flagged as OTHER (context-ambiguous).
    # Use word boundaries and negative lookahead to avoid matching SSNs.
    (r"\b\d{5}(?:-\d{4})?\b(?!-\d)", PIIType.OTHER, "medium"),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_regex_engine(
    text: str,
    custom_patterns: List[dict] | None = None,
) -> List[PIIFinding]:
    """
    Run all built-in + custom regex patterns over *text*.

    Args:
        text: Raw text to scan.
        custom_patterns: Optional list of dicts with keys:
            ``name`` (str), ``pattern`` (str), ``pii_type`` (str).
            Invalid regex raises ``re.error``.

    Returns:
        Deduplicated list of PIIFinding with source="regex".
    """
    if not text or not text.strip():
        return []

    custom_patterns = custom_patterns or []

    # Validate custom patterns up-front (raises re.error on bad regex)
    compiled_custom: List[tuple] = []
    for cp in custom_patterns:
        compiled = re.compile(cp["pattern"])  # raises re.error if invalid
        compiled_custom.append((compiled, cp["pii_type"], "high"))

    seen: set[tuple] = set()  # (text, type) dedup key
    findings: List[PIIFinding] = []

    # Built-in patterns
    for pattern_str, pii_type, confidence in _BUILTIN_PATTERNS:
        for match in re.finditer(pattern_str, text):
            matched_text = match.group(0)
            key = (matched_text, pii_type)
            if key not in seen:
                seen.add(key)
                findings.append(PIIFinding(
                    text=matched_text,
                    type=pii_type,
                    confidence=confidence,
                    source="regex",
                ))

    # Custom patterns
    for compiled, pii_type_str, confidence in compiled_custom:
        try:
            pii_type_enum = PIIType(pii_type_str)
        except ValueError:
            pii_type_enum = PIIType.OTHER
        for match in compiled.finditer(text):
            matched_text = match.group(0)
            key = (matched_text, pii_type_enum)
            if key not in seen:
                seen.add(key)
                findings.append(PIIFinding(
                    text=matched_text,
                    type=pii_type_enum,
                    confidence=confidence,
                    source="regex",
                ))

    return findings
