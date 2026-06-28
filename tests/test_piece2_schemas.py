"""
Piece 2 — Pydantic Schemas

Tests:
- All schemas instantiate with valid data
- Validation rejects bad types / missing required fields
- Enum values for PII type are enforced
- Confidence values are constrained
- Placeholder format is correct
"""

import pytest
from datetime import datetime


class TestPIIFinding:
    def test_valid_finding(self):
        from backend.models.schemas import PIIFinding
        f = PIIFinding(text="Jane Smith", type="PERSON", confidence="high")
        assert f.text == "Jane Smith"
        assert f.type == "PERSON"
        assert f.confidence == "high"

    def test_valid_finding_medium_confidence(self):
        from backend.models.schemas import PIIFinding
        f = PIIFinding(text="ACCT-9988", type="ACCOUNT", confidence="medium")
        assert f.confidence == "medium"

    def test_invalid_type_raises(self):
        from backend.models.schemas import PIIFinding
        with pytest.raises(Exception):  # ValidationError
            PIIFinding(text="foo", type="UNICORN", confidence="high")

    def test_invalid_confidence_raises(self):
        from backend.models.schemas import PIIFinding
        with pytest.raises(Exception):
            PIIFinding(text="foo", type="PERSON", confidence="certain")

    def test_missing_text_raises(self):
        from backend.models.schemas import PIIFinding
        with pytest.raises(Exception):
            PIIFinding(type="PERSON", confidence="high")

    def test_all_allowed_types(self):
        from backend.models.schemas import PIIFinding, PIIType
        for pii_type in PIIType:
            f = PIIFinding(text="x", type=pii_type, confidence="high")
            assert f.type == pii_type

    def test_source_field_optional(self):
        """source tracks whether finding came from LLM, regex, or both."""
        from backend.models.schemas import PIIFinding
        f = PIIFinding(text="foo", type="PERSON", confidence="high", source="llm")
        assert f.source == "llm"

    def test_source_defaults_to_none(self):
        from backend.models.schemas import PIIFinding
        f = PIIFinding(text="foo", type="PERSON", confidence="high")
        assert f.source is None


class TestMappingEntry:
    def test_valid_entry(self):
        from backend.models.schemas import MappingEntry
        e = MappingEntry(
            original="Jane Smith",
            placeholder="[PERSON_1]",
            pii_type="PERSON",
        )
        assert e.original == "Jane Smith"
        assert e.placeholder == "[PERSON_1]"

    def test_placeholder_format_person(self):
        from backend.models.schemas import MappingEntry
        e = MappingEntry(original="x", placeholder="[PERSON_1]", pii_type="PERSON")
        assert e.placeholder.startswith("[PERSON_")
        assert e.placeholder.endswith("]")

    def test_placeholder_format_email(self):
        from backend.models.schemas import MappingEntry
        e = MappingEntry(original="a@b.com", placeholder="[EMAIL_1]", pii_type="EMAIL")
        assert e.placeholder == "[EMAIL_1]"

    def test_missing_original_raises(self):
        from backend.models.schemas import MappingEntry
        with pytest.raises(Exception):
            MappingEntry(placeholder="[PERSON_1]", pii_type="PERSON")

    def test_missing_placeholder_raises(self):
        from backend.models.schemas import MappingEntry
        with pytest.raises(Exception):
            MappingEntry(original="Jane", pii_type="PERSON")


class TestJob:
    def test_valid_job(self):
        from backend.models.schemas import Job
        j = Job(id="job-001", name="test_job")
        assert j.id == "job-001"
        assert j.name == "test_job"

    def test_job_has_timestamp(self):
        from backend.models.schemas import Job
        j = Job(id="job-001", name="test_job")
        assert j.created_at is not None
        assert isinstance(j.created_at, datetime)

    def test_job_status_defaults_pending(self):
        from backend.models.schemas import Job
        j = Job(id="job-001", name="test_job")
        assert j.status == "pending"

    def test_job_status_valid_values(self):
        from backend.models.schemas import Job
        for status in ("pending", "processing", "complete", "error"):
            j = Job(id="x", name="x", status=status)
            assert j.status == status

    def test_job_status_invalid_raises(self):
        from backend.models.schemas import Job
        with pytest.raises(Exception):
            Job(id="x", name="x", status="flying")

    def test_job_missing_id_raises(self):
        from backend.models.schemas import Job
        with pytest.raises(Exception):
            Job(name="test_job")


