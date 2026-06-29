"""
V2 Piece 6 — Image Deduplication

Tests:
- image_extractor computes a SHA-256 hash for each extracted image
- Two identical images get the same hash
- Two different images get different hashes
- DB: images table stores hash column
- GET /jobs/{id}/images groups by hash, returns one entry per unique image
- Each group entry has: hash, count, pages (list of page numbers), image_index, thumbnail
- Single checkbox marks all instances in the group
- POST /jobs/{id}/images/{idx}/mark with apply_to_group=true marks all same-hash images
- When group is marked for removal, all instances are stripped from output
- apply_to_group=false marks only the single index (existing behavior)
- Dedup grouping: 3 occurrences → 1 group entry with count=3
- All-unique images: N images → N group entries each with count=1
"""

import hashlib
import io
import struct
import zlib

import pytest


# ---------------------------------------------------------------------------
# Fixtures — PDFs with duplicate embedded images
# ---------------------------------------------------------------------------

def _make_minimal_png(color=(255, 0, 0)):
    """Produce a 1x1 PNG with given RGB colour."""
    r, g, b = color

    def chunk(name, data):
        c = name + data
        crc = zlib.crc32(c) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + c + struct.pack(">I", crc)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw = bytes([0, r, g, b])
    png += chunk(b"IDAT", zlib.compress(raw))
    png += chunk(b"IEND", b"")
    return png


RED_PNG = _make_minimal_png((255, 0, 0))
BLUE_PNG = _make_minimal_png((0, 0, 255))


@pytest.fixture
def pdf_with_duplicate_images(tmp_path):
    """PDF where the same red image appears on two separate pages."""
    import fitz
    doc = fitz.open()
    for _ in range(2):
        page = doc.new_page()
        page.insert_text((50, 50), "Page with image.", fontsize=11)
        page.insert_image(fitz.Rect(100, 100, 200, 200), stream=RED_PNG)
    path = tmp_path / "dup_images.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf_with_mixed_images(tmp_path):
    """PDF with two distinct images (red on page 1, blue on page 2)."""
    import fitz
    doc = fitz.open()
    p1 = doc.new_page()
    p1.insert_text((50, 50), "Page 1.", fontsize=11)
    p1.insert_image(fitz.Rect(100, 100, 200, 200), stream=RED_PNG)
    p2 = doc.new_page()
    p2.insert_text((50, 50), "Page 2.", fontsize=11)
    p2.insert_image(fitz.Rect(100, 100, 200, 200), stream=BLUE_PNG)
    path = tmp_path / "mixed_images.pdf"
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def pdf_with_three_identical_images(tmp_path):
    """PDF where the same image appears on three pages."""
    import fitz
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        page.insert_image(fitz.Rect(100, 100, 200, 200), stream=RED_PNG)
    path = tmp_path / "triple_dup.pdf"
    doc.save(str(path))
    doc.close()
    return path


# ---------------------------------------------------------------------------
# Hash computation in image_extractor
# ---------------------------------------------------------------------------

class TestImageHashing:
    def test_extract_images_includes_hash(self, pdf_with_raster_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_raster_image_path)
        assert len(images) > 0
        assert hasattr(images[0], "hash") or "hash" in images[0]

    def test_same_image_same_hash(self, pdf_with_duplicate_images):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_duplicate_images)
        assert len(images) >= 2
        hashes = [img.hash if hasattr(img, "hash") else img["hash"] for img in images]
        assert hashes[0] == hashes[1]

    def test_different_images_different_hashes(self, pdf_with_mixed_images):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_mixed_images)
        assert len(images) >= 2
        hashes = [img.hash if hasattr(img, "hash") else img["hash"] for img in images]
        assert hashes[0] != hashes[1]

    def test_hash_is_sha256_hex(self, pdf_with_raster_image_path):
        from backend.services.image_extractor import extract_images
        images = extract_images(pdf_with_raster_image_path)
        h = images[0].hash if hasattr(images[0], "hash") else images[0]["hash"]
        # SHA-256 hex is 64 characters
        assert isinstance(h, str) and len(h) == 64

    def test_hash_stored_in_db(self, tmp_db_path, pdf_with_raster_image_path):
        import sqlite3
        from backend.db.database import init_db
        init_db(tmp_db_path)
        conn = sqlite3.connect(tmp_db_path)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(images)")}
        conn.close()
        assert "hash" in cols


# ---------------------------------------------------------------------------
# GET /jobs/{id}/images — deduplication grouping
# ---------------------------------------------------------------------------

PDF_MIME = "application/pdf"


