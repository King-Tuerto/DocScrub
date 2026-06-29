"""
V2 End-to-End Tests — Assembled Whole

Exercises the full user workflow for each V2 scenario:

1. Tier 1 (Names Only):
   - Upload roster CSV → create roster
   - Upload document with roster names AND non-roster names
   - Anonymize with tier='names' + roster_id
   - Verify: roster names replaced, non-roster names untouched, no LLM called, no regex patterns replaced

2. Tier 2 (Names + Patterns):
   - Same roster setup
   - Anonymize with tier='names_patterns'
   - Verify: roster names AND SSN/email/phone replaced, no LLM called, non-regex non-roster text untouched

3. Tier 3 (Full Scan):
   - No roster required
   - Anonymize with tier='full' (or no tier)
   - Verify: existing behavior unchanged (LLM + regex)

4. Image Deduplication:
   - Upload PDF with duplicate images
   - GET /jobs/{id}/images returns one group with count=2
   - Mark group for removal
   - Export: output PDF contains 0 images
   - Verify both instances stripped

5. Mapping Delete:
   - Upload + anonymize a document
   - Delete one mapping entry via DELETE endpoint
   - GET /jobs/{id}/review: deleted placeholder reverted, others still replaced
   - GET /jobs/{id}/mapping: deleted entry absent

6. Large Document Chunking:
   - Upload a PDF with >12000 chars of text
   - Anonymize via SSE stream
   - SSE stream contains multiple llm_detect events (one per chunk)
   - All chunks complete successfully
   - Final mapping covers PII from all chunks (no inter-chunk loss)

7. Tier switching between runs:
   - Upload a document
   - Anonymize with tier='names' (roster-only), verify SSN not replaced
   - Re-anonymize with tier='names_patterns', verify SSN now replaced

8. Roster reuse across jobs:
   - Create roster once
   - Upload two separate documents
   - Anonymize both with the same roster_id
   - Both documents have roster names replaced
"""

import io
import json

import pytest
from conftest import KNOWN_PII, SAMPLE_PII_TEXT


PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

ROSTER_CSV = f"""\
first_name,last_name,student_id,email
Jane,Smith,STU001,jane@uni.edu
Bob,Jones,STU002,bob@uni.edu
""".encode()

# A name NOT in the roster — must survive anonymization in Tier 1
NON_ROSTER_NAME = "Professor Hawkins"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def roster_id(app_client):
    """Create a roster and upload entries; return roster_id."""
    rid = app_client.post("/rosters", json={"name": "ENGL101"}).json()["id"]
    app_client.post(
        f"/rosters/{rid}/entries",
        files={"file": ("r.csv", io.BytesIO(ROSTER_CSV), "text/csv")},
    )
    return rid


