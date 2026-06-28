"""
Piece 7 — Mapper & Replacer

Tests (Mapper):
- LLM and regex findings merged into single list
- Duplicates removed (same text + same type = one entry)
- Same text, different type → kept as two entries
- Placeholders are typed and sequential: [PERSON_1], [PERSON_2]
- Same real value always maps to same placeholder (idempotent)
- Multiple calls with same input produce identical mapping

Tests (Replacer):
- Replaces all occurrences of a mapped value
- Longest-match-first when spans overlap
- Returns positions of replacements for frontend highlighting
- Replaces in body, header, footer, and table cells independently
- Re-identification (reverse): swaps placeholders back to originals
- Round-trip: original → replaced → restored == original
- Does not corrupt text outside mapped spans
"""

import pytest
from conftest import KNOWN_PII, SAMPLE_PII_TEXT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def llm_findings():
    from backend.models.schemas import PIIFinding
    return [
        PIIFinding(text=KNOWN_PII["person"],  type="PERSON",  confidence="high", source="llm"),
        PIIFinding(text=KNOWN_PII["org"],     type="ORG",     confidence="high", source="llm"),
        PIIFinding(text=KNOWN_PII["email"],   type="EMAIL",   confidence="high", source="llm"),
        PIIFinding(text=KNOWN_PII["address"], type="ADDRESS", confidence="high", source="llm"),
        PIIFinding(text=KNOWN_PII["dob"],     type="DOB",     confidence="medium", source="llm"),
        PIIFinding(text=KNOWN_PII["account"], type="ACCOUNT", confidence="medium", source="llm"),
    ]


@pytest.fixture
def regex_findings():
    from backend.models.schemas import PIIFinding
    return [
        PIIFinding(text=KNOWN_PII["email"],  type="EMAIL",  confidence="high", source="regex"),
        PIIFinding(text=KNOWN_PII["phone1"], type="PHONE",  confidence="high", source="regex"),
        PIIFinding(text=KNOWN_PII["ssn"],    type="SSN",    confidence="high", source="regex"),
    ]


@pytest.fixture
def mapping_table(llm_findings, regex_findings):
    from backend.services.mapper import build_mapping
    return build_mapping(llm_findings + regex_findings)


# ---------------------------------------------------------------------------
# Mapper — merging
# ---------------------------------------------------------------------------

class TestMerge:
    def test_merged_list_contains_all_unique_values(self, mapping_table):
        originals = {e.original for e in mapping_table.entries}
        assert KNOWN_PII["person"] in originals
        assert KNOWN_PII["org"] in originals
        assert KNOWN_PII["email"] in originals
        assert KNOWN_PII["phone1"] in originals
        assert KNOWN_PII["ssn"] in originals

    def test_duplicate_email_appears_once(self, mapping_table):
        """email appears in both llm_findings and regex_findings; must deduplicate."""
        email_entries = [e for e in mapping_table.entries if e.original == KNOWN_PII["email"]]
        assert len(email_entries) == 1

    def test_source_merged_entry_is_both(self, mapping_table):
        """An entry found by both LLM and regex should note both sources."""
        email_entry = next(e for e in mapping_table.entries if e.original == KNOWN_PII["email"])
        assert email_entry.source in ("both", "llm+regex", ["llm", "regex"])

    def test_empty_findings_returns_empty_mapping(self):
        from backend.services.mapper import build_mapping
        table = build_mapping([])
        assert table.entries == []

    def test_llm_only_findings_all_present(self, llm_findings):
        from backend.services.mapper import build_mapping
        table = build_mapping(llm_findings)
        originals = {e.original for e in table.entries}
        assert KNOWN_PII["person"] in originals

    def test_regex_only_findings_all_present(self, regex_findings):
        from backend.services.mapper import build_mapping
        table = build_mapping(regex_findings)
        originals = {e.original for e in table.entries}
        assert KNOWN_PII["ssn"] in originals


# ---------------------------------------------------------------------------
# Mapper — placeholder assignment
# ---------------------------------------------------------------------------

