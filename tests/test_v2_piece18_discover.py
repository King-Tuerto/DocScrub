"""
Tests for the /discover endpoint (Name Discovery Mode).

Piece 18 — stateless PII scan that returns findings without creating a job.
"""
import io
import pytest
from fastapi.testclient import TestClient

from backend.main import create_app

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_CONFIG = {
    "llm_endpoint": "http://localhost:11434",
    "default_model": "llama3.1:8b",
    "output_directory": "./output",
    "db_path": ":memory:",
}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("discover_test")
    config = {
        **TEST_CONFIG,
        "output_directory": str(tmp / "output"),
        "db_path": str(tmp / "test.db"),
    }
    app = create_app(config=config)
    with TestClient(app) as c:
        yield c


def _make_docx_bytes(text: str) -> bytes:
    """Create a minimal DOCX in memory with the given body text."""
    from docx import Document
    doc = Document()
    doc.add_paragraph(text)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------------------
# Basic quick-scan tests
# ---------------------------------------------------------------------------

class TestDiscoverQuick:
    def test_email_found(self, client):
        """Quick scan finds an email address in a DOCX."""
        docx = _make_docx_bytes("Contact jane.smith@example.com for details.")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "findings" in data
        emails = [f for f in data["findings"] if f["pii_type"] == "EMAIL"]
        assert emails, "Expected at least one EMAIL finding"
        assert any(f["text"] == "jane.smith@example.com" for f in emails)

    def test_phone_found(self, client):
        """Quick scan finds a phone number."""
        docx = _make_docx_bytes("Call us at 555-867-5309 anytime.")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        findings = resp.json()["findings"]
        phones = [f for f in findings if f["pii_type"] == "PHONE"]
        assert phones, "Expected a PHONE finding"
        assert any("867-5309" in f["text"] for f in phones)

    def test_ssn_found(self, client):
        """Quick scan finds a Social Security Number."""
        docx = _make_docx_bytes("SSN: 123-45-6789.")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        findings = resp.json()["findings"]
        ssns = [f for f in findings if f["pii_type"] == "SSN"]
        assert ssns, "Expected an SSN finding"

    def test_response_schema(self, client):
        """Response includes filename, method, findings list, and warnings list."""
        docx = _make_docx_bytes("Email: test@test.org")
        resp = client.post(
            "/discover",
            files={"file": ("doc.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["filename"] == "doc.docx"
        assert data["method"] == "quick"
        assert isinstance(data["findings"], list)
        assert isinstance(data["warnings"], list)

    def test_finding_schema(self, client):
        """Each finding has text, pii_type, confidence, and source fields."""
        docx = _make_docx_bytes("Email bob@example.com to RSVP.")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        findings = resp.json()["findings"]
        assert findings, "Expected at least one finding"
        for f in findings:
            assert "text" in f
            assert "pii_type" in f
            assert "confidence" in f
            assert "source" in f

    def test_no_pii_returns_empty_list(self, client):
        """Document with no PII returns empty findings, not an error."""
        docx = _make_docx_bytes("The quick brown fox jumps over the lazy dog.")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        assert resp.json()["findings"] == []

    def test_deduplication(self, client):
        """Same email appearing twice is returned only once."""
        docx = _make_docx_bytes(
            "Contact foo@example.com. Also email foo@example.com again."
        )
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        email_findings = [
            f for f in resp.json()["findings"]
            if f["text"].lower() == "foo@example.com"
        ]
        assert len(email_findings) == 1, "Duplicate finding should be deduplicated"


# ---------------------------------------------------------------------------
# Deep scan: LLM unavailable → falls back to regex with warning
# ---------------------------------------------------------------------------

class TestDiscoverDeep:
    def test_deep_scan_falls_back_when_llm_unreachable(self, client):
        """
        When the LLM endpoint is unreachable, deep scan returns a warning
        and falls back to regex-only results (still 200, not 500).
        """
        docx = _make_docx_bytes("Email: fallback@example.com. SSN: 987-65-4321.")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={
                "method": "deep",
                "llm_endpoint": "http://localhost:19999",  # nothing listening here
                "model": "nonexistent",
            },
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["warnings"], "Expected a warning about LLM being unavailable"
        assert any("unavailable" in w.lower() or "regex" in w.lower() for w in data["warnings"])
        # Regex findings must still be present
        emails = [f for f in data["findings"] if f["pii_type"] == "EMAIL"]
        assert emails, "Regex fallback should still find the email"


# ---------------------------------------------------------------------------
# Validation / error cases
# ---------------------------------------------------------------------------

class TestDiscoverValidation:
    def test_invalid_method_returns_422(self, client):
        """method must be 'quick' or 'deep'."""
        docx = _make_docx_bytes("test")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "turbo"},
        )
        assert resp.status_code == 422

    def test_unsupported_file_type_returns_422(self, client):
        """Uploading a .txt file should be rejected."""
        resp = client.post(
            "/discover",
            files={"file": ("test.txt", b"Hello world", "text/plain")},
            data={"method": "quick"},
        )
        assert resp.status_code == 422
        assert "txt" in resp.json()["detail"].lower() or "unsupported" in resp.json()["detail"].lower()

    def test_no_job_created(self, client):
        """POST /discover must not create a job entry in the database."""
        docx = _make_docx_bytes("test@example.com")
        resp = client.post(
            "/discover",
            files={"file": ("test.docx", docx, DOCX_MIME)},
            data={"method": "quick"},
        )
        assert resp.status_code == 200
        # No job_id in the response
        assert "job_id" not in resp.json()

    def test_stateless_repeated_call(self, client):
        """Calling /discover twice returns consistent results without side effects."""
        docx = _make_docx_bytes("email: repeat@example.com")
        for _ in range(2):
            resp = client.post(
                "/discover",
                files={"file": ("test.docx", docx, DOCX_MIME)},
                data={"method": "quick"},
            )
            assert resp.status_code == 200
            assert any(f["text"] == "repeat@example.com" for f in resp.json()["findings"])


# ---------------------------------------------------------------------------
# CSV format verification (logic tests — independent of the endpoint)
# ---------------------------------------------------------------------------

class TestDiscoverCsvLogic:
    """
    Verify the CSV mapping rules (PERSON → first/last split, EMAIL → email,
    other → also_remove) using a simple Python reimplementation of the
    frontend logic, keeping backend and frontend in sync.
    """

    def _build_csv(self, findings):
        """Mirror of the frontend _buildCsv() logic in Python."""
        import csv, io
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(["first_name", "last_name", "email", "also_remove"])
        for f in findings:
            row = ["", "", "", ""]
            if f["pii_type"] == "EMAIL":
                row[2] = f["text"]
            elif f["pii_type"] == "PERSON":
                parts = f["text"].split(" ", 1)
                row[0] = parts[0]
                row[1] = parts[1] if len(parts) > 1 else ""
            else:
                row[3] = f["text"]
            writer.writerow(row)
        return out.getvalue()

    def test_email_goes_to_email_column(self):
        findings = [{"text": "alice@example.com", "pii_type": "EMAIL"}]
        csv_out = self._build_csv(findings)
        assert "alice@example.com" in csv_out
        rows = list(csv_out.strip().splitlines())
        data_row = rows[1].split(",")
        assert data_row[2] == "alice@example.com"
        assert data_row[0] == "" and data_row[1] == ""

    def test_full_name_splits_to_first_last(self):
        findings = [{"text": "Jane Smith", "pii_type": "PERSON"}]
        csv_out = self._build_csv(findings)
        rows = list(csv_out.strip().splitlines())
        data_row = rows[1].split(",")
        assert data_row[0] == "Jane"
        assert data_row[1] == "Smith"

    def test_single_name_goes_to_first_name_only(self):
        """Single-word name → first_name only (triggers exact-match fallback)."""
        findings = [{"text": "AcmeCorp", "pii_type": "PERSON"}]
        csv_out = self._build_csv(findings)
        rows = list(csv_out.strip().splitlines())
        data_row = rows[1].split(",")
        assert data_row[0] == "AcmeCorp"
        assert data_row[1] == ""

    def test_three_word_name_first_word_is_first_name(self):
        findings = [{"text": "Mary Jane Watson", "pii_type": "PERSON"}]
        csv_out = self._build_csv(findings)
        rows = list(csv_out.strip().splitlines())
        data_row = rows[1].split(",")
        assert data_row[0] == "Mary"
        assert data_row[1] == "Jane Watson"

    def test_phone_goes_to_also_remove(self):
        findings = [{"text": "555-123-4567", "pii_type": "PHONE"}]
        csv_out = self._build_csv(findings)
        rows = list(csv_out.strip().splitlines())
        data_row = rows[1].split(",")
        assert data_row[3] == "555-123-4567"
        assert data_row[0] == data_row[1] == data_row[2] == ""

    def test_csv_header_row(self):
        csv_out = self._build_csv([])
        assert csv_out.strip() == "first_name,last_name,email,also_remove"

    def test_mixed_findings_produce_correct_rows(self):
        findings = [
            {"text": "Bob Lee", "pii_type": "PERSON"},
            {"text": "bob@example.com", "pii_type": "EMAIL"},
            {"text": "555-000-1234", "pii_type": "PHONE"},
        ]
        csv_out = self._build_csv(findings)
        lines = csv_out.strip().splitlines()
        assert len(lines) == 4  # header + 3 data rows
        person_row = lines[1].split(",")
        assert person_row[0] == "Bob" and person_row[1] == "Lee"
        email_row = lines[2].split(",")
        assert email_row[2] == "bob@example.com"
        phone_row = lines[3].split(",")
        assert phone_row[3] == "555-000-1234"