class TestFileRecord:
    def test_valid_pdf_record(self):
        from backend.models.schemas import FileRecord
        r = FileRecord(
            job_id="job-001",
            filename="sample.pdf",
            file_type="pdf",
            size_bytes=10240,
            page_count=5,
        )
        assert r.file_type == "pdf"
        assert r.page_count == 5

    def test_valid_docx_record(self):
        from backend.models.schemas import FileRecord
        r = FileRecord(
            job_id="job-001",
            filename="sample.docx",
            file_type="docx",
            size_bytes=2048,
            page_count=3,
        )
        assert r.file_type == "docx"

    def test_unsupported_file_type_raises(self):
        from backend.models.schemas import FileRecord
        with pytest.raises(Exception):
            FileRecord(
                job_id="job-001",
                filename="data.xlsx",
                file_type="xlsx",
                size_bytes=100,
                page_count=1,
            )

    def test_negative_size_raises(self):
        from backend.models.schemas import FileRecord
        with pytest.raises(Exception):
            FileRecord(
                job_id="job-001",
                filename="x.pdf",
                file_type="pdf",
                size_bytes=-1,
                page_count=1,
            )


class TestImageRecord:
    def test_valid_image_record(self):
        from backend.models.schemas import ImageRecord
        r = ImageRecord(
            job_id="job-001",
            source_filename="sample.pdf",
            page_number=1,
            image_index=0,
            marked_for_removal=True,
        )
        assert r.marked_for_removal is True

    def test_marked_for_removal_defaults_true(self):
        from backend.models.schemas import ImageRecord
        r = ImageRecord(
            job_id="job-001",
            source_filename="sample.pdf",
            page_number=1,
            image_index=0,
        )
        assert r.marked_for_removal is True

    def test_image_bytes_optional(self):
        from backend.models.schemas import ImageRecord
        r = ImageRecord(
            job_id="job-001",
            source_filename="sample.pdf",
            page_number=1,
            image_index=0,
            image_bytes=b"\x89PNG",
        )
        assert r.image_bytes == b"\x89PNG"


class TestExportManifest:
    def test_valid_manifest(self):
        from backend.models.schemas import ExportManifest
        m = ExportManifest(
            job_id="job-001",
            file_count=2,
            pii_items_found=14,
            model_used="llama3.1:8b",
        )
        assert m.file_count == 2
        assert m.pii_items_found == 14

    def test_manifest_has_timestamp(self):
        from backend.models.schemas import ExportManifest
        m = ExportManifest(
            job_id="job-001",
            file_count=1,
            pii_items_found=5,
            model_used="llama3.1:8b",
        )
        assert m.exported_at is not None


class TestReidentifyRequest:
    def test_valid_request(self):
        from backend.models.schemas import ReidentifyRequest
        r = ReidentifyRequest(
            job_id="job-001",
            mapping={"[PERSON_1]": "Jane Smith", "[EMAIL_1]": "jane@acme.com"},
        )
        assert r.job_id == "job-001"
        assert r.mapping["[PERSON_1]"] == "Jane Smith"

    def test_empty_mapping_raises(self):
        from backend.models.schemas import ReidentifyRequest
        with pytest.raises(Exception):
            ReidentifyRequest(job_id="job-001", mapping={})

    def test_missing_job_id_raises(self):
        from backend.models.schemas import ReidentifyRequest
        with pytest.raises(Exception):
            ReidentifyRequest(mapping={"[PERSON_1]": "Jane"})


class TestExtractedDocument:
    def test_valid_extracted_document(self):
        from backend.models.schemas import ExtractedDocument
        doc = ExtractedDocument(
            job_id="job-001",
            filename="sample.pdf",
            file_type="pdf",
            body_text="Hello world",
            header_text="My Header",
            footer_text="My Footer",
            page_count=1,
            is_scanned=False,
            is_password_protected=False,
        )
        assert doc.body_text == "Hello world"
        assert doc.is_scanned is False

    def test_scanned_flag_true(self):
        from backend.models.schemas import ExtractedDocument
        doc = ExtractedDocument(
            job_id="job-001",
            filename="scan.pdf",
            file_type="pdf",
            body_text="",
            page_count=2,
            is_scanned=True,
            is_password_protected=False,
        )
        assert doc.is_scanned is True
        assert doc.body_text == ""

    def test_table_cells_field(self):
        from backend.models.schemas import ExtractedDocument
        doc = ExtractedDocument(
            job_id="job-001",
            filename="sample.docx",
            file_type="docx",
            body_text="body",
            page_count=1,
            is_scanned=False,
            is_password_protected=False,
            table_cells=[["Name", "SSN"], ["Jane Smith", "123-45-6789"]],
        )
        assert len(doc.table_cells) == 2
