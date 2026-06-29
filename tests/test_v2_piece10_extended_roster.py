"""
V2 Piece 10 — Extended Name-List CSV

Tests:
  Parser — also_remove column
  - CSV with also_remove column → entry.also_remove populated
  - Semicolons in also_remove preserved verbatim
  - Empty also_remove cell → entry.also_remove is None
  - also_remove accepted alongside name columns

  Parser — single-column term list
  - Header 'text' → term-list mode, entries have also_remove, no first/last name
  - Header 'term' → same
  - Header 'terms' → same
  - Header 'remove' → same
  - Term-list CSV raises no ValueError despite having no name columns
  - Empty rows skipped in term-list mode
  - Duplicate terms deduplicated in term-list mode
  - Header-only term-list CSV → empty list

  name_matcher — ID mapping
  - Entry with student_id → [ID_1] in mapping
  - Original case string maps to [ID_1]
  - Lowercase variant also maps to [ID_1]
  - Empty student_id → no ID entry
  - Duplicate student_id across entries → one [ID_1] entry (dedup)
  - Multiple distinct IDs → [ID_1], [ID_2] in order

  name_matcher — EMAIL mapping
  - Entry with email → [EMAIL_1]
  - Lowercase variant included
  - Empty email → no EMAIL entry
  - Duplicate email across entries → deduplicated

  name_matcher — REDACTED mapping (also_remove)
  - Single-term also_remove → [REDACTED_1]
  - Semicolon-separated → each term gets its own [REDACTED_N]
  - Lowercase variant of each term included
  - Term shorter than 2 chars → skipped
  - Duplicate term across entries → one [REDACTED_N]
  - Term-only entry (no name) → REDACTED entries but no PERSON entries

  name_matcher — combined
  - Entry with name + ID + email + also_remove → all four types emitted
  - PERSON counter unaffected by ID/EMAIL/REDACTED entries
  - Counter independence: IDs numbered from 1 regardless of how many PERSONs exist

  Replacer integration
  - "STU001" in text replaced with [ID_1]
  - "jane@uni.edu" in text replaced with [EMAIL_1]
  - "Acme Corp" in text replaced with [REDACTED_1]
  - Word boundary: "STU0010" does NOT match [ID_1] for "STU001"
  - Term-only name list replaces all listed terms

  Database round-trip
  - also_remove stored and retrieved via add_roster_entries / get_roster_entries
"""

import pytest


# ============================================================
# Shared CSVs
# ============================================================

ALSO_REMOVE_CSV = """\
first_name,last_name,student_id,email,also_remove
Jane,Smith,STU001,jane@example.com,Acme Corp;Project Alpha
Bob,Jones,STU002,bob@example.com,
Alice,Wonder,,,Widget LLC
"""

TERM_LIST_TEXT_CSV = """\
text
Acme Corp
Project Alpha
Widget LLC
"""

TERM_LIST_TERM_CSV = """\
term
Foo Bar
Baz Qux
"""

TERM_LIST_TERMS_CSV = """\
terms
Alpha Team
Beta Team
"""

TERM_LIST_REMOVE_CSV = """\
remove
Classified Inc
Secret Project
"""

TERM_LIST_EMPTY_ROWS_CSV = """\
text
Acme Corp

Widget LLC

"""

TERM_LIST_DUPLICATES_CSV = """\
text
Acme Corp
Acme Corp
Widget LLC
"""

TERM_LIST_HEADER_ONLY_CSV = "text\n"

ALSO_REMOVE_ONLY_CSV = """\
first_name,last_name,also_remove
Jane,Smith,
Bob,Jones,Redact Me
"""


# ============================================================
# Parser: also_remove column
# ============================================================