class TestPlaceholderAssignment:
    def test_person_placeholder_format(self, mapping_table):
        person_entry = next(e for e in mapping_table.entries if e.original == KNOWN_PII["person"])
        assert person_entry.placeholder.startswith("[PERSON_")
        assert person_entry.placeholder.endswith("]")

    def test_email_placeholder_format(self, mapping_table):
        email_entry = next(e for e in mapping_table.entries if e.original == KNOWN_PII["email"])
        assert email_entry.placeholder.startswith("[EMAIL_")

    def test_ssn_placeholder_format(self, mapping_table):
        ssn_entry = next(e for e in mapping_table.entries if e.original == KNOWN_PII["ssn"])
        assert ssn_entry.placeholder.startswith("[SSN_")

    def test_sequential_numbering_for_same_type(self, llm_findings):
        from backend.models.schemas import PIIFinding
        from backend.services.mapper import build_mapping
        extra = PIIFinding(text="Bob Jones", type="PERSON", confidence="high", source="llm")
        table = build_mapping(llm_findings + [extra])
        person_placeholders = sorted(
            e.placeholder for e in table.entries if e.pii_type == "PERSON"
        )
        assert "[PERSON_1]" in person_placeholders
        assert "[PERSON_2]" in person_placeholders

    def test_different_types_have_independent_counters(self, mapping_table):
        """[PERSON_1] and [EMAIL_1] can coexist — counters are per-type."""
        placeholders = [e.placeholder for e in mapping_table.entries]
        assert "[PERSON_1]" in placeholders
        assert "[EMAIL_1]" in placeholders

    def test_same_value_always_same_placeholder(self, llm_findings, regex_findings):
        from backend.services.mapper import build_mapping
        table1 = build_mapping(llm_findings + regex_findings)
        table2 = build_mapping(llm_findings + regex_findings)
        ph1 = {e.original: e.placeholder for e in table1.entries}
        ph2 = {e.original: e.placeholder for e in table2.entries}
        assert ph1 == ph2

    def test_lookup_by_original(self, mapping_table):
        ph = mapping_table.get_placeholder(KNOWN_PII["person"])
        assert ph is not None
        assert "[PERSON_" in ph

    def test_lookup_nonexistent_original_returns_none(self, mapping_table):
        ph = mapping_table.get_placeholder("Nonexistent Person Name")
        assert ph is None


# ---------------------------------------------------------------------------
# Replacer — text replacement
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_mapping():
    from backend.services.mapper import MappingTable, MappingEntry
    return MappingTable(entries=[
        MappingEntry(original=KNOWN_PII["person"],  placeholder="[PERSON_1]", pii_type="PERSON"),
        MappingEntry(original=KNOWN_PII["email"],   placeholder="[EMAIL_1]",  pii_type="EMAIL"),
        MappingEntry(original=KNOWN_PII["phone1"],  placeholder="[PHONE_1]",  pii_type="PHONE"),
        MappingEntry(original=KNOWN_PII["ssn"],     placeholder="[SSN_1]",    pii_type="SSN"),
        MappingEntry(original=KNOWN_PII["address"], placeholder="[ADDRESS_1]",pii_type="ADDRESS"),
    ])


class TestReplacer:
    def test_replaces_person_name(self, simple_mapping):
        from backend.services.replacer import apply_replacements
        text = f"Name: {KNOWN_PII['person']}"
        result = apply_replacements(text, simple_mapping)
        assert "[PERSON_1]" in result.text
        assert KNOWN_PII["person"] not in result.text

    def test_replaces_all_occurrences(self, simple_mapping):
        from backend.services.replacer import apply_replacements
        text = (
            f"{KNOWN_PII['person']} called. "
            f"Please contact {KNOWN_PII['person']} again."
        )
        result = apply_replacements(text, simple_mapping)
        assert result.text.count("[PERSON_1]") == 2
        assert KNOWN_PII["person"] not in result.text

    def test_replaces_email(self, simple_mapping):
        from backend.services.replacer import apply_replacements
        text = f"Email: {KNOWN_PII['email']}"
        result = apply_replacements(text, simple_mapping)
        assert "[EMAIL_1]" in result.text
        assert KNOWN_PII["email"] not in result.text

    def test_does_not_corrupt_surrounding_text(self, simple_mapping):
        from backend.services.replacer import apply_replacements
        text = f"Dear {KNOWN_PII['person']}, thank you."
        result = apply_replacements(text, simple_mapping)
        assert result.text.startswith("Dear ")
        assert result.text.endswith(", thank you.")

    def test_empty_mapping_returns_text_unchanged(self):
        from backend.services.mapper import MappingTable
        from backend.services.replacer import apply_replacements
        table = MappingTable(entries=[])
        text = SAMPLE_PII_TEXT
        result = apply_replacements(text, table)
        assert result.text == text

    def test_returns_replacement_positions(self, simple_mapping):
        from backend.services.replacer import apply_replacements
        text = f"Name: {KNOWN_PII['person']}"
        result = apply_replacements(text, simple_mapping)
        assert result.positions is not None
        assert isinstance(result.positions, list)
        assert len(result.positions) >= 1

    def test_position_has_start_end_and_type(self, simple_mapping):
        from backend.services.replacer import apply_replacements
        text = f"Name: {KNOWN_PII['person']}"
        result = apply_replacements(text, simple_mapping)
        pos = result.positions[0]
        assert hasattr(pos, "start") or "start" in pos
        assert hasattr(pos, "end") or "end" in pos
        assert hasattr(pos, "pii_type") or "pii_type" in pos

    def test_longest_match_wins_for_overlapping_spans(self):
        """'John Smith' should be replaced as a whole, not split into 'John' and 'Smith'."""
        from backend.services.mapper import MappingTable, MappingEntry
        from backend.services.replacer import apply_replacements
        table = MappingTable(entries=[
            MappingEntry(original="John Smith", placeholder="[PERSON_1]", pii_type="PERSON"),
            MappingEntry(original="John",       placeholder="[PERSON_2]", pii_type="PERSON"),
        ])
        text = "Contact John Smith today."
        result = apply_replacements(text, table)
        assert "[PERSON_1]" in result.text
        assert "[PERSON_2]" not in result.text


