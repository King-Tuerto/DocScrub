"""
Piece 8 — Routes & Anonymization Pipeline

Tests:
- POST /upload: accepts PDF, accepts DOCX, rejects other types, handles multi-file
- GET /jobs: lists jobs
- POST /jobs/{id}/anonymize: runs pipeline, returns anonymized text, emits SSE events
- GET /jobs/{id}/review: returns original + anonymized + mapping + positions
- GET /jobs/{id}/export: downloads anonymized file
- GET /jobs/{id}/export/zip: zip when multiple files
- GET /jobs/{id}/mapping: downloads mapping JSON
- POST /jobs/{id}/mapping: updates (edits) a mapping entry
- POST /reidentify: swaps placeholders back, returns restored file
- Pipeline steps: extract → LLM detect → regex detect → merge → map → replace → strip images → write output
- SSE progress events emitted per step
"""

import io
import json
import zipfile

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def uploaded_pdf_job(app_client, sample_pdf_path, mock_llm_endpoint):
    with open(sample_pdf_path, "rb") as f:
        resp = app_client.post(
            "/upload",
            files={"files": (sample_pdf_path.name, f, "application/pdf")},
        )
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture
def uploaded_docx_job(app_client, sample_docx_path, mock_llm_endpoint):
    with open(sample_docx_path, "rb") as f:
        resp = app_client.post(
            "/upload",
            files={"files": (sample_docx_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )
    assert resp.status_code == 200
    return resp.json()


# ---------------------------------------------------------------------------
# Upload endpoint
# ---------------------------------------------------------------------------

class TestUploadEndpoint:
    def test_upload_pdf_returns_200(self, app_client, sample_pdf_path):
        with open(sample_pdf_path, "rb") as f:
            resp = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, "application/pdf")},
            )
        assert resp.status_code == 200

    def test_upload_pdf_returns_job_id(self, app_client, sample_pdf_path):
        with open(sample_pdf_path, "rb") as f:
            resp = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, "application/pdf")},
            )
        data = resp.json()
        assert "job_id" in data

    def test_upload_docx_returns_200(self, app_client, sample_docx_path):
        with open(sample_docx_path, "rb") as f:
            resp = app_client.post(
                "/upload",
                files={"files": (sample_docx_path.name, f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            )
        assert resp.status_code == 200

    def test_upload_unsupported_type_returns_400(self, app_client, tmp_path):
        bad_file = tmp_path / "data.xlsx"
        bad_file.write_bytes(b"fake excel")
        with open(bad_file, "rb") as f:
            resp = app_client.post(
                "/upload",
                files={"files": ("data.xlsx", f, "application/vnd.ms-excel")},
            )
        assert resp.status_code == 400

    def test_upload_multiple_files_single_job(self, app_client, sample_pdf_path, sample_docx_path):
        with open(sample_pdf_path, "rb") as f1, open(sample_docx_path, "rb") as f2:
            resp = app_client.post(
                "/upload",
                files=[
                    ("files", (sample_pdf_path.name, f1, "application/pdf")),
                    ("files", (sample_docx_path.name, f2, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                ],
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data

    def test_upload_creates_job_in_db(self, app_client, sample_pdf_path):
        with open(sample_pdf_path, "rb") as f:
            resp = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, "application/pdf")},
            )
        job_id = resp.json()["job_id"]
        jobs_resp = app_client.get("/jobs")
        job_ids = [j["id"] for j in jobs_resp.json()]
        assert job_id in job_ids

    def test_upload_returns_file_list(self, app_client, sample_pdf_path):
        with open(sample_pdf_path, "rb") as f:
            resp = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, "application/pdf")},
            )
        data = resp.json()
        assert "files" in data
        assert len(data["files"]) == 1
        assert data["files"][0]["filename"] == sample_pdf_path.name

    def test_upload_no_file_returns_422(self, app_client):
        resp = app_client.post("/upload")
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Jobs listing
# ---------------------------------------------------------------------------

class TestJobsEndpoint:
    def test_list_jobs_empty(self, app_client):
        resp = app_client.get("/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_jobs_after_upload(self, app_client, sample_pdf_path):
        with open(sample_pdf_path, "rb") as f:
            app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, "application/pdf")},
            )
        resp = app_client.get("/jobs")
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Anonymize endpoint
# ---------------------------------------------------------------------------

