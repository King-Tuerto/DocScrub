"""
Replacer — applies a MappingTable to text (and structured documents).

Longest-match-first: avoids "John" clobbering "John Smith".
Returns a ReplacementResult with the anonymized text and positions list.
reverse_replacements: swaps placeholders back to originals (100% fidelity).
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from backend.services.mapper import MappingTable


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ReplacementPosition:
    start: int
    end: int
    pii_type: str
    placeholder: str


@dataclass
class ReplacementResult:
    text: str
    positions: List[ReplacementPosition] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core replacement
# ---------------------------------------------------------------------------

def apply_replacements(text: str, mapping_table: MappingTable) -> ReplacementResult:
    """
    Replace all PII occurrences in text using the mapping table.

    Uses longest-match-first so overlapping spans are handled correctly.
    Returns the anonymised text plus a list of replacement positions
    (positions refer to the *output* string).
    """
    if not mapping_table.entries:
        return ReplacementResult(text=text, positions=[])

    # Sort by length descending so longest match wins
    sorted_entries = sorted(mapping_table.entries, key=lambda e: len(e.original), reverse=True)

    # Build a single alternation regex from all originals.
    # Word-boundary anchors (\b) are added when the original text starts or
    # ends with a word character so that a mapping for "S" never matches "S"
    # inside "Situation", "Suspension", etc.  Patterns that start/end with
    # non-word chars (phone numbers beginning with "(" for example) get no
    # boundary on that side — the exact-character match already prevents false
    # positives there.
    def _bounded(original: str) -> str:
        escaped = re.escape(original)
        pre = r'\b' if original and re.match(r'\w', original[0]) else ''
        suf = r'\b' if original and re.match(r'\w', original[-1]) else ''
        return pre + escaped + suf

    patterns = [_bounded(e.original) for e in sorted_entries]
    combined = re.compile("|".join(patterns))

    # Build lookup: original → entry
    lookup = {e.original: e for e in sorted_entries}

    result_parts: List[str] = []
    positions: List[ReplacementPosition] = []
    cursor = 0
    offset = 0  # cumulative difference in length so far

    for m in combined.finditer(text):
        matched_text = m.group(0)
        entry = lookup[matched_text]

        # Text before this match
        result_parts.append(text[cursor:m.start()])

        # Position in output string
        out_start = m.start() + offset
        out_end = out_start + len(entry.placeholder)
        positions.append(ReplacementPosition(
            start=out_start,
            end=out_end,
            pii_type=entry.pii_type,
            placeholder=entry.placeholder,
        ))

        result_parts.append(entry.placeholder)
        offset += len(entry.placeholder) - len(matched_text)
        cursor = m.end()

    result_parts.append(text[cursor:])
    return ReplacementResult(text="".join(result_parts), positions=positions)


# ---------------------------------------------------------------------------
# Structured document replacement
# ---------------------------------------------------------------------------

def apply_replacements_to_document(doc: Dict[str, Any], mapping_table: MappingTable) -> Dict[str, Any]:
    """
    Apply replacements to a document dict with body_text, header_text,
    footer_text, and table_cells fields.  Returns a new dict.
    """
    result = dict(doc)

    result["body_text"] = apply_replacements(doc.get("body_text", ""), mapping_table).text
    result["header_text"] = apply_replacements(doc.get("header_text", ""), mapping_table).text
    result["footer_text"] = apply_replacements(doc.get("footer_text", ""), mapping_table).text

    table_cells = doc.get("table_cells")
    if table_cells:
        result["table_cells"] = [
            [apply_replacements(cell, mapping_table).text for cell in row]
            for row in table_cells
        ]

    return result


# ---------------------------------------------------------------------------
# Reverse (re-identification)
# ---------------------------------------------------------------------------

def reverse_replacements(text: str, mapping_table: MappingTable) -> str:
    """
    Swap placeholders back to originals.

    Raises ValueError if a placeholder in the text is not in the mapping.
    """
    # Build placeholder → original lookup
    ph_to_orig = {e.placeholder: e.original for e in mapping_table.entries}

    # Find all placeholders in text (e.g. [PERSON_1], [EMAIL_3])
    placeholder_pattern = re.compile(r'\[[A-Z]+_\d+\]')

    result_parts: List[str] = []
    cursor = 0

    for m in placeholder_pattern.finditer(text):
        ph = m.group(0)
        if ph not in ph_to_orig:
            raise ValueError(
                f"Placeholder {ph!r} not found in mapping table — "
                "cannot re-identify without the original mapping."
            )
        result_parts.append(text[cursor:m.start()])
        result_parts.append(ph_to_orig[ph])
        cursor = m.end()

    result_parts.append(text[cursor:])
    return "".join(result_parts)