class TestAlsoRemoveColumn:
    def test_also_remove_populated(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(ALSO_REMOVE_CSV.encode(), "roster.csv")
        jane = next(e for e in entries if e.first_name == "Jane")
        assert jane.also_remove == "Acme Corp;Project Alpha"

    def test_semicolons_preserved(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(ALSO_REMOVE_CSV.encode(), "roster.csv")
        jane = next(e for e in entries if e.first_name == "Jane")
        assert ";" in jane.also_remove

    def test_empty_also_remove_is_none(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(ALSO_REMOVE_CSV.encode(), "roster.csv")
        bob = next(e for e in entries if e.first_name == "Bob")
        assert bob.also_remove is None

    def test_also_remove_without_name_columns(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(ALSO_REMOVE_CSV.encode(), "roster.csv")
        alice = next(e for e in entries if e.first_name == "Alice")
        assert alice.also_remove == "Widget LLC"

    def test_also_remove_field_exists_on_roster_entry(self):
        from backend.services.roster_parser import RosterEntry
        e = RosterEntry(first_name="A", last_name="B", also_remove="X Corp")
        assert e.also_remove == "X Corp"

    def test_roster_entry_also_remove_defaults_to_none(self):
        from backend.services.roster_parser import RosterEntry
        e = RosterEntry(first_name="A", last_name="B")
        assert e.also_remove is None


# ============================================================
# Parser: single-column term list
# ============================================================

class TestTermListFormat:
    def test_text_header_produces_also_remove_entries(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_TEXT_CSV.encode(), "list.csv")
        assert len(entries) == 3
        assert all(e.also_remove is not None for e in entries)

    def test_text_header_no_first_last_name(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_TEXT_CSV.encode(), "list.csv")
        assert all(e.first_name is None and e.last_name is None for e in entries)

    def test_term_header_accepted(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_TERM_CSV.encode(), "list.csv")
        assert len(entries) == 2
        assert entries[0].also_remove == "Foo Bar"

    def test_terms_header_accepted(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_TERMS_CSV.encode(), "list.csv")
        assert len(entries) == 2

    def test_remove_header_accepted(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_REMOVE_CSV.encode(), "list.csv")
        assert len(entries) == 2
        assert entries[0].also_remove == "Classified Inc"

    def test_term_list_no_value_error(self):
        from backend.services.roster_parser import parse_roster
        # Must not raise even though there are no name columns
        entries = parse_roster(TERM_LIST_TEXT_CSV.encode(), "list.csv")
        assert isinstance(entries, list)

    def test_empty_rows_skipped(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_EMPTY_ROWS_CSV.encode(), "list.csv")
        assert len(entries) == 2

    def test_duplicates_deduplicated(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_DUPLICATES_CSV.encode(), "list.csv")
        assert len(entries) == 2  # "Acme Corp" appears twice → once

    def test_header_only_returns_empty_list(self):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(TERM_LIST_HEADER_ONLY_CSV.encode(), "list.csv")
        assert entries == []


# ============================================================
# name_matcher: ID mapping
# ============================================================

class TestIDMapping:
    def _entry(self, **kwargs):
        from backend.services.roster_parser import RosterEntry
        return RosterEntry(
            first_name=kwargs.get("first_name", "Jane"),
            last_name=kwargs.get("last_name", "Smith"),
            student_id=kwargs.get("student_id"),
            email=kwargs.get("email"),
            also_remove=kwargs.get("also_remove"),
        )

    def test_student_id_produces_id_entry(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(student_id="STU001")])
        types = {e.pii_type for e in mapping.entries}
        assert "ID" in types

    def test_id_placeholder_is_id_1(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(student_id="STU001")])
        ids = [e for e in mapping.entries if e.pii_type == "ID"]
        assert any(e.placeholder == "[ID_1]" for e in ids)

    def test_original_case_maps_to_id_1(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(student_id="STU001")])
        ids = {e.original: e.placeholder for e in mapping.entries if e.pii_type == "ID"}
        assert ids.get("STU001") == "[ID_1]"

    def test_lowercase_variant_maps_to_id_1(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(student_id="STU001")])
        ids = {e.original: e.placeholder for e in mapping.entries if e.pii_type == "ID"}
        assert ids.get("stu001") == "[ID_1]"

    def test_empty_student_id_no_id_entry(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(student_id=None)])
        assert not any(e.pii_type == "ID" for e in mapping.entries)

    def test_duplicate_student_id_deduped(self):
        from backend.services.name_matcher import build_name_mapping
        entries = [self._entry(student_id="STU001"), self._entry(first_name="Bob", last_name="Jones", student_id="STU001")]
        mapping = build_name_mapping(entries)
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        placeholders = {e.placeholder for e in id_entries}
        assert placeholders == {"[ID_1]"}

    def test_two_distinct_ids_numbered_sequentially(self):
        from backend.services.name_matcher import build_name_mapping
        entries = [self._entry(student_id="STU001"), self._entry(first_name="Bob", last_name="Jones", student_id="STU002")]
        mapping = build_name_mapping(entries)
        id_phs = sorted({e.placeholder for e in mapping.entries if e.pii_type == "ID"})
        assert id_phs == ["[ID_1]", "[ID_2]"]


