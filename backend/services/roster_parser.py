"""
Roster parser — CSV and XLSX ingestion for the names-tier anonymizer.

parse_roster(data: bytes, filename: str) -> List[RosterEntry]

Supports flexible column naming (canonical, title case, joined, single 'name').
"""

import csv
import io
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class RosterEntry:
    first_name: Optional[str]
    last_name: Optional[str]
    preferred_name: Optional[str] = None
    student_id: Optional[str] = None
    email: Optional[str] = None


# ---------------------------------------------------------------------------
# Column name sets (all lowercase for comparison)
# ---------------------------------------------------------------------------

_FIRST_NAME_COLS = {
    "first_name", "firstname", "first name", "first",
    "given_name", "given name", "givenname",
}
_LAST_NAME_COLS = {
    "last_name", "lastname", "last name", "last",
    "surname", "family_name", "family name", "familyname",
}
_PREFERRED_NAME_COLS = {
    "preferred_name", "preferred name", "preferredname",
    "nickname", "nick name", "preferred", "goes by",
    "preferred first name", "preferred first",
}
_STUDENT_ID_COLS = {
    "student_id", "student id", "studentid",
    "student_number", "student number", "studentnumber",
    "id",
}
_EMAIL_COLS = {
    "email", "email address", "emailaddress", "e-mail", "e_mail",
}


def _norm(s: str) -> str:
    return s.strip().lower()


def _detect_columns(headers: List[str]) -> dict:
    """
    Map semantic field names to column indices.
    Raises ValueError if no recognisable name columns exist.
    """
    mapping: dict = {}
    for i, h in enumerate(headers):
        n = _norm(h)
        if n in _FIRST_NAME_COLS and "first_name" not in mapping:
            mapping["first_name"] = i
        elif n in _LAST_NAME_COLS and "last_name" not in mapping:
            mapping["last_name"] = i
        elif n == "name" and "name" not in mapping and "first_name" not in mapping:
            mapping["name"] = i
        elif n in _PREFERRED_NAME_COLS and "preferred_name" not in mapping:
            mapping["preferred_name"] = i
        elif n in _STUDENT_ID_COLS and "student_id" not in mapping:
            mapping["student_id"] = i
        elif n in _EMAIL_COLS and "email" not in mapping:
            mapping["email"] = i

    has_names = ("first_name" in mapping or "last_name" in mapping or "name" in mapping)
    if not has_names:
        raise ValueError(
            f"No name columns found in roster. Got headers: {headers}. "
            "Expected 'first_name'/'last_name', 'First Name'/'Last Name', or 'name'."
        )
    return mapping


def _get_cell(row: List[str], col_map: dict, key: str) -> Optional[str]:
    if key not in col_map:
        return None
    idx = col_map[key]
    if idx >= len(row):
        return None
    val = row[idx].strip() if row[idx] else ""
    return val if val else None


def _row_to_entry(row: List[str], col_map: dict) -> Optional["RosterEntry"]:
    # Single 'name' column: split on first whitespace
    if "name" in col_map and "first_name" not in col_map and "last_name" not in col_map:
        name_val = _get_cell(row, col_map, "name") or ""
        parts = name_val.split(None, 1)
        first = parts[0] if parts else ""
        last = parts[1] if len(parts) > 1 else ""
    else:
        first = _get_cell(row, col_map, "first_name") or ""
        last = _get_cell(row, col_map, "last_name") or ""

    if not first.strip() and not last.strip():
        return None  # blank row

    return RosterEntry(
        first_name=first.strip() or None,
        last_name=last.strip() or None,
        preferred_name=_get_cell(row, col_map, "preferred_name"),
        student_id=_get_cell(row, col_map, "student_id"),
        email=_get_cell(row, col_map, "email"),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_roster(data: bytes, filename: str) -> List[RosterEntry]:
    """
    Parse a CSV or XLSX roster file and return a deduplicated list of RosterEntry objects.

    Raises:
        ValueError: if the file extension is unsupported or no name columns are found.
    """
    fname = filename.lower()
    if fname.endswith(".csv"):
        return _parse_csv(data)
    elif fname.endswith(".xlsx"):
        return _parse_xlsx(data)
    else:
        raise ValueError(
            f"Unsupported roster file format: {filename!r}. Expected .csv or .xlsx"
        )


# ---------------------------------------------------------------------------
# CSV parser
# ---------------------------------------------------------------------------

def _parse_csv(data: bytes) -> List[RosterEntry]:
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return []
    headers = rows[0]
    col_map = _detect_columns(headers)

    entries: List[RosterEntry] = []
    seen: set = set()
    for row in rows[1:]:
        str_row = [cell if cell is not None else "" for cell in row]
        entry = _row_to_entry(str_row, col_map)
        if entry is None:
            continue
        key = (entry.first_name, entry.last_name)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries


# ---------------------------------------------------------------------------
# XLSX parser
# ---------------------------------------------------------------------------

def _parse_xlsx(data: bytes) -> List[RosterEntry]:
    try:
        import openpyxl
    except ImportError:
        raise ValueError(
            "openpyxl is required to parse Excel files. "
            "Install with: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []

    headers = [str(h).strip() if h is not None else "" for h in rows[0]]
    col_map = _detect_columns(headers)

    entries: List[RosterEntry] = []
    seen: set = set()
    for row in rows[1:]:
        str_row = [str(cell).strip() if cell is not None else "" for cell in row]
        entry = _row_to_entry(str_row, col_map)
        if entry is None:
            continue
        key = (entry.first_name, entry.last_name)
        if key in seen:
            continue
        seen.add(key)
        entries.append(entry)
    return entries
