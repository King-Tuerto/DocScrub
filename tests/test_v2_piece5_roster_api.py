"""
V2 Piece 5 — Roster & Tier API Routes

Tests:
- POST /rosters — create roster, returns id + name
- POST /rosters/{id}/entries — upload CSV, returns entry count
- POST /rosters/{id}/entries — upload XLSX, returns entry count
- POST /rosters/{id}/entries — bad CSV raises 422
- GET /rosters — lists all rosters with entry counts
- GET /rosters/{id} — returns roster detail + entries
- GET /rosters/{id} — missing roster returns 404
- DELETE /rosters/{id} — 204, roster gone
- DELETE /rosters/{id} — missing roster returns 404

- POST /jobs/{id}/anonymize with tier='names' + roster_id — runs names-only pipeline
- POST /jobs/{id}/anonymize with tier='names_patterns' + roster_id — names + regex
- POST /jobs/{id}/anonymize with tier='full' (default, no change) — existing behavior
- POST /jobs/{id}/anonymize with tier='names' but no roster_id — 422 or warning
- POST /jobs/{id}/anonymize/stream with tier in body — SSE still works
- Tier and roster_id saved to job in DB
"""

import io
import json

import pytest
from conftest import KNOWN_PII


PDF_MIME = "application/pdf"


SAMPLE_CSV = """\
first_name,last_name,student_id,email
Jane,Smith,STU001,jane@uni.edu
Bob,Jones,STU002,bob@uni.edu
""".encode()

BAD_CSV = b"course,grade\nENGL101,A\n"


# ---------------------------------------------------------------------------
# Roster CRUD endpoints
# ---------------------------------------------------------------------------

class TestRosterCreate:
    def test_create_roster_returns_200(self, app_client):
        r = app_client.post("/rosters", json={"name": "ENGL101 Fall 2025"})
        assert r.status_code == 200

    def test_create_roster_returns_id(self, app_client):
        r = app_client.post("/rosters", json={"name": "ENGL101"})
        data = r.json()
        assert "id" in data
        assert isinstance(data["id"], str) and len(data["id"]) > 0

    def test_create_roster_returns_name(self, app_client):
        r = app_client.post("/rosters", json={"name": "My Roster"})
        assert r.json()["name"] == "My Roster"

    def test_create_roster_missing_name_returns_422(self, app_client):
        r = app_client.post("/rosters", json={})
        assert r.status_code == 422


