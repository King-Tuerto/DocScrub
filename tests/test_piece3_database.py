"""
Piece 3 — SQLite Database Layer

Tests:
- DB schema created on startup
- Job CRUD (create, retrieve, list, delete)
- Mapping CRUD (save, retrieve by job, delete with job)
- Cascade delete: deleting a job removes its mappings and files
- DB file created at configured path if absent
- Invalid operations raise appropriate errors
"""

import sqlite3
from pathlib import Path

import pytest


class TestDatabaseInit:
    def test_init_creates_db_file(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        assert tmp_db_path.exists()

    def test_init_creates_jobs_table(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_init_creates_mappings_table(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='mappings'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_init_creates_files_table(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='files'"
        )
        assert cur.fetchone() is not None
        conn.close()

    def test_init_idempotent(self, tmp_db_path):
        """Calling init_db twice must not raise or corrupt the schema."""
        from backend.db.database import init_db
        init_db(tmp_db_path)
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert {"jobs", "mappings", "files"}.issubset(tables)
        conn.close()


@pytest.fixture
def db(tmp_db_path):
    from backend.db.database import init_db, get_db
    init_db(tmp_db_path)
    return get_db(tmp_db_path)


class TestJobCRUD:
    def test_create_job_returns_id(self, db):
        from backend.db.database import create_job
        job_id = create_job(db, name="test_job")
        assert job_id is not None
        assert isinstance(job_id, str)

    def test_create_job_stores_name(self, db):
        from backend.db.database import create_job, get_job
        job_id = create_job(db, name="my_job")
        job = get_job(db, job_id)
        assert job["name"] == "my_job"

    def test_create_job_sets_pending_status(self, db):
        from backend.db.database import create_job, get_job
        job_id = create_job(db, name="x")
        job = get_job(db, job_id)
        assert job["status"] == "pending"

    def test_create_job_sets_timestamp(self, db):
        from backend.db.database import create_job, get_job
        job_id = create_job(db, name="x")
        job = get_job(db, job_id)
        assert job["created_at"] is not None

    def test_get_job_nonexistent_returns_none(self, db):
        from backend.db.database import get_job
        result = get_job(db, "nonexistent-id")
        assert result is None

    def test_update_job_status(self, db):
        from backend.db.database import create_job, update_job_status, get_job
        job_id = create_job(db, name="x")
        update_job_status(db, job_id, "complete")
        job = get_job(db, job_id)
        assert job["status"] == "complete"

    def test_list_jobs_empty(self, db):
        from backend.db.database import list_jobs
        jobs = list_jobs(db)
        assert jobs == []

    def test_list_jobs_returns_all(self, db):
        from backend.db.database import create_job, list_jobs
        create_job(db, name="job_a")
        create_job(db, name="job_b")
        jobs = list_jobs(db)
        assert len(jobs) == 2

    def test_list_jobs_ordered_newest_first(self, db):
        import time
        from backend.db.database import create_job, list_jobs
        create_job(db, name="first")
        time.sleep(0.01)
        create_job(db, name="second")
        jobs = list_jobs(db)
        assert jobs[0]["name"] == "second"

    def test_delete_job(self, db):
        from backend.db.database import create_job, delete_job, get_job
        job_id = create_job(db, name="doomed")
        delete_job(db, job_id)
        assert get_job(db, job_id) is None

    def test_delete_nonexistent_job_does_not_raise(self, db):
        from backend.db.database import delete_job
        delete_job(db, "ghost-id")  # should be silent


class TestMappingCRUD:
    def test_save_mapping_entries(self, db):
        from backend.db.database import create_job, save_mappings, get_mappings
        job_id = create_job(db, name="x")
        entries = [
            {"original": "Jane Smith",      "placeholder": "[PERSON_1]", "pii_type": "PERSON"},
            {"original": "jane@acme.com",   "placeholder": "[EMAIL_1]",  "pii_type": "EMAIL"},
        ]
        save_mappings(db, job_id, entries)
        retrieved = get_mappings(db, job_id)
        assert len(retrieved) == 2

    def test_get_mappings_correct_values(self, db):
        from backend.db.database import create_job, save_mappings, get_mappings
        job_id = create_job(db, name="x")
        save_mappings(db, job_id, [
            {"original": "Jane Smith", "placeholder": "[PERSON_1]", "pii_type": "PERSON"},
        ])
        m = get_mappings(db, job_id)[0]
        assert m["original"] == "Jane Smith"
        assert m["placeholder"] == "[PERSON_1]"
        assert m["pii_type"] == "PERSON"

    def test_get_mappings_wrong_job_returns_empty(self, db):
        from backend.db.database import create_job, save_mappings, get_mappings
        job_id = create_job(db, name="x")
        save_mappings(db, job_id, [
            {"original": "Jane", "placeholder": "[PERSON_1]", "pii_type": "PERSON"},
        ])
        result = get_mappings(db, "other-job")
        assert result == []

    def test_save_mappings_overwrite_existing(self, db):
        """Saving mappings for an existing job should replace them, not append."""
        from backend.db.database import create_job, save_mappings, get_mappings
        job_id = create_job(db, name="x")
        save_mappings(db, job_id, [
            {"original": "Jane", "placeholder": "[PERSON_1]", "pii_type": "PERSON"},
        ])
        save_mappings(db, job_id, [
            {"original": "Bob", "placeholder": "[PERSON_1]", "pii_type": "PERSON"},
        ])
        result = get_mappings(db, job_id)
        assert len(result) == 1
        assert result[0]["original"] == "Bob"


class TestCascadeDelete:
    def test_delete_job_removes_its_mappings(self, db):
        from backend.db.database import create_job, save_mappings, delete_job, get_mappings
        job_id = create_job(db, name="x")
        save_mappings(db, job_id, [
            {"original": "Jane", "placeholder": "[PERSON_1]", "pii_type": "PERSON"},
        ])
        delete_job(db, job_id)
        assert get_mappings(db, job_id) == []

    def test_delete_job_removes_its_file_records(self, db):
        from backend.db.database import (
            create_job, save_file_record, delete_job, get_file_records
        )
        job_id = create_job(db, name="x")
        save_file_record(db, job_id, {
            "filename": "test.pdf",
            "file_type": "pdf",
            "size_bytes": 1024,
            "page_count": 2,
        })
        delete_job(db, job_id)
        assert get_file_records(db, job_id) == []


class TestFileRecordCRUD:
    def test_save_and_retrieve_file_record(self, db):
        from backend.db.database import create_job, save_file_record, get_file_records
        job_id = create_job(db, name="x")
        save_file_record(db, job_id, {
            "filename": "report.pdf",
            "file_type": "pdf",
            "size_bytes": 5120,
            "page_count": 10,
        })
        records = get_file_records(db, job_id)
        assert len(records) == 1
        assert records[0]["filename"] == "report.pdf"

    def test_multiple_files_in_one_job(self, db):
        from backend.db.database import create_job, save_file_record, get_file_records
        job_id = create_job(db, name="batch")
        for name in ("a.pdf", "b.docx", "c.pdf"):
            save_file_record(db, job_id, {
                "filename": name,
                "file_type": name.split(".")[-1],
                "size_bytes": 100,
                "page_count": 1,
            })
        assert len(get_file_records(db, job_id)) == 3