# ============================================================
# name_matcher: EMAIL mapping
# ============================================================

class TestEmailMapping:
    def _entry(self, **kwargs):
        from backend.services.roster_parser import RosterEntry
        return RosterEntry(
            first_name=kwargs.get("first_name", "Jane"),
            last_name=kwargs.get("last_name", "Smith"),
            email=kwargs.get("email"),
        )

    def test_email_produces_email_entry(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(email="jane@example.com")])
        assert any(e.pii_type == "EMAIL" for e in mapping.entries)

    def test_email_placeholder_is_email_1(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(email="jane@example.com")])
        emails = [e for e in mapping.entries if e.pii_type == "EMAIL"]
        assert any(e.placeholder == "[EMAIL_1]" for e in emails)

    def test_lowercase_variant_included(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(email="Jane@Example.COM")])
        lc = {e.original for e in mapping.entries if e.pii_type == "EMAIL"}
        assert "jane@example.com" in lc

    def test_empty_email_no_entry(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(email=None)])
        assert not any(e.pii_type == "EMAIL" for e in mapping.entries)

    def test_duplicate_email_deduped(self):
        from backend.services.name_matcher import build_name_mapping
        entries = [self._entry(email="jane@example.com"), self._entry(first_name="Bob", last_name="Jones", email="jane@example.com")]
        mapping = build_name_mapping(entries)
        phs = {e.placeholder for e in mapping.entries if e.pii_type == "EMAIL"}
        assert phs == {"[EMAIL_1]"}


# ============================================================
# name_matcher: REDACTED mapping (also_remove)
# ============================================================

