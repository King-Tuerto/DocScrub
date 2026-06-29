"""
Image extraction from PDF and DOCX files.
Returns list[ImageRecord] with bytes and metadata.
"""

import hashlib
import zipfile
from pathlib import Path
from typing import List

from backend.models.schemas import ImageRecord


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_images(path: Path) -> List[ImageRecord]:
    """
    Extract all embedded images from a PDF or DOCX file.

    Args:
        path: Path to the file.

    Returns:
        List of ImageRecord objects.  All default to marked_for_removal=True.
    """
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _extract_pdf_images(path)
    elif ext == ".docx":
        return _extract_docx_images(path)
    else:
        return []


# ---------------------------------------------------------------------------
# PDF image extraction
# ---------------------------------------------------------------------------

def _extract_pdf_images(path: Path) -> List[ImageRecord]:
    import fitz

    doc = fitz.open(str(path))
    if doc.needs_pass:
        doc.close()
        return []

    results: List[ImageRecord] = []
    index = 0

    for page_num, page in enumerate(doc, start=1):
        # --- Raster image XObjects ---
        raster_images = page.get_images(full=True)
        for img_info in raster_images:
            xref = img_info[0]
            try:
                img_data = doc.extract_image(xref)
                img_bytes = img_data.get("image", b"")
                if img_bytes:
                    results.append(ImageRecord(
                        source_filename=path.name,
                        page_number=page_num,
                        image_index=index,
                        image_bytes=img_bytes,
                        marked_for_removal=True,
                        hash=hashlib.sha256(img_bytes).hexdigest(),
                    ))
                    index += 1
            except Exception:
                pass

        # --- Form XObjects (e.g. embedded PDF pages via show_pdf_page) ---
        # Only process if no raster images were found on this page,
        # to avoid double-counting pages that mix both types.
        if not raster_images:
            try:
                xobjects = page.get_xobjects()
            except Exception:
                xobjects = []

            if xobjects:
                # Render the whole page as PNG for user review
                try:
                    pix = page.get_pixmap(dpi=72)
                    img_bytes = pix.tobytes("png")
                    if img_bytes:
                        results.append(ImageRecord(
                            source_filename=path.name,
                            page_number=page_num,
                            image_index=index,
                            image_bytes=img_bytes,
                            marked_for_removal=True,
                            hash=hashlib.sha256(img_bytes).hexdigest(),
                        ))
                        index += 1
                except Exception:
                    pass

    doc.close()
    return results


# ---------------------------------------------------------------------------
# DOCX image extraction
# ---------------------------------------------------------------------------

def _extract_docx_images(path: Path) -> List[ImageRecord]:
    """
    Extract images from the word/media/ directory inside the DOCX ZIP.
    """
    results: List[ImageRecord] = []
    index = 0

    try:
        with zipfile.ZipFile(str(path), "r") as z:
            media_files = [
                name for name in z.namelist()
                if name.startswith("word/media/")
                and not name.endswith("/")
            ]
            for media_file in sorted(media_files):
                img_bytes = z.read(media_file)
                if img_bytes:
                    results.append(ImageRecord(
                        source_filename=path.name,
                        page_number=1,  # DOCX has no page-level metadata without rendering
                        image_index=index,
                        image_bytes=img_bytes,
                        marked_for_removal=True,
                        hash=hashlib.sha256(img_bytes).hexdigest(),
                    ))
                    index += 1
    except (zipfile.BadZipFile, KeyError):
        pass

    return results
