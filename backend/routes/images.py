"""
Images route — GET  /jobs/{job_id}/images
               PATCH /jobs/{job_id}/images/{image_id}
               POST  /jobs/{job_id}/images/{idx}/mark

Extracts embedded images from uploaded files, stores metadata in DB,
and lets the user toggle the marked_for_removal flag before anonymization.
GET /images groups by SHA-256 hash: one entry per unique image.
"""

import base64
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.db.database import (
    get_db,
    get_file_records,
    get_images_for_job,
    get_image_by_id,
    get_job,
    upsert_image,
    update_image_flag,
    update_images_by_hash,
)
from backend.services.image_extractor import extract_images

router = APIRouter()


class ImageFlagBody(BaseModel):
    marked_for_removal: bool


class MarkBody(BaseModel):
    marked_for_removal: bool
    apply_to_group: bool = False


def _image_id(job_id: str, source_filename: str, image_index: int) -> str:
    """Deterministic, stable ID for an image within a job."""
    return f"{job_id}_{source_filename}_{image_index}"


def _extract_and_upsert(conn, job_id: str, output_dir: Path, file_records: list):
    """Extract images from staged files and upsert into DB. Returns list of ImageRecord."""
    staging_dir = output_dir / job_id / "input"
    all_images = []
    for rec in file_records:
        file_path = staging_dir / rec["filename"]
        if not file_path.exists():
            continue
        try:
            images = extract_images(file_path)
        except Exception:
            images = []
        for img in images:
            img_id = _image_id(job_id, img.source_filename, img.image_index)
            upsert_image(
                conn,
                image_id=img_id,
                job_id=job_id,
                source_filename=img.source_filename,
                page_number=img.page_number,
                image_index=img.image_index,
                marked_for_removal=True,
                image_hash=img.hash,
            )
            all_images.append(img)
    return all_images


@router.get("/jobs/{job_id}/images")
def list_images(job_id: str, request: Request):
    """
    Extract and return all images grouped by SHA-256 hash.
    One entry per unique image with count, pages, thumbnail, and marked_for_removal.
    """
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        file_records = get_file_records(conn, job_id)

        # Read existing DB flags before upsert so we preserve user-set flags
        existing = {row["id"]: row for row in get_images_for_job(conn, job_id)}

        all_images = _extract_and_upsert(conn, job_id, output_dir, file_records)

        # Re-read DB state after upsert to pick up any newly inserted rows
        db_state = {row["id"]: row for row in get_images_for_job(conn, job_id)}

        # Group by hash (fall back to image_id as key for unhashed images)
        groups: dict = {}
        for img in all_images:
            img_id = _image_id(job_id, img.source_filename, img.image_index)
            db_row = db_state.get(img_id) or existing.get(img_id)
            marked = bool(db_row["marked_for_removal"]) if db_row else True

            group_key = img.hash if img.hash else f"__nohash_{img_id}__"

            if group_key not in groups:
                b64 = base64.b64encode(img.image_bytes).decode("ascii") if img.image_bytes else ""
                rep_id = _image_id(job_id, img.source_filename, img.image_index)
                groups[group_key] = {
                    "hash": img.hash or "",
                    "count": 0,
                    "pages": [],
                    "image_index": img.image_index,
                    "thumbnail": b64,
                    "all_marked": True,
                    # backward-compat fields for existing tests
                    "id": rep_id,
                    "page_number": img.page_number,
                    "b64": b64,
                    "source_filename": img.source_filename,
                }

            groups[group_key]["count"] += 1
            groups[group_key]["pages"].append(img.page_number)
            if not marked:
                groups[group_key]["all_marked"] = False

        result = []
        for group in groups.values():
            result.append({
                "hash": group["hash"],
                "count": group["count"],
                "pages": sorted(set(group["pages"])),
                "image_index": group["image_index"],
                "thumbnail": group["thumbnail"],
                "marked_for_removal": group["all_marked"],
                # backward-compat
                "id": group["id"],
                "page_number": group["page_number"],
                "b64": group["b64"],
                "source_filename": group["source_filename"],
            })

        return result

    finally:
        conn.close()


@router.post("/jobs/{job_id}/images/{idx}/mark")
def mark_image(job_id: str, idx: int, body: MarkBody, request: Request):
    """
    Set marked_for_removal for an image by index.
    apply_to_group=True marks all images sharing the same hash.
    """
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        file_records = get_file_records(conn, job_id)

        # Ensure all images are in DB (first visit via mark rather than GET)
        all_images = _extract_and_upsert(conn, job_id, output_dir, file_records)

        # Find the target image by index
        target = next((img for img in all_images if img.image_index == idx), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Image index {idx} not found")

        if body.apply_to_group and target.hash:
            update_images_by_hash(conn, job_id, target.hash, body.marked_for_removal)
        else:
            img_id = _image_id(job_id, target.source_filename, target.image_index)
            update_image_flag(conn, img_id, body.marked_for_removal)

        return {"ok": True, "image_index": idx, "marked_for_removal": body.marked_for_removal}

    finally:
        conn.close()


@router.patch("/jobs/{job_id}/images/{image_id}")
def update_image(job_id: str, image_id: str, body: ImageFlagBody, request: Request):
    """Toggle the marked_for_removal flag for a specific image (legacy endpoint)."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        existing = get_image_by_id(conn, image_id)
        if existing is None:
            parts = image_id.split("_")
            if len(parts) >= 3:
                upsert_image(
                    conn,
                    image_id=image_id,
                    job_id=job_id,
                    source_filename=parts[1] if len(parts) > 1 else "unknown",
                    page_number=1,
                    image_index=int(parts[-1]) if parts[-1].isdigit() else 0,
                    marked_for_removal=body.marked_for_removal,
                )
            else:
                raise HTTPException(status_code=404, detail=f"Image {image_id!r} not found")
        else:
            update_image_flag(conn, image_id, body.marked_for_removal)

        return {"id": image_id, "marked_for_removal": body.marked_for_removal}
    finally:
        conn.close()
