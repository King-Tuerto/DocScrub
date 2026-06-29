"""
SQLite database layer — thin wrapper around sqlite3.
All functions take a Connection as first argument.
No ORM; raw SQL.
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mappings (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL,
    original    TEXT NOT NULL,
    placeholder TEXT NOT NULL,
    pii_type    TEXT NOT NULL,
    source      TEXT,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS files (
    id         TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL,
    filename   TEXT NOT NULL,
    file_type  TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS images (
    id                 TEXT PRIMARY KEY,
    job_id             TEXT NOT NULL,
    source_filename    TEXT NOT NULL,
    page_number        INTEGER NOT NULL DEFAULT 1,
    image_index        INTEGER NOT NULL DEFAULT 0,
    marked_for_removal INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""

_DDL_V2 = """
CREATE TABLE IF NOT EXISTS rosters (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roster_entries (
    id             TEXT PRIMARY KEY,
    roster_id      TEXT NOT NULL,
    first_name     TEXT,
    last_name      TEXT,
    preferred_name TEXT,
    student_id     TEXT,
    email          TEXT,
    FOREIGN KEY (roster_id) REFERENCES rosters(id)
);
"""


# ---------------------------------------------------------------------------
# Init / connect
# ---------------------------------------------------------------------------

def _ensure_column(conn: sqlite3.Connection, table: str, column: str, col_def: str) -> None:
    """Add a column to a table if it doesn't already exist."""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def init_db(path: Path) -> None:
    """Create the database file and tables if they don't exist. Safe to call on existing DBs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_DDL)
    conn.executescript(_DDL_V2)
    # Migration: add new columns to existing tables (no-op if already present)
    _ensure_column(conn, "jobs", "tier", "TEXT NOT NULL DEFAULT 'full'")
    _ensure_column(conn, "images", "hash", "TEXT")
    _ensure_column(conn, "roster_entries", "student_id", "TEXT")
    _ensure_column(conn, "roster_entries", "also_remove", "TEXT")
    conn.commit()
    conn.close()


def get_db(path: Path) -> sqlite3.Connection:
    """Open and return a connection with dict-like row access."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# Job CRUD
# ---------------------------------------------------------------------------

def create_job(conn: sqlite3.Connection, name: str) -> str:
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO jobs (id, name, status, created_at) VALUES (?, ?, 'pending', ?)",
        (job_id, name, now),
    )
    conn.commit()
    return job_id


def get_job(conn: sqlite3.Connection, job_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row)


def update_job_status(conn: sqlite3.Connection, job_id: str, status: str) -> None:
    conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()


