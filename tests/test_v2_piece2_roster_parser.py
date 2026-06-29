"""
V2 Piece 2 — Roster Parser

Tests:
- CSV with canonical columns (first_name, last_name) parsed correctly
- CSV with alternative column names (First Name, LastName, firstname etc.)
- CSV with a single 'name' column — split on space or comma
- Excel (.xlsx) parsed the same as CSV
- preferred_name / nickname column captured when present
- student_id and email columns captured when present
- Rows where both first_name and last_name are blank are skipped
- Leading/trailing whitespace stripped from every field
- Duplicate rows deduplicated
- File with only a header row → empty list (no crash)
- Missing column raises a clear ValueError (not a cryptic KeyError)
- RosterEntry dataclass has the expected fields
"""

import io

import pytest


# ---------------------------------------------------------------------------
# Fixtures — in-memory CSV and Excel bytes
# ---------------------------------------------------------------------------

CANONICAL_CSV = """\
first_name,last_name,preferred_name,student_id,email
Jane,Smith,Janie,STU001,jane@uni.edu
Bob,Jones,,STU002,bob@uni.edu
Alice,Wonder,Ali,STU003,
"""

ALT_HEADERS_CSV = """\
First Name,Last Name,Preferred Name,Student ID,Email
Jane,Smith,Janie,STU001,jane@uni.edu
Bob,Jones,,STU002,
"""

SINGLE_NAME_COL_CSV = """\
name,student_id
Jane Smith,STU001
Jones Bob,STU002
"""

BLANK_ROWS_CSV = """\
first_name,last_name,student_id
Jane,Smith,STU001
,,STU999
Bob,Jones,STU002
"""

WHITESPACE_CSV = """\
first_name,last_name
  Jane  ,  Smith
  Bob  ,  Jones
"""

DUPLICATE_ROWS_CSV = """\
first_name,last_name
Jane,Smith
Jane,Smith
Bob,Jones
"""

HEADER_ONLY_CSV = "first_name,last_name,student_id\n"

NO_NAME_COLUMNS_CSV = """\
course,grade
ENGL101,A
MATH201,B
"""


@pytest.fixture
def canonical_csv_bytes():
    return CANONICAL_CSV.encode()


@pytest.fixture
def alt_headers_csv_bytes():
    return ALT_HEADERS_CSV.encode()


@pytest.fixture
def single_name_col_csv_bytes():
    return SINGLE_NAME_COL_CSV.encode()


@pytest.fixture
def blank_rows_csv_bytes():
    return BLANK_ROWS_CSV.encode()


@pytest.fixture
def whitespace_csv_bytes():
    return WHITESPACE_CSV.encode()


@pytest.fixture
def duplicate_rows_csv_bytes():
    return DUPLICATE_ROWS_CSV.encode()


@pytest.fixture
def header_only_csv_bytes():
    return HEADER_ONLY_CSV.encode()


@pytest.fixture
def no_name_columns_csv_bytes():
    return NO_NAME_COLUMNS_CSV.encode()


