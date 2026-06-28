"""
Piece 4 — File Layer (Text Extraction + Image Extraction)

Tests:
- PDF: text extracted page-by-page
- PDF: headers/footers returned as separate fields
- PDF: scanned PDF (no text) → is_scanned=True, body_text empty
- PDF: password-protected → is_password_protected=True, body skipped
- PDF: images extracted with page number
- DOCX: body text extracted
- DOCX: table cell text preserved
- DOCX: header/footer extracted separately
- DOCX: images extracted with position metadata
- Both: ExtractedDocument structure normalised regardless of input format
- Both: PII in table cells is reachable (not lost)
- image_extractor returns ImageRecord list with bytes + metadata
"""

import pytest
from conftest import KNOWN_PII, SAMPLE_PII_TEXT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def assert_contains_pii(text: str):
    """Assert that the extracted text contains at least one known PII value."""
    found = any(v in text for v in KNOWN_PII.values())
    assert found, f"Expected at least one PII value in extracted text. Got:\n{text[:500]}"


# ---------------------------------------------------------------------------
# PDF extraction
# ---------------------------------------------------------------------------

class TestPDFExtraction:
    def test_extracts_body_text(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(sample_pdf_path)
        assert KNOWN_PII["person"] in result.body_text

    def test_returns_extracted_document_type(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        from backend.models.schemas import ExtractedDocument
        result = extract_pdf(sample_pdf_path)
        assert isinstance(result, ExtractedDocument)

    def test_file_type_is_pdf(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(sample_pdf_path)
        assert result.file_type == "pdf"

    def test_page_count_correct(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(sample_pdf_path)
        assert result.page_count >= 1

    def test_is_scanned_false_for_text_pdf(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(sample_pdf_path)
        assert result.is_scanned is False

    def test_is_password_protected_false_for_normal_pdf(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(sample_pdf_path)
        assert result.is_password_protected is False

    def test_scanned_pdf_is_scanned_true(self, scanned_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(scanned_pdf_path)
        assert result.is_scanned is True

    def test_scanned_pdf_body_text_empty(self, scanned_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(scanned_pdf_path)
        assert result.body_text.strip() == ""

    def test_password_protected_pdf_flagged(self, password_protected_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(password_protected_pdf_path)
        assert result.is_password_protected is True

    def test_password_protected_pdf_body_empty(self, password_protected_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(password_protected_pdf_path)
        assert result.body_text == ""

    def test_filename_preserved(self, sample_pdf_path):
        from backend.services.file_reader import extract_pdf
        result = extract_pdf(sample_pdf_path)
        assert result.filename == sample_pdf_path.name

    def test_nonexistent_file_raises(self, tmp_path):
        from backend.services.file_reader import extract_pdf
        with pytest.raises(FileNotFoundError):
            extract_pdf(tmp_path / "ghost.pdf")

    def test_wrong_extension_raises(self, tmp_path):
        bad = tmp_path / "file.txt"
        bad.write_text("hello")
        from backend.services.file_reader import extract_pdf
        with pytest.raises(ValueError):
            extract_pdf(bad)


# ---------------------------------------------------------------------------
# DOCX extraction
# ---------------------------------------------------------------------------

class TestDOCXExtraction:
    def test_extracts_body_text(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        assert KNOWN_PII["person"] in result.body_text

    def test_returns_extracted_document_type(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        from backend.models.schemas import ExtractedDocument
        result = extract_docx(sample_docx_path)
        assert isinstance(result, ExtractedDocument)

    def test_file_type_is_docx(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        assert result.file_type == "docx"

    def test_extracts_header_text(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        assert KNOWN_PII["org"] in result.header_text

    def test_extracts_footer_text(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        assert KNOWN_PII["person"] in result.footer_text

    def test_extracts_table_cell_text(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        # Table cells should be accessible either via body_text or table_cells
        all_text = result.body_text + " ".join(
            cell for row in (result.table_cells or []) for cell in row
        )
        assert KNOWN_PII["ssn"] in all_text

    def test_table_cells_structure(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        assert result.table_cells is not None
        assert isinstance(result.table_cells, list)
        # Each row is a list of cell strings
        for row in result.table_cells:
            assert isinstance(row, list)
            for cell in row:
                assert isinstance(cell, str)

    def test_pii_in_table_not_lost(self, sample_docx_path):
        """SSN in a table cell must appear somewhere in the extraction result."""
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        all_text = result.body_text + " ".join(
            c for row in (result.table_cells or []) for c in row
        )
        assert KNOWN_PII["ssn"] in all_text

    def test_is_scanned_false_for_docx(self, sample_docx_path):
        from backend.services.file_reader import extract_docx
        result = extract_docx(sample_docx_path)
        assert result.is_scanned is False

    def test_nonexistent_docx_raises(self, tmp_path):
        from backend.services.file_reader import extract_docx
        with pytest.raises(FileNotFoundError):
            extract_docx(tmp_path / "ghost.docx")


# ---------------------------------------------------------------------------
# Generic router: extract_file dispatches by extension
# ---------------------------------------------------------------------------

class TestExtractFileDispatch:
    def test_dispatch_to_pdf_reader(self, sample_pdf_path):
        from backend.services.file_reader import extract_file
        result = extract_file(sample_pdf_path)
        assert result.file_type == "pdf"

    def test_dispatch_to_docx_reader(self, sample_docx_path):
        from backend.services.file_reader import extract_file
        result = extract_file(sample_docx_path)
        assert result.file_type == "docx"

    def test_unsupported_extension_raises(self, tmp_path):
        bad = tmp_path / "report.xlsx"
        bad.write_bytes(b"fake excel bytes")
        from backend.services.file_reader import extract_file
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract_file(bad)


# ---------------------------------------------------------------------------
# Image extraction — PDFs
# ---------------------------------------------------------------------------

class TestPDFImageExtraction:
    def test_extract_images_returns_list(self, pdf_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_image_path)
        assert isinstance(images, list)

    def test_extract_images_has_image_record(self, pdf_with_image_path):
        from backend.services.image_extractor import extract_images
        from backend.models.schemas import ImageRecord
        images = extract_images(pdf_with_image_path)
        assert len(images) >= 1
        assert isinstance(images[0], ImageRecord)

    def test_image_record_has_bytes(self, pdf_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_image_path)
        assert images[0].image_bytes is not None
        assert len(images[0].image_bytes) > 0

    def test_image_record_has_page_number(self, pdf_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_image_path)
        assert images[0].page_number >= 1

    def test_image_record_has_source_filename(self, pdf_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_image_path)
        assert images[0].source_filename == pdf_with_image_path.name

    def test_marked_for_removal_defaults_true(self, pdf_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_image_path)
        assert all(img.marked_for_removal is True for img in images)

    def test_no_images_returns_empty_list(self, sample_pdf_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(sample_pdf_path)
        assert images == []


# ---------------------------------------------------------------------------
# Image extraction — DOCX
# ---------------------------------------------------------------------------

class TestDOCXImageExtraction:
    def test_extract_images_from_docx(self, docx_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(docx_with_image_path)
        assert len(images) >= 1

    def test_docx_image_has_bytes(self, docx_with_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(docx_with_image_path)
        assert images[0].image_bytes is not None

    def test_docx_no_images_returns_empty(self, sample_docx_path):
        from backend.services.image_extractor import extract_images
        # The basic sample_docx_path has no embedded images
        images = extract_images(sample_docx_path)
        assert images == []