class TestRedactedMapping:
    def _entry(self, also_remove=None, first_name="Jane", last_name="Smith"):
        from backend.services.roster_parser import RosterEntry
        return RosterEntry(first_name=first_name, last_name=last_name, also_remove=also_remove)

    def _term_entry(self, term):
        from backend.services.roster_parser import RosterEntry
        return RosterEntry(first_name=None, last_name=None, also_remove=term)

    def test_single_term_produces_redacted_1(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(also_remove="Acme Corp")])
        phs = {e.placeholder for e in mapping.entries if e.pii_type == "REDACTED"}
        assert "[REDACTED_1]" in phs

    def test_original_term_original_case_mapped(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(also_remove="Acme Corp")])
        originals = {e.original for e in mapping.entries if e.pii_type == "REDACTED"}
        assert "Acme Corp" in originals

    def test_lowercase_variant_included(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(also_remove="Acme Corp")])
        originals = {e.original for e in mapping.entries if e.pii_type == "REDACTED"}
        assert "acme corp" in originals

    def test_semicolon_separated_terms_each_get_own_placeholder(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._entry(also_remove="Acme Corp;Project Alpha;123 Main St")])
        phs = sorted({e.placeholder for e in mapping.entries if e.pii_type == "REDACTED"})
        assert phs == ["[REDACTED_1]", "[REDACTED_2]", "[REDACTED_3]"]

    def test_short_term_skipped(self):
        from backend.services.name_matcher import build_name_mapping
        # "X" is 1 char → should be skipped
        mapping = build_name_mapping([self._entry(also_remove="X;Valid Term")])
        phs = {e.placeholder for e in mapping.entries if e.pii_type == "REDACTED"}
        assert "[REDACTED_1]" in phs
        # Only one term survives ("Valid Term"), not two
        assert "[REDACTED_2]" not in phs

    def test_duplicate_terms_across_entries_deduped(self):
        from backend.services.name_matcher import build_name_mapping
        e1 = self._entry(also_remove="Acme Corp")
        e2 = self._entry(first_name="Bob", last_name="Jones", also_remove="Acme Corp")
        mapping = build_name_mapping([e1, e2])
        phs = {e.placeholder for e in mapping.entries if e.pii_type == "REDACTED"}
        assert phs == {"[REDACTED_1]"}

    def test_term_only_entry_produces_no_person(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._term_entry("Acme Corp")])
        assert not any(e.pii_type == "PERSON" for e in mapping.entries)

    def test_term_only_entry_produces_redacted(self):
        from backend.services.name_matcher import build_name_mapping
        mapping = build_name_mapping([self._term_entry("Acme Corp")])
        assert any(e.pii_type == "REDACTED" for e in mapping.entries)


# ============================================================
# name_matcher: combined
# ============================================================

class TestCombinedMapping:
    def test_all_four_types_emitted_from_one_entry(self):
        from backend.services.roster_parser import RosterEntry
        from backend.services.name_matcher import build_name_mapping
        entry = RosterEntry(
            first_name="Jane", last_name="Smith",
            student_id="STU001",
            email="jane@example.com",
            also_remove="Acme Corp",
        )
        mapping = build_name_mapping([entry])
        types = {e.pii_type for e in mapping.entries}
        assert "PERSON" in types
        assert "ID" in types
        assert "EMAIL" in types
        assert "REDACTED" in types

    def test_person_counter_independent_of_others(self):
        from backend.services.roster_parser import RosterEntry
        from backend.services.name_matcher import build_name_mapping
        entries = [
            RosterEntry(first_name="Alice", last_name="A", student_id="ID1", email="a@x.com", also_remove="T1"),
            RosterEntry(first_name="Bob", last_name="B", student_id="ID2", email="b@x.com", also_remove="T2"),
        ]
        mapping = build_name_mapping(entries)
        person_phs = sorted({e.placeholder for e in mapping.entries if e.pii_type == "PERSON"})
        assert "[PERSON_1]" in person_phs
        assert "[PERSON_2]" in person_phs

    def test_id_counter_starts_at_1_regardless_of_person_count(self):
        from backend.services.roster_parser import RosterEntry
        from backend.services.name_matcher import build_name_mapping
        entries = [
            RosterEntry(first_name="Alice", last_name="A", student_id="ID1"),
            RosterEntry(first_name="Bob", last_name="B", student_id="ID2"),
        ]
        mapping = build_name_mapping(entries)
        id_phs = sorted({e.placeholder for e in mapping.entries if e.pii_type == "ID"})
        assert id_phs == ["[ID_1]", "[ID_2]"]


# ============================================================
# Replacer integration
# ============================================================