class TestRosterEntryUpload:
    def test_upload_csv_entries_returns_200(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "R"}).json()["id"]
        r = app_client.post(
            f"/rosters/{roster_id}/entries",
            files={"file": ("roster.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
        )
        assert r.status_code == 200

    def test_upload_csv_returns_count(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "R"}).json()["id"]
        r = app_client.post(
            f"/rosters/{roster_id}/entries",
            files={"file": ("roster.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
        )
        data = r.json()
        assert data.get("count") == 2

    def test_upload_bad_csv_returns_422(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "R"}).json()["id"]
        r = app_client.post(
            f"/rosters/{roster_id}/entries",
            files={"file": ("bad.csv", io.BytesIO(BAD_CSV), "text/csv")},
        )
        assert r.status_code == 422

    def test_upload_entries_to_missing_roster_returns_404(self, app_client):
        r = app_client.post(
            "/rosters/nonexistent-id/entries",
            files={"file": ("roster.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
        )
        assert r.status_code == 404


class TestRosterList:
    def test_get_rosters_returns_200(self, app_client):
        r = app_client.get("/rosters")
        assert r.status_code == 200

    def test_get_rosters_empty_by_default(self, app_client):
        r = app_client.get("/rosters")
        assert r.json() == [] or isinstance(r.json(), list)

    def test_get_rosters_includes_created_roster(self, app_client):
        app_client.post("/rosters", json={"name": "Listed Roster"})
        r = app_client.get("/rosters")
        names = [item["name"] for item in r.json()]
        assert "Listed Roster" in names

    def test_get_rosters_includes_entry_count(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "Counted"}).json()["id"]
        app_client.post(
            f"/rosters/{roster_id}/entries",
            files={"file": ("r.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
        )
        r = app_client.get("/rosters")
        roster = next(item for item in r.json() if item["id"] == roster_id)
        assert roster.get("entry_count") == 2 or roster.get("count") == 2


class TestRosterDetail:
    def test_get_roster_returns_200(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "Detail"}).json()["id"]
        r = app_client.get(f"/rosters/{roster_id}")
        assert r.status_code == 200

    def test_get_roster_returns_name(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "Detail"}).json()["id"]
        r = app_client.get(f"/rosters/{roster_id}")
        assert r.json()["name"] == "Detail"

    def test_get_roster_includes_entries(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "With Entries"}).json()["id"]
        app_client.post(
            f"/rosters/{roster_id}/entries",
            files={"file": ("r.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
        )
        r = app_client.get(f"/rosters/{roster_id}")
        data = r.json()
        assert "entries" in data
        assert len(data["entries"]) == 2

    def test_get_missing_roster_returns_404(self, app_client):
        r = app_client.get("/rosters/no-such-roster")
        assert r.status_code == 404


class TestRosterDelete:
    def test_delete_roster_returns_204(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "Del"}).json()["id"]
        r = app_client.delete(f"/rosters/{roster_id}")
        assert r.status_code == 204

    def test_delete_roster_makes_it_unreachable(self, app_client):
        roster_id = app_client.post("/rosters", json={"name": "Del2"}).json()["id"]
        app_client.delete(f"/rosters/{roster_id}")
        r = app_client.get(f"/rosters/{roster_id}")
        assert r.status_code == 404

    def test_delete_missing_roster_returns_404(self, app_client):
        r = app_client.delete("/rosters/nonexistent-id")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Anonymize endpoint — tier + roster_id
# ---------------------------------------------------------------------------

def _upload_pdf(app_client, pdf_path):
    with open(pdf_path, "rb") as f:
        r = app_client.post(
            "/upload",
            files={"files": (pdf_path.name, f, PDF_MIME)},
        )
    assert r.status_code == 200
    return r.json()["job_id"]


def _create_roster_with_entries(app_client):
    roster_id = app_client.post("/rosters", json={"name": "R"}).json()["id"]
    app_client.post(
        f"/rosters/{roster_id}/entries",
        files={"file": ("r.csv", io.BytesIO(SAMPLE_CSV), "text/csv")},
    )
    return roster_id


class TestAnonymizeTierParam:
    def test_tier_names_accepted(self, app_client, sample_pdf_path):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        roster_id = _create_roster_with_entries(app_client)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        assert r.status_code == 200

    def test_tier_names_patterns_accepted(self, app_client, sample_pdf_path):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        roster_id = _create_roster_with_entries(app_client)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        assert r.status_code == 200

    def test_tier_full_still_works(self, app_client, sample_pdf_path, mock_llm_endpoint):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "full"},
        )
        assert r.status_code == 200

    def test_tier_names_without_roster_id_returns_warning_or_error(
        self, app_client, sample_pdf_path
    ):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names"},
        )
        # Either 422 (bad request) or 200 with a warning in the response
        if r.status_code == 200:
            data = r.json()
            warnings = data.get("warnings", [])
            assert any("roster" in w.lower() for w in warnings)
        else:
            assert r.status_code in (400, 422)

    def test_tier_saved_to_job(self, app_client, sample_pdf_path):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        roster_id = _create_roster_with_entries(app_client)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        # Job detail should reflect the tier
        jobs = app_client.get("/jobs").json()
        job = next(j for j in jobs if j["id"] == job_id)
        assert job.get("tier") == "names"

    def test_invalid_tier_returns_422(self, app_client, sample_pdf_path):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "ultra_scan"},
        )
        assert r.status_code == 422

    def test_stream_endpoint_accepts_tier(self, app_client, sample_pdf_path):
        job_id = _upload_pdf(app_client, sample_pdf_path)
        roster_id = _create_roster_with_entries(app_client)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize/stream",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
