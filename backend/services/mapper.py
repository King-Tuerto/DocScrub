"""
Mapper — merges LLM + regex findings, deduplicates, assigns typed sequential
placeholders.  Designed to be deterministic: same input always produces the
same mapping.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MappingEntry:
    original: str
    placeholder: str
    pii_type: str
    source: Optional[str] = None


@dataclass
class MappingTable:
    entries: List[MappingEntry] = field(default_factory=list)

    def get_placeholder(self, original: str) -> Optional[str]:
        for e in self.entries:
            if e.original == original:
                return e.placeholder
        return None


# ---------------------------------------------------------------------------
# Build mapping
# ---------------------------------------------------------------------------

def build_mapping(findings) -> MappingTable:
    """
    Merge a list of PIIFinding objects into a MappingTable.

    Deduplication: same (text, type) → one entry.
    If a text appears in findings from both sources, source is set to "both".
    Placeholders: [TYPE_N], where N is a per-type counter starting at 1.
    Input order determines counter assignment; ties broken by text value.
    """
    # Belt-and-suspenders: skip single-character findings.  They corrupt every
    # word in the document that contains the letter (substring match on "S"
    # replaces "S" inside "Situation", "Suspension", etc.).  The LLM system
    # prompt already prohibits flagging single chars; this filter is the safety
    # net for when the model ignores the instruction.
    safe: list = []
    for f in (findings or []):
        if len(f.text.strip()) < 2:
            logger.warning(
                "Skipping single-character PII finding %r (type=%s) — "
                "too short to replace safely.",
                f.text, getattr(f.type, "value", f.type),
            )
            continue
        safe.append(f)
    findings = safe

    if not findings:
        return MappingTable(entries=[])

    # Stable-sort so counter assignment is deterministic
    sorted_findings = sorted(findings, key=lambda f: (str(f.type), f.text))

    # Deduplicate: key = (text, type); track sources
    seen: dict = {}  # (text, type_str) → {source_set, type_str}
    ordered_keys: list = []  # preserve first-seen order after sort

    for f in sorted_findings:
        type_str = f.type.value if hasattr(f.type, "value") else str(f.type)
        key = (f.text, type_str)
        if key not in seen:
            seen[key] = {"sources": set(), "type": type_str}
            ordered_keys.append(key)
        seen[key]["sources"].add(f.source or "unknown")

    # Assign placeholders (per-type counter)
    counters: dict = {}
    entries: List[MappingEntry] = []

    for key in ordered_keys:
        text, type_str = key
        meta = seen[key]
        counters[type_str] = counters.get(type_str, 0) + 1
        placeholder = f"[{type_str}_{counters[type_str]}]"

        sources = meta["sources"]
        if len(sources) > 1:
            source_val = "both"
        else:
            source_val = next(iter(sources))

        entries.append(MappingEntry(
            original=text,
            placeholder=placeholder,
            pii_type=type_str,
            source=source_val,
        ))

    return MappingTable(entries=entries)