@pytest.fixture
def canonical_xlsx_bytes():
    """Build an Excel file with canonical columns using openpyxl."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["first_name", "last_name", "preferred_name", "student_id", "email"])
    ws.append(["Jane", "Smith", "Janie", "STU001", "jane@uni.edu"])
    ws.append(["Bob", "Jones", None, "STU002", None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def no_name_columns_xlsx_bytes():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["course", "grade"])
    ws.append(["ENGL101", "A"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# RosterEntry dataclass
# ---------------------------------------------------------------------------

class TestRosterEntryModel:
    def test_roster_entry_has_required_fields(self):
        from backend.services.roster_parser import RosterEntry
        e = RosterEntry(
            first_name="Jane",
            last_name="Smith",
            preferred_name=None,
            student_id=None,
            email=None,
        )
        assert e.first_name == "Jane"
        assert e.last_name == "Smith"
        assert e.preferred_name is None

    def test_roster_entry_all_optional_fields(self):
        from backend.services.roster_parser import RosterEntry
        e = RosterEntry(
            first_name="Bob",
            last_name="Jones",
            preferred_name="Bobby",
            student_id="STU99",
            email="b@uni.edu",
        )
        assert e.preferred_name == "Bobby"
        assert e.student_id == "STU99"
        assert e.email == "b@uni.edu"


# ---------------------------------------------------------------------------
# CSV parsing — happy path
# ---------------------------------------------------------------------------

class TestCSVParsingHappyPath:
    def test_canonical_csv_returns_correct_count(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        assert len(entries) == 3

    def test_canonical_csv_first_entry_first_name(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        assert entries[0].first_name == "Jane"

    def test_canonical_csv_first_entry_last_name(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        assert entries[0].last_name == "Smith"

    def test_canonical_csv_preferred_name_captured(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        assert entries[0].preferred_name == "Janie"

    def test_canonical_csv_student_id_captured(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        assert entries[0].student_id == "STU001"

    def test_canonical_csv_email_captured(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        assert entries[0].email == "jane@uni.edu"

    def test_canonical_csv_missing_optional_is_none(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_csv_bytes, filename="roster.csv")
        # Bob Jones has no preferred_name
        bob = next(e for e in entries if e.first_name == "Bob")
        assert bob.preferred_name is None


# ---------------------------------------------------------------------------
# CSV parsing — alternative headers
# ---------------------------------------------------------------------------

class TestCSVAlternativeHeaders:
    def test_title_case_headers_accepted(self, alt_headers_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(alt_headers_csv_bytes, filename="roster.csv")
        assert len(entries) == 2
        assert entries[0].first_name == "Jane"

    def test_single_name_column_split_correctly(self, single_name_col_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(single_name_col_csv_bytes, filename="roster.csv")
        assert len(entries) == 2
        # "Jane Smith" → first="Jane", last="Smith"
        jane = next(e for e in entries if "Jane" in (e.first_name or ""))
        assert jane.last_name == "Smith"

    def test_single_name_column_reversed_format(self, single_name_col_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(single_name_col_csv_bytes, filename="roster.csv")
        # "Jones Bob" — could be "Last First" — parser should handle both orders
        # At minimum: must not crash and must produce 2 entries
        assert len(entries) == 2


# ---------------------------------------------------------------------------
# CSV edge cases
# ---------------------------------------------------------------------------

class TestCSVEdgeCases:
    def test_blank_rows_skipped(self, blank_rows_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(blank_rows_csv_bytes, filename="roster.csv")
        # Row with empty first AND last name must be skipped
        assert len(entries) == 2
        names = {(e.first_name, e.last_name) for e in entries}
        assert ("", "") not in names

    def test_whitespace_stripped(self, whitespace_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(whitespace_csv_bytes, filename="roster.csv")
        assert entries[0].first_name == "Jane"
        assert entries[0].last_name == "Smith"

    def test_duplicates_deduplicated(self, duplicate_rows_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(duplicate_rows_csv_bytes, filename="roster.csv")
        # Jane Smith appears twice — should appear once
        janes = [e for e in entries if e.first_name == "Jane" and e.last_name == "Smith"]
        assert len(janes) == 1

    def test_header_only_csv_returns_empty_list(self, header_only_csv_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(header_only_csv_bytes, filename="roster.csv")
        assert entries == []

    def test_no_name_columns_raises_value_error(self, no_name_columns_csv_bytes):
        from backend.services.roster_parser import parse_roster
        with pytest.raises(ValueError, match=r"(?i)name|column"):
            parse_roster(no_name_columns_csv_bytes, filename="roster.csv")


# ---------------------------------------------------------------------------
# Excel parsing
# ---------------------------------------------------------------------------

class TestExcelParsing:
    def test_xlsx_returns_correct_count(self, canonical_xlsx_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_xlsx_bytes, filename="roster.xlsx")
        assert len(entries) == 2

    def test_xlsx_first_name_parsed(self, canonical_xlsx_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_xlsx_bytes, filename="roster.xlsx")
        assert entries[0].first_name == "Jane"

    def test_xlsx_preferred_name_parsed(self, canonical_xlsx_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_xlsx_bytes, filename="roster.xlsx")
        assert entries[0].preferred_name == "Janie"

    def test_xlsx_none_cells_become_none(self, canonical_xlsx_bytes):
        from backend.services.roster_parser import parse_roster
        entries = parse_roster(canonical_xlsx_bytes, filename="roster.xlsx")
        bob = next(e for e in entries if e.first_name == "Bob")
        assert bob.preferred_name is None

    def test_xlsx_no_name_columns_raises_value_error(self, no_name_columns_xlsx_bytes):
        from backend.services.roster_parser import parse_roster
        with pytest.raises(ValueError, match=r"(?i)name|column"):
            parse_roster(no_name_columns_xlsx_bytes, filename="roster.xlsx")

    def test_unknown_extension_raises_value_error(self, canonical_csv_bytes):
        from backend.services.roster_parser import parse_roster
        with pytest.raises(ValueError, match=r"(?i)format|extension|unsupported"):
            parse_roster(canonical_csv_bytes, filename="roster.txt")