# ---------------------------------------------------------------------------
# Replacer — structured document replacement
# ---------------------------------------------------------------------------

class TestStructuredReplacement:
    def test_replaces_in_header(self, simple_mapping):
        from backend.services.replacer import apply_replacements_to_document
        doc = {
            "body_text": "Hello world",
            "header_text": f"Company: {KNOWN_PII['org']}",
            "footer_text": "",
            "table_cells": [],
        }
        from backend.services.mapper import MappingTable, MappingEntry
        table = MappingTable(entries=[
            MappingEntry(original=KNOWN_PII["org"], placeholder="[ORG_1]", pii_type="ORG"),
        ])
        result = apply_replacements_to_document(doc, table)
        assert "[ORG_1]" in result["header_text"]
        assert KNOWN_PII["org"] not in result["header_text"]

    def test_replaces_in_footer(self, simple_mapping):
        from backend.services.replacer import apply_replacements_to_document
        from backend.services.mapper import MappingTable, MappingEntry
        doc = {
            "body_text": "",
            "header_text": "",
            "footer_text": f"Contact: {KNOWN_PII['phone1']}",
            "table_cells": [],
        }
        table = MappingTable(entries=[
            MappingEntry(original=KNOWN_PII["phone1"], placeholder="[PHONE_1]", pii_type="PHONE"),
        ])
        result = apply_replacements_to_document(doc, table)
        assert "[PHONE_1]" in result["footer_text"]

    def test_replaces_in_table_cells(self, simple_mapping):
        from backend.services.replacer import apply_replacements_to_document
        from backend.services.mapper import MappingTable, MappingEntry
        doc = {
            "body_text": "",
            "header_text": "",
            "footer_text": "",
            "table_cells": [["Name", "SSN"], [KNOWN_PII["person"], KNOWN_PII["ssn"]]],
        }
        table = MappingTable(entries=[
            MappingEntry(original=KNOWN_PII["person"], placeholder="[PERSON_1]", pii_type="PERSON"),
            MappingEntry(original=KNOWN_PII["ssn"],    placeholder="[SSN_1]",    pii_type="SSN"),
        ])
        result = apply_replacements_to_document(doc, table)
        assert result["table_cells"][1][0] == "[PERSON_1]"
        assert result["table_cells"][1][1] == "[SSN_1]"

    def test_body_unaffected_by_header_replacement(self):
        """A replacement in the header must not alter body text."""
        from backend.services.replacer import apply_replacements_to_document
        from backend.services.mapper import MappingTable, MappingEntry
        doc = {
            "body_text": "Clean body text with no PII.",
            "header_text": f"Header: {KNOWN_PII['person']}",
            "footer_text": "",
            "table_cells": [],
        }
        table = MappingTable(entries=[
            MappingEntry(original=KNOWN_PII["person"], placeholder="[PERSON_1]", pii_type="PERSON"),
        ])
        result = apply_replacements_to_document(doc, table)
        assert result["body_text"] == "Clean body text with no PII."


# ---------------------------------------------------------------------------
# Round-trip (replace → re-identify)
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_reverse_mapping_restores_original(self, simple_mapping):
        from backend.services.replacer import apply_replacements, reverse_replacements
        original = f"{KNOWN_PII['person']} — {KNOWN_PII['email']}"
        replaced = apply_replacements(original, simple_mapping)
        restored = reverse_replacements(replaced.text, simple_mapping)
        assert restored == original

    def test_reverse_restores_all_pii(self, simple_mapping):
        from backend.services.replacer import apply_replacements, reverse_replacements
        replaced = apply_replacements(SAMPLE_PII_TEXT, simple_mapping)
        restored = reverse_replacements(replaced.text, simple_mapping)
        for key in ("person", "email", "phone1", "ssn"):
            assert KNOWN_PII[key] in restored

    def test_reverse_is_100_percent_faithful(self, simple_mapping):
        """Spec success criterion: 100% mapping fidelity."""
        from backend.services.replacer import apply_replacements, reverse_replacements
        original = SAMPLE_PII_TEXT
        replaced = apply_replacements(original, simple_mapping)
        restored = reverse_replacements(replaced.text, simple_mapping)
        assert restored == original

    def test_unknown_placeholder_in_reverse_raises(self, simple_mapping):
        """If a placeholder in the anonymized file isn't in the mapping, raise."""
        from backend.services.replacer import reverse_replacements
        with pytest.raises(Exception):
            reverse_replacements("Hello [PERSON_99]", simple_mapping)
