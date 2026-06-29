"""
V2 Piece 7 — Mapping Delete

Tests:
- DELETE /jobs/{id}/mapping/{placeholder} returns 204
- Deleted entry is absent from subsequent GET /jobs/{id}/mapping
- Other entries remain after deletion
- Deleting non-existent placeholder returns 404
- Deleting from a non-existent job returns 404
- After deletion, anonymized text for that entry is reverted to original
- After deletion, anonymized text for OTHER entries is unchanged
- Review screen GET /jobs/{id}/review reflects the revert
- Revert does not double-replace: original text that also appears in another
  entry's text is not touched
- Delete is idempotent: calling twice returns 404 on second call
"""

import pytest
from conftest import KNOWN_PII


PDF_MIME = "application/pdf"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _setup_job_with_mapping(app_client, sample_pdf_path, mock_llm_endpoint):
    """Upload, anonymize, return (job_id, mapping)."""
    with open(sample_pdf_path, "rb") as f:
        job_id = app_client.post(
            "/upload",
            files={"files": (sample_pdf_path.name, f, PDF_MIME)},
        ).json()["job_id"]
    app_client.post(f"/jobs/{job_id}/anonymize")
    mapping = app_client.get(f"/jobs/{job_id}/mapping").json()
    return job_id, mapping


# ---------------------------------------------------------------------------
# DELETE endpoint — HTTP contract
# ---------------------------------------------------------------------------

class TestMappingDeleteHTTP:
    def test_delete_returns_204(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        if not mapping:
            pytest.skip("No mapping entries to delete")
        ph = mapping[0]["placeholder"]
        r = app_client.delete(f"/jobs/{job_id}/mapping/{ph}")
        assert r.status_code == 204

    def test_delete_missing_placeholder_returns_404(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, _ = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        r = app_client.delete(f"/jobs/{job_id}/mapping/[PERSON_99]")
        assert r.status_code == 404

    def test_delete_missing_job_returns_404(self, app_client):
        r = app_client.delete("/jobs/no-such-job/mapping/[PERSON_1]")
        assert r.status_code == 404

    def test_delete_idempotent_second_call_is_404(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        if not mapping:
            pytest.skip("No mapping entries to delete")
        ph = mapping[0]["placeholder"]
        app_client.delete(f"/jobs/{job_id}/mapping/{ph}")
        r2 = app_client.delete(f"/jobs/{job_id}/mapping/{ph}")
        assert r2.status_code == 404


# ---------------------------------------------------------------------------
# DELETE — effect on mapping list
# ---------------------------------------------------------------------------

class TestMappingDeleteEffect:
    def test_deleted_entry_absent_from_mapping(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        if not mapping:
            pytest.skip("No mapping entries")
        ph = mapping[0]["placeholder"]
        app_client.delete(f"/jobs/{job_id}/mapping/{ph}")
        updated = app_client.get(f"/jobs/{job_id}/mapping").json()
        phs = [e["placeholder"] for e in updated]
        assert ph not in phs

    def test_other_entries_remain_after_deletion(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        if len(mapping) < 2:
            pytest.skip("Need at least 2 mapping entries")
        ph_to_delete = mapping[0]["placeholder"]
        ph_to_keep = mapping[1]["placeholder"]
        app_client.delete(f"/jobs/{job_id}/mapping/{ph_to_delete}")
        updated = app_client.get(f"/jobs/{job_id}/mapping").json()
        phs = [e["placeholder"] for e in updated]
        assert ph_to_keep in phs


# ---------------------------------------------------------------------------
# DELETE — text revert
# ---------------------------------------------------------------------------

class TestMappingDeleteRevert:
    def test_deleted_placeholder_reverted_to_original_in_review(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        """After deleting PERSON_1, the original person name reappears in anonymized text."""
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        person_entry = next(
            (e for e in mapping if e["pii_type"] == "PERSON"), None
        )
        if person_entry is None:
            pytest.skip("No PERSON entry in mapping")
        ph = person_entry["placeholder"]
        original = person_entry["original"]

        app_client.delete(f"/jobs/{job_id}/mapping/{ph}")

        review = app_client.get(f"/jobs/{job_id}/review").json()
        anon_texts = " ".join(f["anonymized_text"] for f in review.get("files", []))
        assert original in anon_texts, (
            f"Expected original {original!r} to reappear after deleting {ph}"
        )

    def test_deleted_placeholder_absent_from_anonymized_text(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        if not mapping:
            pytest.skip("No mapping entries")
        ph = mapping[0]["placeholder"]
        app_client.delete(f"/jobs/{job_id}/mapping/{ph}")
        review = app_client.get(f"/jobs/{job_id}/review").json()
        anon_texts = " ".join(f["anonymized_text"] for f in review.get("files", []))
        assert ph not in anon_texts

    def test_remaining_placeholders_still_in_text_after_delete(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        if len(mapping) < 2:
            pytest.skip("Need at least 2 entries")
        ph_del = mapping[0]["placeholder"]
        ph_keep = mapping[1]["placeholder"]
        app_client.delete(f"/jobs/{job_id}/mapping/{ph_del}")
        review = app_client.get(f"/jobs/{job_id}/review").json()
        anon_texts = " ".join(f["anonymized_text"] for f in review.get("files", []))
        assert ph_keep in anon_texts

    def test_revert_does_not_affect_other_originals(
        self, app_client, sample_pdf_path, mock_llm_endpoint
    ):
        """Deleting PERSON_1 must not accidentally re-expose EMAIL_1's original."""
        job_id, mapping = _setup_job_with_mapping(
            app_client, sample_pdf_path, mock_llm_endpoint
        )
        person_entry = next((e for e in mapping if e["pii_type"] == "PERSON"), None)
        email_entry = next((e for e in mapping if e["pii_type"] == "EMAIL"), None)
        if person_entry is None or email_entry is None:
            pytest.skip("Need both PERSON and EMAIL entries")

        app_client.delete(f"/jobs/{job_id}/mapping/{person_entry['placeholder']}")
        review = app_client.get(f"/jobs/{job_id}/review").json()
        anon_texts = " ".join(f["anonymized_text"] for f in review.get("files", []))
        # Email original must still be anonymized
        assert email_entry["original"] not in anon_texts


# ---------------------------------------------------------------------------
# Unit: revert logic in replacer
# ---------------------------------------------------------------------------

class TestRevertLogicUnit:
    def test_revert_single_placeholder_in_text(self):
        """revert_placeholder(text, ph, original) replaces [PH] with original."""
        from backend.services.replacer import revert_placeholder
        text = "Hello [PERSON_1], your SSN is [SSN_1]."
        result = revert_placeholder(text, "[PERSON_1]", "Jane Smith")
        assert "Jane Smith" in result
        assert "[PERSON_1]" not in result
        assert "[SSN_1]" in result  # other placeholder untouched

    def test_revert_placeholder_all_occurrences(self):
        from backend.services.replacer import revert_placeholder
        text = "[PERSON_1] called. Please contact [PERSON_1] again."
        result = revert_placeholder(text, "[PERSON_1]", "Jane Smith")
        assert result.count("Jane Smith") == 2
        assert "[PERSON_1]" not in result

    def test_revert_placeholder_missing_is_noop(self):
        from backend.services.replacer import revert_placeholder
        text = "No placeholders here."
        result = revert_placeholder(text, "[PERSON_1]", "Jane Smith")
        assert result == text