class TestReplacerIntegration:
    def _mapping_from_entries(self, *roster_entries):
        from backend.services.name_matcher import build_name_mapping
        return build_name_mapping(list(roster_entries))

    def _entry(self, **kwargs):
        from backend.services.roster_parser import RosterEntry
        return RosterEntry(
            first_name=kwargs.get("first_name", "Jane"),
            last_name=kwargs.get("last_name", "Smith"),
            student_id=kwargs.get("student_id"),
            email=kwargs.get("email"),
            also_remove=kwargs.get("also_remove"),
        )

    def test_id_replaced_in_text(self):
        from backend.services.replacer import apply_replacements
        mapping = self._mapping_from_entries(self._entry(student_id="STU001"))
        result = apply_replacements("Student STU001 submitted.", mapping)
        assert "[ID_1]" in result.text
        assert "STU001" not in result.text

    def test_email_replaced_in_text(self):
        from backend.services.replacer import apply_replacements
        mapping = self._mapping_from_entries(self._entry(email="jane@example.com"))
        result = apply_replacements("Contact jane@example.com for details.", mapping)
        assert "[EMAIL_1]" in result.text
        assert "jane@example.com" not in result.text

    def test_also_remove_replaced_in_text(self):
        from backend.services.replacer import apply_replacements
        mapping = self._mapping_from_entries(self._entry(also_remove="Acme Corp"))
        result = apply_replacements("Acme Corp submitted the form.", mapping)
        assert "[REDACTED_1]" in result.text
        assert "Acme Corp" not in result.text

    def test_word_boundary_no_partial_match(self):
        from backend.services.replacer import apply_replacements
        mapping = self._mapping_from_entries(self._entry(student_id="STU001"))
        result = apply_replacements("STU0010 is a different ID.", mapping)
        # STU0010 should NOT be replaced — it's longer than STU001
        assert "STU0010" in result.text

    def test_term_list_all_terms_replaced(self):
        from backend.services.roster_parser import RosterEntry
        from backend.services.name_matcher import build_name_mapping
        from backend.services.replacer import apply_replacements
        entries = [
            RosterEntry(first_name=None, last_name=None, also_remove="Classified Inc"),
            RosterEntry(first_name=None, last_name=None, also_remove="Secret Project"),
        ]
        mapping = build_name_mapping(entries)
        result = apply_replacements(
            "Classified Inc hired Secret Project for the contract.", mapping
        )
        assert "Classified Inc" not in result.text
        assert "Secret Project" not in result.text

    def test_semicolon_terms_all_replaced(self):
        from backend.services.replacer import apply_replacements
        mapping = self._mapping_from_entries(
            self._entry(also_remove="Acme Corp;Project Alpha")
        )
        result = apply_replacements("Acme Corp ran Project Alpha.", mapping)
        assert "Acme Corp" not in result.text
        assert "Project Alpha" not in result.text


# ============================================================
# Database round-trip
# ============================================================

class TestDatabaseAlsoRemove:
    def test_also_remove_stored_and_retrieved(self, tmp_path):
        from backend.db.database import init_db, get_db, create_roster, add_roster_entries, get_roster_entries
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_db(db_path)
        try:
            roster_id = create_roster(conn, "test")
            add_roster_entries(conn, roster_id, [
                {
                    "first_name": "Jane",
                    "last_name": "Smith",
                    "preferred_name": None,
                    "student_id": "STU001",
                    "email": "jane@example.com",
                    "also_remove": "Acme Corp;Project Alpha",
                }
            ])
            entries = get_roster_entries(conn, roster_id)
            assert len(entries) == 1
            assert entries[0]["also_remove"] == "Acme Corp;Project Alpha"
        finally:
            conn.close()

    def test_null_also_remove_stored_as_none(self, tmp_path):
        from backend.db.database import init_db, get_db, create_roster, add_roster_entries, get_roster_entries
        db_path = tmp_path / "test.db"
        init_db(db_path)
        conn = get_db(db_path)
        try:
            roster_id = create_roster(conn, "test")
            add_roster_entries(conn, roster_id, [
                {
                    "first_name": "Bob",
                    "last_name": "Jones",
                    "preferred_name": None,
                    "student_id": None,
                    "email": None,
                    "also_remove": None,
                }
            ])
            entries = get_roster_entries(conn, roster_id)
            assert entries[0]["also_remove"] is None
        finally:
            conn.close()
