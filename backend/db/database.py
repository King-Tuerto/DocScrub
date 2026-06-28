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
"""


# ---------------------------------------------------------------------------
# Init / connect
# ---------------------------------------------------------------------------

def init_db(path: Path) -> None:
    """Create the database file and tables if they don't exist."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_DDL)
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