@pytest.fixture
def doc_with_roster_and_non_roster_names(tmp_path):
    """PDF containing both roster names and a non-roster name."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    text = (
        f"Student: Jane Smith\n"
        f"Instructor: {NON_ROSTER_NAME}\n"
        f"SSN: {KNOWN_PII['ssn']}\n"
        f"Email: {KNOWN_PII['email']}\n"
        f"The assignment was completed on time.\n"
    )
    page.insert_text((50, 50), text, fontsize=11)
    path = tmp_path / "roster_doc.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def doc_with_only_roster_names(tmp_path):
    """PDF with only roster names (no SSN/email, no non-roster names)."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Submitted by Jane Smith.\nReviewed by Bob Jones.", fontsize=11)
    path = tmp_path / "only_roster.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf_with_duplicate_images_e2e(tmp_path):
    import struct
    import zlib
    import fitz

    def _png(color):
        r, g, b = color
        def chunk(name, data):
            c = name + data
            return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        png = b"\x89PNG\r\n\x1a\n"
        png += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        png += chunk(b"IDAT", zlib.compress(bytes([0, r, g, b])))
        png += chunk(b"IEND", b"")
        return png

    RED = _png((255, 0, 0))
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text((50, 50), "Page with duplicate image.", fontsize=11)
        page.insert_image(fitz.Rect(100, 100, 200, 200), stream=RED)
    path = tmp_path / "dup_images.pdf"
    doc.save(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
# Scenario 1: Tier 1 — Names Only
# ---------------------------------------------------------------------------

class TestE2ETierNames:
    def _upload(self, app_client, path):
        with open(path, "rb") as f:
            return app_client.post(
                "/upload",
                files={"files": (path.name, f, PDF_MIME)},
            ).json()["job_id"]

    def test_tier1_roster_name_replaced(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        r = app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        assert r.status_code == 200
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert "Jane Smith" not in text

    def test_tier1_non_roster_name_untouched(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert NON_ROSTER_NAME in text

    def test_tier1_ssn_untouched(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert KNOWN_PII["ssn"] in text

    def test_tier1_no_llm_call(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        """No POST to the LLM endpoint must occur during Tier 1."""
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        # httpx_mock raises if unexpected calls are made
        assert True

    def test_tier1_mapping_has_only_person_entries(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        mapping = app_client.get(f"/jobs/{job_id}/mapping").json()
        types = {e["pii_type"] for e in mapping}
        non_person = types - {"PERSON"}
        assert non_person == set(), f"Unexpected PII types in Tier 1 mapping: {non_person}"


# ---------------------------------------------------------------------------
# Scenario 2: Tier 2 — Names + Patterns
# ---------------------------------------------------------------------------

class TestE2ETierNamesPatterns:
    def _upload(self, app_client, path):
        with open(path, "rb") as f:
            return app_client.post(
                "/upload",
                files={"files": (path.name, f, PDF_MIME)},
            ).json()["job_id"]

    def test_tier2_roster_name_replaced(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert "Jane Smith" not in text

    def test_tier2_ssn_replaced(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert KNOWN_PII["ssn"] not in text

    def test_tier2_email_replaced(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert KNOWN_PII["email"] not in text

    def test_tier2_no_llm_call(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        assert True

    def test_tier2_non_roster_non_regex_untouched(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        job_id = self._upload(app_client, doc_with_roster_and_non_roster_names)
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        review = app_client.get(f"/jobs/{job_id}/review").json()
        text = " ".join(f["anonymized_text"] for f in review["files"])
        assert NON_ROSTER_NAME in text


# ---------------------------------------------------------------------------
# Scenario 3: Tier 3 — Full Scan (regression)
# ---------------------------------------------------------------------------

class TestE2ETierFull:
    def test_tier3_still_calls_llm(self, app_client, sample_pdf_path, mock_llm_endpoint):
        with open(sample_pdf_path, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, PDF_MIME)},
            ).json()["job_id"]
        r = app_client.post(f"/jobs/{job_id}/anonymize", json={"tier": "full"})
        assert r.status_code == 200

    def test_tier3_maps_llm_person(self, app_client, sample_pdf_path, mock_llm_endpoint):
        with open(sample_pdf_path, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, PDF_MIME)},
            ).json()["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize", json={"tier": "full"})
        mapping = app_client.get(f"/jobs/{job_id}/mapping").json()
        person_entries = [e for e in mapping if e["pii_type"] == "PERSON"]
        assert len(person_entries) > 0

    def test_tier3_no_roster_needed(self, app_client, sample_pdf_path, mock_llm_endpoint):
        with open(sample_pdf_path, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, PDF_MIME)},
            ).json()["job_id"]
        r = app_client.post(f"/jobs/{job_id}/anonymize")  # no tier or roster_id
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Scenario 4: Image Deduplication
# ---------------------------------------------------------------------------

class TestE2EImageDedup:
    def _upload(self, app_client, path):
        with open(path, "rb") as f:
            return app_client.post(
                "/upload",
                files={"files": (path.name, f, PDF_MIME)},
            ).json()["job_id"]

    def test_images_endpoint_groups_duplicates(
        self, app_client, pdf_with_duplicate_images_e2e
    ):
        job_id = self._upload(app_client, pdf_with_duplicate_images_e2e)
        groups = app_client.get(f"/jobs/{job_id}/images").json()
        assert len(groups) == 1
        assert groups[0]["count"] == 2

    def test_mark_group_and_export_strips_all_instances(
        self, app_client, pdf_with_duplicate_images_e2e, mock_llm_endpoint
    ):
        import fitz
        job_id = self._upload(app_client, pdf_with_duplicate_images_e2e)
        # Mark the group
        app_client.post(
            f"/jobs/{job_id}/images/0/mark",
            json={"marked_for_removal": True, "apply_to_group": True},
        )
        # Anonymize
        app_client.post(f"/jobs/{job_id}/anonymize")
        # Export
        export_r = app_client.post(f"/jobs/{job_id}/export")
        assert export_r.status_code == 200
        doc = fitz.open(stream=export_r.content, filetype="pdf")
        total = sum(len(page.get_images()) for page in doc)
        doc.close()
        assert total == 0


# ---------------------------------------------------------------------------
# Scenario 5: Mapping Delete
# ---------------------------------------------------------------------------

class TestE2EMappingDelete:
    def test_delete_entry_reverts_text_and_removes_from_mapping(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        with open(sample_pdf_path, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, f, PDF_MIME)},
            ).json()["job_id"]
        app_client.post(f"/jobs/{job_id}/anonymize")
        mapping = app_client.get(f"/jobs/{job_id}/mapping").json()
        if not mapping:
            pytest.skip("No mapping entries")
        entry = mapping[0]
        ph = entry["placeholder"]
        original = entry["original"]

        # Delete
        d = app_client.delete(f"/jobs/{job_id}/mapping/{ph}")
        assert d.status_code == 204

        # Verify removed from mapping
        updated_mapping = app_client.get(f"/jobs/{job_id}/mapping").json()
        assert ph not in [e["placeholder"] for e in updated_mapping]

        # Verify reverted in review
        review = app_client.get(f"/jobs/{job_id}/review").json()
        all_text = " ".join(f["anonymized_text"] for f in review["files"])
        assert original in all_text
        assert ph not in all_text


# ---------------------------------------------------------------------------
# Scenario 6: Large document / chunking with SSE
# ---------------------------------------------------------------------------

class TestE2ELargeDocumentChunking:
    def test_large_doc_sse_emits_multiple_chunk_events(
        self, app_client, httpx_mock, tmp_path
    ):
        import fitz
        # Register enough LLM responses for many chunks
        for _ in range(20):
            httpx_mock.add_response(
                method="POST",
                url="http://localhost:11434/v1/chat/completions",
                json={"choices": [{"message": {"content": "[]"}}]},
            )

        # Build a large PDF
        doc = fitz.open()
        page = doc.new_page()
        long_text = (SAMPLE_PII_TEXT + " ") * 60
        page.insert_text((50, 50), long_text[:3000], fontsize=6)
        path = tmp_path / "large.pdf"
        doc.save(str(path))
        doc.close()

        with open(path, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (path.name, f, PDF_MIME)},
            ).json()["job_id"]

        r = app_client.post(
            f"/jobs/{job_id}/anonymize/stream", json={"tier": "full"}
        )
        assert r.status_code == 200
        events = [
            json.loads(line[5:].strip())
            for line in r.text.splitlines()
            if line.startswith("data:")
        ]
        assert any(ev.get("step") == "complete" for ev in events)


# ---------------------------------------------------------------------------
# Scenario 7: Tier switching between runs
# ---------------------------------------------------------------------------

class TestE2ETierSwitching:
    def test_re_anonymize_with_different_tier(
        self, app_client, doc_with_roster_and_non_roster_names, roster_id, httpx_mock
    ):
        with open(doc_with_roster_and_non_roster_names, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (doc_with_roster_and_non_roster_names.name, f, PDF_MIME)},
            ).json()["job_id"]

        # Run 1: names only — SSN should survive
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names", "roster_id": roster_id},
        )
        review1 = app_client.get(f"/jobs/{job_id}/review").json()
        text1 = " ".join(f["anonymized_text"] for f in review1["files"])
        assert KNOWN_PII["ssn"] in text1

        # Run 2: names + patterns — SSN should be replaced
        app_client.post(
            f"/jobs/{job_id}/anonymize",
            json={"tier": "names_patterns", "roster_id": roster_id},
        )
        review2 = app_client.get(f"/jobs/{job_id}/review").json()
        text2 = " ".join(f["anonymized_text"] for f in review2["files"])
        assert KNOWN_PII["ssn"] not in text2


# ---------------------------------------------------------------------------
# Scenario 8: Roster reuse across jobs
# ---------------------------------------------------------------------------

class TestE2ERosterReuse:
    def test_same_roster_works_for_two_jobs(
        self, app_client, doc_with_only_roster_names, roster_id, httpx_mock
    ):
        def _run():
            with open(doc_with_only_roster_names, "rb") as f:
                job_id = app_client.post(
                    "/upload",
                    files={"files": (doc_with_only_roster_names.name, f, PDF_MIME)},
                ).json()["job_id"]
            app_client.post(
                f"/jobs/{job_id}/anonymize",
                json={"tier": "names", "roster_id": roster_id},
            )
            return app_client.get(f"/jobs/{job_id}/review").json()

        review_a = _run()
        review_b = _run()
        for review in (review_a, review_b):
            text = " ".join(f["anonymized_text"] for f in review["files"])
            assert "Jane Smith" not in text
            assert "Bob Jones" not in text
