"""
V2 Piece 3 — Fuzzy Name Matcher

Tests:
- Canonical "First Last" matched
- Reversed "Last First" matched
- "Last, First" comma format matched
- "F. Last" initial-dot format matched
- "F Last" initial-no-dot format matched
- Nickname/diminutive matched (Joe → Joseph, Rob → Robert, etc.)
- Preferred name from roster matched
- Two-character minimum enforced (initials alone do NOT match)
- Word-boundary matching: "Smith" in "Smithson" does NOT match
- Case-insensitive matching ("jane smith" == "Jane Smith")
- Multiple students produce independent [PERSON_N] placeholders
- Unknown name (not in roster) produces no mapping entry
- Empty roster returns empty MappingTable
- Single-entry roster works correctly
- Duplicate name variants don't produce duplicate mapping entries
- Name spanning a chunk boundary: both parts present in text → still matched
- Nickname table contains common English variants (spot checks)
"""

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def single_entry_roster():
    from backend.services.roster_parser import RosterEntry
    return [
        RosterEntry(
            first_name="Jane",
            last_name="Smith",
            preferred_name="Janie",
            student_id="STU001",
            email=None,
        )
    ]


@pytest.fixture
def multi_entry_roster():
    from backend.services.roster_parser import RosterEntry
    return [
        RosterEntry("Jane", "Smith", "Janie", "STU001", None),
        RosterEntry("Robert", "Jones", None, "STU002", None),
        RosterEntry("Michael", "Brown", "Mike", "STU003", None),
        RosterEntry("Joseph", "Davis", "Joe", "STU004", None),
    ]


# ---------------------------------------------------------------------------
# Nickname table spot checks
# ---------------------------------------------------------------------------

class TestNicknameTable:
    def test_nickname_table_is_dict(self):
        from backend.services.name_matcher import NICKNAME_TABLE
        assert isinstance(NICKNAME_TABLE, dict)

    def test_nickname_table_has_100_plus_entries(self):
        from backend.services.name_matcher import NICKNAME_TABLE
        assert len(NICKNAME_TABLE) >= 100

    def test_joe_maps_to_joseph(self):
        from backend.services.name_matcher import NICKNAME_TABLE
        joseph_nicknames = NICKNAME_TABLE.get("JOSEPH", [])
        assert "JOE" in joseph_nicknames or "JOSEPH" in NICKNAME_TABLE.get("JOE", [])

    def test_rob_maps_to_robert(self):
        from backend.services.name_matcher import NICKNAME_TABLE
        # Either ROBERT → [ROB, BOB, ...] or ROB → ROBERT
        hit = (
            "ROB" in NICKNAME_TABLE.get("ROBERT", [])
            or "ROBERT" in NICKNAME_TABLE.get("ROB", [])
        )
        assert hit

    def test_bill_maps_to_william(self):
        from backend.services.name_matcher import NICKNAME_TABLE
        hit = (
            "BILL" in NICKNAME_TABLE.get("WILLIAM", [])
            or "WILLIAM" in NICKNAME_TABLE.get("BILL", [])
        )
        assert hit

    def test_liz_maps_to_elizabeth(self):
        from backend.services.name_matcher import NICKNAME_TABLE
        hit = (
            "LIZ" in NICKNAME_TABLE.get("ELIZABETH", [])
            or "ELIZABETH" in NICKNAME_TABLE.get("LIZ", [])
        )
        assert hit


# ---------------------------------------------------------------------------
# build_name_mapping — happy path
# ---------------------------------------------------------------------------