def list_jobs(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def delete_job(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute("DELETE FROM mappings WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM files WHERE job_id = ?", (job_id,))
    conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()


def set_job_tier(conn: sqlite3.Connection, job_id: str, tier: str) -> None:
    conn.execute("UPDATE jobs SET tier = ? WHERE id = ?", (tier, job_id))
    conn.commit()


def get_job_tier(conn: sqlite3.Connection, job_id: str) -> str:
    row = conn.execute("SELECT tier FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return "full"
    return row[0] or "full"


# ---------------------------------------------------------------------------
# Mapping CRUD
# ---------------------------------------------------------------------------

def save_mappings(conn: sqlite3.Connection, job_id: str, entries: List[dict]) -> None:
    """Replace all mappings for this job with the given entries."""
    conn.execute("DELETE FROM mappings WHERE job_id = ?", (job_id,))
    for entry in entries:
        conn.execute(
            "INSERT INTO mappings (id, job_id, original, placeholder, pii_type, source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                job_id,
                entry["original"],
                entry["placeholder"],
                entry["pii_type"],
                entry.get("source"),
            ),
        )
    conn.commit()


def get_mappings(conn: sqlite3.Connection, job_id: str) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM mappings WHERE job_id = ?", (job_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_mapping_entry(conn: sqlite3.Connection, job_id: str, placeholder: str) -> None:
    """Delete a single mapping entry by placeholder within a job."""
    conn.execute(
        "DELETE FROM mappings WHERE job_id = ? AND placeholder = ?",
        (job_id, placeholder),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# File record CRUD
# ---------------------------------------------------------------------------

def save_file_record(conn: sqlite3.Connection, job_id: str, record: dict) -> None:
    conn.execute(
        "INSERT INTO files (id, job_id, filename, file_type, size_bytes, page_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(uuid.uuid4()),
            job_id,
            record["filename"],
            record["file_type"],
            record["size_bytes"],
            record["page_count"],
        ),
    )
    conn.commit()


def get_file_records(conn: sqlite3.Connection, job_id: str) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM files WHERE job_id = ?", (job_id,)
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Image record CRUD
# ---------------------------------------------------------------------------

def upsert_image(
    conn: sqlite3.Connection,
    image_id: str,
    job_id: str,
    source_filename: str,
    page_number: int,
    image_index: int,
    marked_for_removal: bool = True,
    image_hash: Optional[str] = None,
) -> None:
    """Insert image record if not already present; preserve existing flags."""
    conn.execute(
        "INSERT OR IGNORE INTO images "
        "(id, job_id, source_filename, page_number, image_index, marked_for_removal, hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (image_id, job_id, source_filename, page_number, image_index,
         1 if marked_for_removal else 0, image_hash),
    )
    conn.commit()


def update_images_by_hash(
    conn: sqlite3.Connection,
    job_id: str,
    image_hash: str,
    marked_for_removal: bool,
) -> None:
    """Update marked_for_removal for all images in a job with a given hash."""
    conn.execute(
        "UPDATE images SET marked_for_removal = ? WHERE job_id = ? AND hash = ?",
        (1 if marked_for_removal else 0, job_id, image_hash),
    )
    conn.commit()


def get_images_for_job(conn: sqlite3.Connection, job_id: str) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM images WHERE job_id = ? ORDER BY source_filename, image_index",
        (job_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_image_flag(
    conn: sqlite3.Connection,
    image_id: str,
    marked_for_removal: bool,
) -> bool:
    """Update the marked_for_removal flag. Returns True if a row was updated."""
    cur = conn.execute(
        "UPDATE images SET marked_for_removal = ? WHERE id = ?",
        (1 if marked_for_removal else 0, image_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_image_by_id(conn: sqlite3.Connection, image_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM images WHERE id = ?", (image_id,)
    ).fetchone()
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Roster CRUD
# ---------------------------------------------------------------------------

def create_roster(conn: sqlite3.Connection, name: str) -> str:
    roster_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO rosters (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (roster_id, name, now, now),
    )
    conn.commit()
    return roster_id


def get_rosters(conn: sqlite3.Connection) -> List[dict]:
    rows = conn.execute("SELECT * FROM rosters ORDER BY created_at DESC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        count = conn.execute(
            "SELECT COUNT(*) FROM roster_entries WHERE roster_id = ?", (d["id"],)
        ).fetchone()[0]
        d["entry_count"] = count
        result.append(d)
    return result


def get_roster(conn: sqlite3.Connection, roster_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM rosters WHERE id = ?", (roster_id,)).fetchone()
    return _row_to_dict(row)


def delete_roster(conn: sqlite3.Connection, roster_id: str) -> None:
    conn.execute("DELETE FROM roster_entries WHERE roster_id = ?", (roster_id,))
    conn.execute("DELETE FROM rosters WHERE id = ?", (roster_id,))
    conn.commit()


def add_roster_entries(conn: sqlite3.Connection, roster_id: str, entries: List[dict]) -> None:
    for entry in entries:
        conn.execute(
            "INSERT INTO roster_entries "
            "(id, roster_id, first_name, last_name, preferred_name, student_id, email, also_remove) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                roster_id,
                entry.get("first_name"),
                entry.get("last_name"),
                entry.get("preferred_name"),
                entry.get("student_id"),
                entry.get("email"),
                entry.get("also_remove"),
            ),
        )
    conn.commit()


def get_roster_entries(conn: sqlite3.Connection, roster_id: str) -> List[dict]:
    rows = conn.execute(
        "SELECT * FROM roster_entries WHERE roster_id = ?", (roster_id,)
    ).fetchall()
    return [dict(r) for r in rows]
