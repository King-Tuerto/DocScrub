"""
V2 Piece 12 — Real-world test regression suite

Covers five issues found in real-world testing:

  Issue 1 — Numeric student ID not replaced
    • Numeric IDs (e.g. "4412087") produce an ID mapping entry
    • apply_replacements replaces the ID in body text
    • init_db migrates legacy DBs that lack the student_id column
    • ID-only roster entries (no name) work end-to-end

  Issue 2 — Title prefix + standalone last name variants
    • Title prefixes: Professor, Prof., Dr., Mr., Mrs., Ms., Miss, Mx.
    • Standalone last name ("Waterman") generated as a variant
    • Standalone first name ("Paul") is NOT generated
    • Title variants filtered by text (only those present in document)
    • Mapping round-trip: "Dr. Smith" in text → replaced as [PERSON_1]

  Issue 4 — Text-filtering verification (real-world scenario)
    • Upload only Robert Chen's paper → Maria Gonzalez does NOT appear in mapping
    • Roster with 3 people; only 1 in document → exactly 1 PERSON entry
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest


# ============================================================
# Shared helpers
# ============================================================

def _entry(first=None, last=None, preferred=None, student_id=None, email=None, also_remove=None):
    from backend.services.roster_parser import RosterEntry
    return RosterEntry(
        first_name=first, last_name=last,
        preferred_name=preferred,
        student_id=student_id,
        email=email,
        also_remove=also_remove,
    )


def _mapping(entries, text=None):
    from backend.services.name_matcher import build_name_mapping
    return build_name_mapping(entries, text=text)


def _replace(text, mapping_table):
    from backend.services.replacer import apply_replacements
    return apply_replacements(text, mapping_table)


# ============================================================
# Issue 1 — Numeric student ID replacement
# ============================================================

class TestNumericIDInMapping:
    """build_name_mapping correctly emits entries for numeric IDs."""

    def test_numeric_id_emits_id_entry_no_filter(self):
        entry = _entry(first="Paul", last="Waterman", student_id="4412087")
        mapping = _mapping([entry])
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        assert len(id_entries) == 1
        assert id_entries[0].original == "4412087"
        assert id_entries[0].placeholder == "[ID_1]"

    def test_numeric_id_emits_id_entry_with_text_filter(self):
        entry = _entry(first="Paul", last="Waterman", student_id="4412087")
        mapping = _mapping([entry], text="Student ID: 4412087 is enrolled.")
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        assert len(id_entries) == 1
        assert id_entries[0].original == "4412087"

    def test_numeric_id_not_in_text_excluded(self):
        entry = _entry(first="Paul", last="Waterman", student_id="4412087")
        mapping = _mapping([entry], text="No ID mentioned here.")
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        assert len(id_entries) == 0

    def test_numeric_id_word_boundary_not_partial(self):
        # "44120870" is in text but not "4412087" — should not match
        entry = _entry(student_id="4412087")
        mapping = _mapping([entry], text="ID is 44120870 here.")
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        assert len(id_entries) == 0

    def test_id_only_entry_no_name_fields(self):
        """Roster entry with student_id but no name is processed correctly."""
        entry = _entry(student_id="4412087")
        mapping = _mapping([entry], text="4412087")
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        assert len(id_entries) == 1
        person_entries = [e for e in mapping.entries if e.pii_type == "PERSON"]
        assert len(person_entries) == 0

    def test_multiple_numeric_ids_counter_increments(self):
        entries = [
            _entry(student_id="1001"),
            _entry(student_id="1002"),
            _entry(student_id="1003"),
        ]
        mapping = _mapping(entries, text="Students 1001, 1002, 1003 enrolled.")
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        placeholders = {e.placeholder for e in id_entries}
        assert placeholders == {"[ID_1]", "[ID_2]", "[ID_3]"}


class TestNumericIDReplacement:
    """apply_replacements correctly substitutes numeric IDs in text."""

    def test_replaces_numeric_id_in_label_line(self):
        entry = _entry(first="Paul", last="Waterman", student_id="4412087")
        mapping = _mapping([entry])
        result = _replace("Student ID: 4412087", mapping)
        assert "[ID_1]" in result.text
        assert "4412087" not in result.text

    def test_replaces_numeric_id_standalone(self):
        entry = _entry(student_id="4412087")
        mapping = _mapping([entry])
        result = _replace("4412087", mapping)
        assert result.text == "[ID_1]"

    def test_replaces_numeric_id_surrounded_by_punctuation(self):
        entry = _entry(student_id="4412087")
        mapping = _mapping([entry])
        result = _replace("(4412087)", mapping)
        assert "[ID_1]" in result.text
        assert "4412087" not in result.text

    def test_does_not_replace_partial_match(self):
        entry = _entry(student_id="4412087")
        mapping = _mapping([entry])
        # "44120870" contains the ID as substring but must not be replaced
        result = _replace("44120870", mapping)
        assert "44120870" in result.text
        assert "[ID_1]" not in result.text

    def test_replaces_alphanumeric_id(self):
        entry = _entry(student_id="STU001")
        mapping = _mapping([entry])
        result = _replace("Student STU001 enrolled.", mapping)
        assert "[ID_1]" in result.text
        assert "STU001" not in result.text

    def test_replaces_lowercase_variant_of_alphanumeric_id(self):
        entry = _entry(student_id="STU001")
        mapping = _mapping([entry])
        result = _replace("Student stu001 enrolled.", mapping)
        assert "[ID_1]" in result.text
        assert "stu001" not in result.text

    def test_id_and_name_both_replaced(self):
        entry = _entry(first="Paul", last="Waterman", student_id="4412087")
        mapping = _mapping([entry])
        result = _replace("Paul Waterman, Student ID: 4412087.", mapping)
        assert "[ID_1]" in result.text
        assert "4412087" not in result.text
        assert "[PERSON_1]" in result.text
        assert "Paul Waterman" not in result.text


class TestStudentIDDBMigration:
    """init_db adds student_id column to legacy roster_entries tables."""

    def test_student_id_column_ensured_on_fresh_db(self, tmp_path):
        db_path = tmp_path / "fresh.db"
        from backend.db.database import init_db
        init_db(db_path)
        conn = sqlite3.connect(str(db_path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(roster_entries)")}
        conn.close()
        assert "student_id" in cols

    def test_student_id_column_added_to_legacy_db(self, tmp_path):
        """DB created before student_id existed gets it added by init_db."""
        db_path = tmp_path / "legacy.db"
        # Create legacy schema without student_id
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rosters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS roster_entries (
                id TEXT PRIMARY KEY,
                roster_id TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                preferred_name TEXT,
                email TEXT,
                FOREIGN KEY (roster_id) REFERENCES rosters(id)
            );
        """)
        conn.commit()
        conn.close()

        # init_db must add student_id to the existing table
        from backend.db.database import init_db
        init_db(db_path)

        conn = sqlite3.connect(str(db_path))
        cols = {row[1] for row in conn.execute("PRAGMA table_info(roster_entries)")}
        conn.close()
        assert "student_id" in cols, "init_db must migrate student_id for legacy DBs"

    def test_insert_and_retrieve_student_id_after_migration(self, tmp_path):
        """Can store and retrieve student_id after migration from legacy schema."""
        db_path = tmp_path / "legacy2.db"
        # Build minimal schema without student_id
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS rosters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS roster_entries (
                id TEXT PRIMARY KEY,
                roster_id TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                preferred_name TEXT,
                email TEXT
            );
        """)
        conn.commit()
        conn.close()

        from backend.db.database import init_db, get_db, create_roster, add_roster_entries, get_roster_entries
        init_db(db_path)
        conn = get_db(db_path)
        roster_id = create_roster(conn, "Test Roster")
        add_roster_entries(conn, roster_id, [
            {"first_name": "Paul", "last_name": "Waterman", "student_id": "4412087", "also_remove": None},
        ])
        rows = get_roster_entries(conn, roster_id)
        conn.close()
        assert len(rows) == 1
        assert rows[0]["student_id"] == "4412087"


# ============================================================
# Issue 2 — Title prefix variants
# ============================================================

class TestTitlePrefixVariants:
    """_generate_variants emits title-prefixed forms of the last name."""

    def _variants(self, first, last, preferred=None):
        from backend.services.name_matcher import _generate_variants
        from backend.services.roster_parser import RosterEntry
        entry = RosterEntry(
            first_name=first, last_name=last,
            preferred_name=preferred,
            student_id=None, email=None, also_remove=None,
        )
        return set(_generate_variants(entry))

    def test_dr_last_name_generated(self):
        v = self._variants("Paul", "Waterman")
        assert "Dr. Waterman" in v

    def test_professor_last_name_generated(self):
        v = self._variants("Paul", "Waterman")
        assert "Professor Waterman" in v

    def test_prof_last_name_generated(self):
        v = self._variants("Paul", "Waterman")
        assert "Prof. Waterman" in v

    def test_mr_last_name_generated(self):
        v = self._variants("Paul", "Waterman")
        assert "Mr. Waterman" in v

    def test_mrs_last_name_generated(self):
        v = self._variants("Maria", "Gonzalez")
        assert "Mrs. Gonzalez" in v

    def test_ms_last_name_generated(self):
        v = self._variants("Maria", "Gonzalez")
        assert "Ms. Gonzalez" in v

    def test_miss_last_name_generated(self):
        v = self._variants("Maria", "Gonzalez")
        assert "Miss Gonzalez" in v

    def test_mx_last_name_generated(self):
        v = self._variants("Alex", "Kim")
        assert "Mx. Kim" in v

    def test_all_titles_present(self):
        expected_titles = [
            "Professor", "Prof.", "Dr.", "Mr.", "Mrs.", "Ms.", "Miss", "Mx.",
        ]
        v = self._variants("Jane", "Smith")
        for title in expected_titles:
            assert f"{title} Smith" in v, f"Expected '{title} Smith' in variants"

    def test_title_variants_have_lowercase_form(self):
        v = self._variants("Jane", "Smith")
        assert "dr. smith" in v
        assert "professor smith" in v
        assert "mr. smith" in v

    def test_no_title_prefix_without_last_name(self):
        v = self._variants("Jane", "")
        # No last name → no title variants
        assert not any("Dr." in vv for vv in v)
        assert not any("Professor" in vv for vv in v)

    def test_standalone_last_name_generated(self):
        v = self._variants("Paul", "Waterman")
        assert "Waterman" in v

    def test_standalone_first_name_NOT_generated(self):
        v = self._variants("Paul", "Waterman")
        # "Paul" alone must not appear (too many false positives)
        assert "Paul" not in v
        assert "paul" not in v

    def test_standalone_last_name_lowercase_form(self):
        v = self._variants("Paul", "Waterman")
        assert "waterman" in v

    def test_standalone_last_name_no_last_name(self):
        v = self._variants("Jane", "")
        # No last name → no standalone last name
        assert "" not in v
        assert not any(vv == "" for vv in v)


class TestTitleVariantFiltering:
    """Title variants are filtered correctly when text is provided."""

    def test_title_in_text_included(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="Dr. Smith reviewed the document.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert "Dr. Smith" in person_originals

    def test_title_not_in_text_excluded(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="Jane Smith wrote this.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        # "Dr. Smith" is NOT in the text — must not appear in mapping
        assert "Dr. Smith" not in person_originals

    def test_standalone_last_name_in_text_included(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="As Smith noted in section 2.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert "Smith" in person_originals

    def test_standalone_last_name_not_in_text_excluded(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="No names here.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert "Smith" not in person_originals

    def test_title_variant_replaced_in_text(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry])
        from backend.services.replacer import apply_replacements
        result = apply_replacements("Dr. Smith graded the paper.", mapping)
        assert "[PERSON_1]" in result.text
        assert "Dr. Smith" not in result.text

    def test_standalone_last_name_replaced_in_text(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry])
        from backend.services.replacer import apply_replacements
        result = apply_replacements("As Smith noted in section 2.", mapping)
        assert "[PERSON_1]" in result.text
        assert "Smith" not in result.text

    def test_professor_variant_replaced(self):
        entry = _entry(first="Robert", last="Chen")
        mapping = _mapping([entry])
        from backend.services.replacer import apply_replacements
        result = apply_replacements("Professor Chen assigned this paper.", mapping)
        assert "[PERSON_1]" in result.text
        assert "Professor Chen" not in result.text


# ============================================================
# Issue 4 — Text-filtering: real-world scenario
# ============================================================

class TestRealWorldTextFiltering:
    """Only people mentioned in the uploaded document appear in the mapping."""

    def test_only_robert_chen_in_paper_not_maria(self):
        """
        Roster has Robert Chen and Maria Gonzalez.
        Document is Robert Chen's paper — only Robert should appear.
        """
        entries = [
            _entry(first="Robert", last="Chen"),
            _entry(first="Maria", last="Gonzalez"),
        ]
        text = (
            "Robert Chen\n"
            "Introduction\n"
            "This paper examines neural network architectures.\n"
            "Chen et al. (2024) proposed a novel approach.\n"
            "Conclusion\n"
            "Robert Chen expresses gratitude to the reviewers."
        )
        mapping = _mapping(entries, text=text)
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}

        # Robert / Chen variants present
        assert any("Chen" in o or "Robert" in o for o in person_originals), (
            "Expected Robert Chen's variants in mapping"
        )
        # Maria Gonzalez variants absent
        gonzalez_variants = [o for o in person_originals if "Gonzalez" in o or "Maria" in o]
        assert gonzalez_variants == [], (
            f"Maria Gonzalez variants must not appear: {gonzalez_variants}"
        )

    def test_three_person_roster_one_in_doc(self):
        entries = [
            _entry(first="Alice", last="Adams"),
            _entry(first="Bob", last="Baker"),
            _entry(first="Carol", last="Clark"),
        ]
        text = "Bob Baker submitted this report on January 1st."
        mapping = _mapping(entries, text=text)
        person_phs = {e.placeholder for e in mapping.entries if e.pii_type == "PERSON"}
        assert len(person_phs) == 1
        assert "[PERSON_1]" in person_phs

    def test_id_in_text_but_not_name(self):
        """
        Roster has Paul Waterman with ID 4412087.
        Document only has the ID, not the name.
        """
        entry = _entry(first="Paul", last="Waterman", student_id="4412087")
        text = "Student ID: 4412087 completed the assignment."
        mapping = _mapping([entry], text=text)

        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        person_entries = [e for e in mapping.entries if e.pii_type == "PERSON"]
        assert len(id_entries) == 1
        assert id_entries[0].original == "4412087"
        # Name not in text → no PERSON entry
        assert len(person_entries) == 0

    def test_no_cross_contamination_between_students(self):
        """No student's name leaks into another student's document."""
        students = [
            _entry(first="Alice", last="Anderson", student_id="A001", email="alice@u.edu"),
            _entry(first="Bob", last="Baker", student_id="B002", email="bob@u.edu"),
            _entry(first="Carol", last="Clark", student_id="C003", email="carol@u.edu"),
        ]
        # Document is only about Bob Baker
        text = "Author: Bob Baker (B002). Email: bob@u.edu.\nThis paper explores..."
        mapping = _mapping(students, text=text)

        originals = {e.original.lower() for e in mapping.entries}
        # Bob's data present
        assert any("baker" in o or "bob" in o for o in originals)
        assert "b002" in originals
        assert "bob@u.edu" in originals

        # Alice's and Carol's data absent
        assert not any("anderson" in o or "alice" in o for o in originals)
        assert not any("clark" in o or "carol" in o for o in originals)
        assert "a001" not in originals
        assert "c003" not in originals

    def test_mapping_table_entries_all_findable_in_text(self):
        """Every original in the mapping must be findable in the source text."""
        entries = [
            _entry(first="Jane", last="Smith", student_id="JS001",
                   email="jane@u.edu", also_remove="Acme Corp"),
        ]
        text = "Jane Smith (JS001, jane@u.edu) works at Acme Corp."
        mapping = _mapping(entries, text=text)
        text_lower = text.lower()
        for e in mapping.entries:
            assert e.original.lower() in text_lower, (
                f"Entry {e.original!r} not in document text"
            )