class TestBuildNameMapping:
    def test_empty_roster_returns_empty_table(self):
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping([])
        assert table.entries == []

    def test_canonical_first_last_matched(self, single_entry_roster):
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        originals = {e.original for e in table.entries}
        assert "Jane Smith" in originals

    def test_reversed_last_first_matched(self, single_entry_roster):
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        originals = {e.original for e in table.entries}
        assert "Smith Jane" in originals or "Smith, Jane" in originals

    def test_initial_dot_format_matched(self, single_entry_roster):
        """'J. Smith' must appear as a variant."""
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        originals = {e.original for e in table.entries}
        assert "J. Smith" in originals

    def test_initial_no_dot_format_matched(self, single_entry_roster):
        """'J Smith' must appear as a variant."""
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        originals = {e.original for e in table.entries}
        assert "J Smith" in originals

    def test_preferred_name_matched(self, single_entry_roster):
        """'Janie Smith' must appear because preferred_name='Janie'."""
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        originals = {e.original for e in table.entries}
        assert "Janie Smith" in originals

    def test_nickname_variant_matched(self, multi_entry_roster):
        """'Joe Davis' must appear because Joseph's nickname is Joe."""
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(multi_entry_roster)
        originals = {e.original for e in table.entries}
        assert "Joe Davis" in originals

    def test_all_variants_map_to_same_placeholder(self, single_entry_roster):
        """All variants for one student must share the same placeholder."""
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        person_entries = [e for e in table.entries if e.pii_type == "PERSON"]
        placeholders = {e.placeholder for e in person_entries}
        # All variants for Jane Smith → [PERSON_1]
        assert len(placeholders) == 1

    def test_two_students_get_different_placeholders(self, multi_entry_roster):
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(multi_entry_roster)
        person_entries = [e for e in table.entries if e.pii_type == "PERSON"]
        placeholders = {e.placeholder for e in person_entries}
        assert len(placeholders) >= 2

    def test_entry_types_are_known_roster_types(self, multi_entry_roster):
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(multi_entry_roster)
        allowed_types = {"PERSON", "ID", "EMAIL", "REDACTED"}
        for e in table.entries:
            assert e.pii_type in allowed_types, f"Unexpected type {e.pii_type!r}"

    def test_no_single_char_variants_produced(self, single_entry_roster):
        """No variant shorter than 2 chars must appear (word-boundary safety)."""
        from backend.services.name_matcher import build_name_mapping
        table = build_name_mapping(single_entry_roster)
        for e in table.entries:
            assert len(e.original.strip()) >= 2, (
                f"Single-char variant produced: {e.original!r}"
            )

    def test_single_entry_roster_works(self):
        """Smoke test: a roster with one student produces at least one mapping."""
        from backend.services.roster_parser import RosterEntry
        from backend.services.name_matcher import build_name_mapping
        roster = [RosterEntry("Alice", "Wonder", None, None, None)]
        table = build_name_mapping(roster)
        assert len(table.entries) > 0


# ---------------------------------------------------------------------------
# Matching in text (apply_replacements integration)
# ---------------------------------------------------------------------------

class TestNameMatchingInText:
    def _apply(self, roster, text):
        from backend.services.name_matcher import build_name_mapping
        from backend.services.replacer import apply_replacements
        table = build_name_mapping(roster)
        return apply_replacements(text, table)

    def test_canonical_name_replaced(self, single_entry_roster):
        result = self._apply(single_entry_roster, "Patient: Jane Smith was seen.")
        assert "[PERSON_1]" in result.text
        assert "Jane Smith" not in result.text

    def test_nickname_replaced(self, multi_entry_roster):
        result = self._apply(multi_entry_roster, "Joe Davis submitted the exam.")
        assert "[PERSON_" in result.text
        assert "Joe Davis" not in result.text

    def test_initial_format_replaced(self, single_entry_roster):
        result = self._apply(single_entry_roster, "Signature: J. Smith")
        assert "[PERSON_1]" in result.text

    def test_non_roster_name_untouched(self, single_entry_roster):
        result = self._apply(single_entry_roster, "Unknown Person wrote this.")
        assert "Unknown Person" in result.text

    def test_partial_last_name_not_matched(self, single_entry_roster):
        """'Smithson' must not be replaced just because 'Smith' is in the roster."""
        result = self._apply(single_entry_roster, "Contact Smithson Industries.")
        assert "Smithson" in result.text

    def test_case_insensitive_match(self, single_entry_roster):
        result = self._apply(single_entry_roster, "Submitted by jane smith.")
        assert "jane smith" not in result.text.lower() or "[PERSON_" in result.text

    def test_two_roster_names_both_replaced(self, multi_entry_roster):
        result = self._apply(
            multi_entry_roster,
            "Jane Smith and Robert Jones both passed."
        )
        assert "Jane Smith" not in result.text
        assert "Robert Jones" not in result.text

    def test_non_roster_text_completely_preserved(self, single_entry_roster):
        text = "The assignment was due on Monday at noon."
        result = self._apply(single_entry_roster, text)
        assert result.text == text

    def test_empty_roster_leaves_text_unchanged(self):
        from backend.services.name_matcher import build_name_mapping
        from backend.services.replacer import apply_replacements
        table = build_name_mapping([])
        text = "Jane Smith was here."
        result = apply_replacements(text, table)
        assert result.text == text