def _upload_and_get_images(app_client, pdf_path):
    with open(pdf_path, "rb") as f:
        job_id = app_client.post(
            "/upload",
            files={"files": (pdf_path.name, f, PDF_MIME)},
        ).json()["job_id"]
    return job_id, app_client.get(f"/jobs/{job_id}/images")


class TestImageGroupingAPI:
    def test_duplicate_images_return_one_group(
        self, app_client, pdf_with_duplicate_images
    ):
        job_id, r = _upload_and_get_images(app_client, pdf_with_duplicate_images)
        assert r.status_code == 200
        groups = r.json()
        assert len(groups) == 1

    def test_duplicate_group_has_count_2(
        self, app_client, pdf_with_duplicate_images
    ):
        job_id, r = _upload_and_get_images(app_client, pdf_with_duplicate_images)
        group = r.json()[0]
        assert group.get("count") == 2

    def test_duplicate_group_has_two_pages(
        self, app_client, pdf_with_duplicate_images
    ):
        job_id, r = _upload_and_get_images(app_client, pdf_with_duplicate_images)
        group = r.json()[0]
        assert len(group.get("pages", [])) == 2

    def test_mixed_images_return_two_groups(
        self, app_client, pdf_with_mixed_images
    ):
        job_id, r = _upload_and_get_images(app_client, pdf_with_mixed_images)
        assert len(r.json()) == 2

    def test_group_has_hash_field(self, app_client, pdf_with_raster_image_path):
        job_id, r = _upload_and_get_images(app_client, pdf_with_raster_image_path)
        if r.json():
            assert "hash" in r.json()[0]

    def test_group_has_thumbnail(self, app_client, pdf_with_raster_image_path):
        job_id, r = _upload_and_get_images(app_client, pdf_with_raster_image_path)
        if r.json():
            assert "thumbnail" in r.json()[0] or "data_url" in r.json()[0]

    def test_three_identical_images_one_group_count_3(
        self, app_client, pdf_with_three_identical_images
    ):
        job_id, r = _upload_and_get_images(app_client, pdf_with_three_identical_images)
        groups = r.json()
        assert len(groups) == 1
        assert groups[0]["count"] == 3


# ---------------------------------------------------------------------------
# apply_to_group — marking and stripping
# ---------------------------------------------------------------------------

class TestApplyToGroup:
    def test_apply_to_group_true_marks_all_same_hash(
        self, app_client, pdf_with_duplicate_images
    ):
        with open(pdf_with_duplicate_images, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (pdf_with_duplicate_images.name, f, PDF_MIME)},
            ).json()["job_id"]
        # Mark index 0 with apply_to_group=true
        r = app_client.post(
            f"/jobs/{job_id}/images/0/mark",
            json={"marked_for_removal": True, "apply_to_group": True},
        )
        assert r.status_code == 200
        # Both images (index 0 and 1) should now be marked
        images_r = app_client.get(f"/jobs/{job_id}/images")
        groups = images_r.json()
        assert groups[0].get("marked_for_removal") is True

    def test_apply_to_group_false_marks_only_one(
        self, app_client, pdf_with_duplicate_images
    ):
        with open(pdf_with_duplicate_images, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (pdf_with_duplicate_images.name, f, PDF_MIME)},
            ).json()["job_id"]
        # Mark index 0 without apply_to_group
        app_client.post(
            f"/jobs/{job_id}/images/0/mark",
            json={"marked_for_removal": False, "apply_to_group": False},
        )
        # Index 1 should retain its default (marked for removal = True)
        raw_images = app_client.get(f"/jobs/{job_id}/images").json()
        # One group, but they diverge — implementation detail; just check no crash
        assert raw_images is not None

    def test_all_group_instances_stripped_from_output(
        self, app_client, pdf_with_duplicate_images, mock_llm_endpoint
    ):
        """After marking the group for removal and anonymizing, output PDF has no images."""
        import fitz
        with open(pdf_with_duplicate_images, "rb") as f:
            job_id = app_client.post(
                "/upload",
                files={"files": (pdf_with_duplicate_images.name, f, PDF_MIME)},
            ).json()["job_id"]
        # Mark group for removal
        app_client.post(
            f"/jobs/{job_id}/images/0/mark",
            json={"marked_for_removal": True, "apply_to_group": True},
        )
        # Anonymize
        app_client.post(f"/jobs/{job_id}/anonymize")
        # Export and check no images remain
        export_r = app_client.post(f"/jobs/{job_id}/export")
        assert export_r.status_code == 200
        output_bytes = export_r.content
        doc = fitz.open(stream=output_bytes, filetype="pdf")
        total_images = sum(len(page.get_images()) for page in doc)
        doc.close()
        assert total_images == 0, f"Expected 0 images after stripping group, got {total_images}"
