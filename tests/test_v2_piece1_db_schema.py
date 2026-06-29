"""
V2 Piece 1 — DB Schema Migrations

Tests:
- rosters table created by init_db
- roster_entries table created by init_db
- jobs table gains a 'tier' column (default 'full')
- images table gains 'hash' and 'page_number' columns
- Schema migrations are idempotent (calling init_db twice doesn't crash)
- New CRUD helpers: create_roster, get_rosters, get_roster, delete_roster
- New CRUD helpers: add_roster_entries, get_roster_entries
- New CRUD helpers: set_job_tier, get_job_tier
- New CRUD helper: delete_mapping_entry
- Roster cascade: deleting a roster removes all its entries
- delete_mapping_entry removes only the specified placeholder
"""

import sqlite3
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestV2Schema:
    def test_rosters_table_exists(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='rosters'"
        )
        assert cur.fetchone() is not None, "rosters table not created"
        conn.close()

    def test_roster_entries_table_exists(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='roster_entries'"
        )
        assert cur.fetchone() is not None, "roster_entries table not created"
        conn.close()

    def test_rosters_table_columns(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(rosters)")}
        conn.close()
        assert "id" in cols
        assert "name" in cols
        assert "created_at" in cols
        assert "updated_at" in cols

    def test_roster_entries_table_columns(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(roster_entries)")}
        conn.close()
        assert "id" in cols
        assert "roster_id" in cols
        assert "first_name" in cols
        assert "last_name" in cols
        assert "preferred_name" in cols
        assert "student_id" in cols
        assert "email" in cols

    def test_jobs_table_has_tier_column(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        conn.close()
        assert "tier" in cols, "jobs table missing 'tier' column"

    def test_jobs_tier_default_is_full(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_job
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        job_id = create_job(conn, "test-job")
        row = conn.execute("SELECT tier FROM jobs WHERE id=?", (job_id,)).fetchone()
        conn.close()
        assert row["tier"] == "full"

    def test_images_table_has_hash_column(self, tmp_db_path):
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
        conn.close()
        assert "hash" in cols, "images table missing 'hash' column"

    def test_schema_migration_idempotent(self, tmp_db_path):
        """Calling init_db on an existing V1 DB must not raise."""
        from backend.db.database import init_db
        # Create a minimal V1-like DB first (no rosters, no tier column)
        conn = sqlite3.connect(tmp_db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS jobs "
            "(id TEXT PRIMARY KEY, name TEXT, status TEXT, created_at TEXT)"
        )
        conn.commit()
        conn.close()
        # Now run V2 init_db — must survive upgrading the existing schema
        init_db(tmp_db_path)
        conn2 = sqlite3.connect(tmp_db_path)
        cols = {row[1] for row in conn2.execute("PRAGMA table_info(jobs)")}
        conn2.close()
        assert "tier" in cols


# ---------------------------------------------------------------------------
# Roster CRUD
# ---------------------------------------------------------------------------

class TestRosterCRUD:
    def test_create_roster_returns_id(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_roster
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "ENGL101 Spring 2025")
        conn.close()
        assert isinstance(roster_id, str) and len(roster_id) > 0

    def test_get_rosters_returns_all(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_roster, get_rosters
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        create_roster(conn, "Roster A")
        create_roster(conn, "Roster B")
        rosters = get_rosters(conn)
        conn.close()
        names = [r["name"] for r in rosters]
        assert "Roster A" in names
        assert "Roster B" in names

    def test_get_roster_returns_single(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_roster, get_roster
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "My Roster")
        roster = get_roster(conn, roster_id)
        conn.close()
        assert roster is not None
        assert roster["name"] == "My Roster"

    def test_get_roster_missing_returns_none(self, tmp_db_path):
        from backend.db.database import init_db, get_db, get_roster
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        result = get_roster(conn, "nonexistent-id")
        conn.close()
        assert result is None

    def test_delete_roster_removes_record(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_roster, delete_roster, get_roster
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "Temp Roster")
        delete_roster(conn, roster_id)
        result = get_roster(conn, roster_id)
        conn.close()
        assert result is None

    def test_delete_roster_cascades_to_entries(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_roster, delete_roster,
            add_roster_entries, get_roster_entries,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "Roster With Entries")
        add_roster_entries(conn, roster_id, [
            {"first_name": "Alice", "last_name": "Smith",
             "preferred_name": None, "student_id": None, "email": None},
        ])
        delete_roster(conn, roster_id)
        entries = get_roster_entries(conn, roster_id)
        conn.close()
        assert entries == []


# ---------------------------------------------------------------------------
# Roster entries CRUD
# ---------------------------------------------------------------------------

class TestRosterEntriesCRUD:
    def test_add_roster_entries_stores_all(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_roster,
            add_roster_entries, get_roster_entries,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "Test Roster")
        entries = [
            {"first_name": "Jane", "last_name": "Smith",
             "preferred_name": "Janie", "student_id": "STU001", "email": "j@uni.edu"},
            {"first_name": "Bob", "last_name": "Jones",
             "preferred_name": None, "student_id": "STU002", "email": None},
        ]
        add_roster_entries(conn, roster_id, entries)
        stored = get_roster_entries(conn, roster_id)
        conn.close()
        assert len(stored) == 2

    def test_add_roster_entries_stores_fields(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_roster,
            add_roster_entries, get_roster_entries,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "Fields Test")
        add_roster_entries(conn, roster_id, [
            {"first_name": "Alice", "last_name": "Wonder",
             "preferred_name": "Ali", "student_id": "S99", "email": "a@test.com"},
        ])
        stored = get_roster_entries(conn, roster_id)
        conn.close()
        e = stored[0]
        assert e["first_name"] == "Alice"
        assert e["last_name"] == "Wonder"
        assert e["preferred_name"] == "Ali"
        assert e["student_id"] == "S99"
        assert e["email"] == "a@test.com"

    def test_get_roster_entries_empty_for_new_roster(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_roster, get_roster_entries
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        roster_id = create_roster(conn, "Empty Roster")
        entries = get_roster_entries(conn, roster_id)
        conn.close()
        assert entries == []

    def test_add_entries_does_not_bleed_across_rosters(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_roster,
            add_roster_entries, get_roster_entries,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        r1 = create_roster(conn, "R1")
        r2 = create_roster(conn, "R2")
        add_roster_entries(conn, r1, [
            {"first_name": "Alice", "last_name": "A",
             "preferred_name": None, "student_id": None, "email": None},
        ])
        add_roster_entries(conn, r2, [
            {"first_name": "Bob", "last_name": "B",
             "preferred_name": None, "student_id": None, "email": None},
        ])
        r2_entries = get_roster_entries(conn, r2)
        conn.close()
        names = [e["first_name"] for e in r2_entries]
        assert "Alice" not in names
        assert "Bob" in names


# ---------------------------------------------------------------------------
# Job tier helpers
# ---------------------------------------------------------------------------

class TestJobTierHelpers:
    def test_set_and_get_job_tier(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_job, set_job_tier, get_job_tier
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        job_id = create_job(conn, "test-job")
        set_job_tier(conn, job_id, "names")
        tier = get_job_tier(conn, job_id)
        conn.close()
        assert tier == "names"

    def test_get_job_tier_default_is_full(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_job, get_job_tier
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        job_id = create_job(conn, "default-tier-job")
        tier = get_job_tier(conn, job_id)
        conn.close()
        assert tier == "full"

    def test_set_job_tier_names_patterns(self, tmp_db_path):
        from backend.db.database import init_db, get_db, create_job, set_job_tier, get_job_tier
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        job_id = create_job(conn, "np-job")
        set_job_tier(conn, job_id, "names_patterns")
        assert get_job_tier(conn, job_id) == "names_patterns"
        conn.close()


# ---------------------------------------------------------------------------
# delete_mapping_entry
# ---------------------------------------------------------------------------

class TestDeleteMappingEntry:
    def test_delete_mapping_entry_removes_placeholder(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_job, save_mappings,
            get_mappings, delete_mapping_entry,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        job_id = create_job(conn, "del-test")
        save_mappings(conn, job_id, [
            {"original": "Jane Smith", "placeholder": "[PERSON_1]",
             "pii_type": "PERSON", "source": "llm"},
            {"original": "Acme Corp", "placeholder": "[ORG_1]",
             "pii_type": "ORG", "source": "llm"},
        ])
        delete_mapping_entry(conn, job_id, "[PERSON_1]")
        mappings = get_mappings(conn, job_id)
        conn.close()
        placeholders = [m["placeholder"] for m in mappings]
        assert "[PERSON_1]" not in placeholders
        assert "[ORG_1]" in placeholders

    def test_delete_nonexistent_placeholder_is_noop(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_job, save_mappings,
            get_mappings, delete_mapping_entry,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        job_id = create_job(conn, "noop-test")
        save_mappings(conn, job_id, [
            {"original": "Alice", "placeholder": "[PERSON_1]",
             "pii_type": "PERSON", "source": "llm"},
        ])
        delete_mapping_entry(conn, job_id, "[PERSON_99]")
        mappings = get_mappings(conn, job_id)
        conn.close()
        assert len(mappings) == 1

    def test_delete_entry_leaves_other_jobs_untouched(self, tmp_db_path):
        from backend.db.database import (
            init_db, get_db, create_job, save_mappings,
            get_mappings, delete_mapping_entry,
        )
        init_db(tmp_db_path)
        conn = get_db(tmp_db_path)
        j1 = create_job(conn, "job1")
        j2 = create_job(conn, "job2")
        save_mappings(conn, j1, [
            {"original": "Alice", "placeholder": "[PERSON_1]",
             "pii_type": "PERSON", "source": "llm"},
        ])
        save_mappings(conn, j2, [
            {"original": "Alice", "placeholder": "[PERSON_1]",
             "pii_type": "PERSON", "source": "llm"},
        ])
        delete_mapping_entry(conn, j1, "[PERSON_1]")
        j2_mappings = get_mappings(conn, j2)
        conn.close()
        assert len(j2_mappings) == 1