class TestAnonymizeEndpoint:
    def test_anonymize_returns_200(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        resp = app_client.post(f"/jobs/{job_id}/anonymize")
        assert resp.status_code == 200

    def test_anonymize_returns_anonymized_text(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        resp = app_client.post(f"/jobs/{job_id}/anonymize")
        data = resp.json()
        assert "files" in data
        assert len(data["files"]) >= 1

    def test_anonymize_pii_not_in_output(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        from conftest import KNOWN_PII
        job_id = uploaded_pdf_job["job_id"]
        resp = app_client.post(f"/jobs/{job_id}/anonymize")
        data = resp.json()
        for file_result in data["files"]:
            anonymized = file_result.get("anonymized_text", "")
            assert KNOWN_PII["ssn"] not in anonymized, "SSN should be replaced"

    def test_anonymize_unknown_job_returns_404(self, app_client):
        resp = app_client.post("/jobs/nonexistent-id/anonymize")
        assert resp.status_code == 404

    def test_anonymize_updates_job_status_to_complete(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        jobs = app_client.get("/jobs").json()
        job = next(j for j in jobs if j["id"] == job_id)
        assert job["status"] == "complete"

    def test_anonymize_saves_mapping_to_db(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        mapping_resp = app_client.get(f"/jobs/{job_id}/mapping")
        assert mapping_resp.status_code == 200
        mapping = mapping_resp.json()
        assert len(mapping) > 0


# ---------------------------------------------------------------------------
# SSE progress events
# ---------------------------------------------------------------------------

class TestSSEProgressEvents:
    def test_sse_stream_emits_events(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        with app_client.stream("POST", f"/jobs/{job_id}/anonymize/stream") as resp:
            assert resp.status_code == 200
            content_type = resp.headers.get("content-type", "")
            assert "text/event-stream" in content_type

    def test_sse_emits_step_events(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        events = []
        with app_client.stream("POST", f"/jobs/{job_id}/anonymize/stream") as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:].strip()))
        steps = [e.get("step") for e in events if "step" in e]
        assert len(steps) >= 1


# ---------------------------------------------------------------------------
# Review endpoint
# ---------------------------------------------------------------------------

class TestReviewEndpoint:
    @pytest.fixture
    def anonymized_job(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        return job_id

    def test_review_returns_200(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/review")
        assert resp.status_code == 200

    def test_review_contains_original_text(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/review")
        data = resp.json()
        assert "files" in data
        for f in data["files"]:
            assert "original_text" in f

    def test_review_contains_anonymized_text(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/review")
        data = resp.json()
        for f in data["files"]:
            assert "anonymized_text" in f

    def test_review_contains_mapping(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/review")
        data = resp.json()
        assert "mapping" in data
        assert isinstance(data["mapping"], list)

    def test_review_contains_positions(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/review")
        data = resp.json()
        for f in data["files"]:
            assert "positions" in f

    def test_review_unknown_job_returns_404(self, app_client):
        resp = app_client.get("/jobs/ghost-id/review")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Mapping edit endpoint
# ---------------------------------------------------------------------------

class TestMappingEdit:
    @pytest.fixture
    def anonymized_job(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        return job_id

    def test_update_mapping_entry(self, app_client, anonymized_job):
        mapping = app_client.get(f"/jobs/{anonymized_job}/mapping").json()
        first = mapping[0]
        resp = app_client.patch(
            f"/jobs/{anonymized_job}/mapping/{first['placeholder']}",
            json={"original": "MANUALLY CORRECTED"},
        )
        assert resp.status_code == 200

    def test_updated_mapping_reflected_in_review(self, app_client, anonymized_job):
        mapping = app_client.get(f"/jobs/{anonymized_job}/mapping").json()
        placeholder = mapping[0]["placeholder"]
        app_client.patch(
            f"/jobs/{anonymized_job}/mapping/{placeholder}",
            json={"original": "CORRECTED VALUE"},
        )
        updated = app_client.get(f"/jobs/{anonymized_job}/mapping").json()
        entry = next((e for e in updated if e["placeholder"] == placeholder), None)
        assert entry is not None
        assert entry["original"] == "CORRECTED VALUE"


# ---------------------------------------------------------------------------
# Export endpoint
# ---------------------------------------------------------------------------

class TestExportEndpoint:
    @pytest.fixture
    def anonymized_job(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        return job_id

    def test_export_file_returns_200(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/export")
        assert resp.status_code == 200

    def test_single_file_export_not_zip(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/export")
        content_type = resp.headers.get("content-type", "")
        assert "zip" not in content_type

    def test_export_mapping_json(self, app_client, anonymized_job):
        resp = app_client.get(f"/jobs/{anonymized_job}/export/mapping")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("application/json")
        data = resp.json()
        assert isinstance(data, list)

    def test_multi_file_job_export_is_zip(self, app_client, sample_pdf_path, sample_docx_path, mock_llm_endpoint):
        with open(sample_pdf_path, "rb") as f1, open(sample_docx_path, "rb") as f2:
            upload_resp = app_client.post(
                "/upload",
                files=[
                    ("files", (sample_pdf_path.name, f1, "application/pdf")),
                    ("files", (sample_docx_path.name, f2, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
                ],
            )
        job_id = upload_resp.json()["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        resp = app_client.get(f"/jobs/{job_id}/export")
        assert resp.status_code == 200
        assert zipfile.is_zipfile(io.BytesIO(resp.content))

    def test_export_unknown_job_returns_404(self, app_client):
        resp = app_client.get("/jobs/ghost-id/export")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Re-identification endpoint
# ---------------------------------------------------------------------------

class TestReidentifyEndpoint:
    @pytest.fixture
    def exported_data(self, app_client, uploaded_pdf_job, mock_llm_endpoint):
        job_id = uploaded_pdf_job["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        mapping = app_client.get(f"/jobs/{job_id}/export/mapping").json()
        file_resp = app_client.get(f"/jobs/{job_id}/export")
        return {
            "job_id": job_id,
            "mapping": mapping,
            "file_bytes": file_resp.content,
            "filename": "sample_anonymized.pdf",
        }

    def test_reidentify_returns_200(self, app_client, exported_data):
        mapping_dict = {e["placeholder"]: e["original"] for e in exported_data["mapping"]}
        resp = app_client.post(
            "/reidentify",
            json={
                "job_id": exported_data["job_id"],
                "mapping": mapping_dict,
            },
        )
        assert resp.status_code == 200

    def test_reidentify_missing_mapping_returns_400(self, app_client):
        resp = app_client.post(
            "/reidentify",
            json={"job_id": "any", "mapping": {}},
        )
        assert resp.status_code == 400

    def test_reidentify_unknown_job_returns_404(self, app_client):
        resp = app_client.post(
            "/reidentify",
            json={"job_id": "ghost-id", "mapping": {"[PERSON_1]": "Jane"}},
        )
        assert resp.status_code == 404
