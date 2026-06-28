"""
Images route — GET  /jobs/{job_id}/images
               PATCH /jobs/{job_id}/images/{image_id}

Extracts embedded images from uploaded files, stores metadata in DB,
and lets the user toggle the marked_for_removal flag before anonymization.
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
)
from backend.services.image_extractor import extract_images

router = APIRouter()


class ImageFlagBody(BaseModel):
    marked_for_removal: bool


def _image_id(job_id: str, source_filename: str, image_index: int) -> str:
    """Deterministic, stable ID for an image within a job."""
    return f"{job_id}_{source_filename}_{image_index}"


@router.get("/jobs/{job_id}/images")
def list_images(job_id: str, request: Request):
    """
    Extract and return all images from the uploaded files for this job.
    Each image includes base64-encoded bytes (b64) for thumbnail display.
    The marked_for_removal flag is persisted in the DB; default is True.
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
        staging_dir = output_dir / job_id / "input"

        # Load current DB flags (keyed by image_id)
        existing = {row["id"]: row for row in get_images_for_job(conn, job_id)}

        response_items = []

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

                # Upsert into DB — preserves existing marked_for_removal if present
                upsert_image(
                    conn,
                    image_id=img_id,
                    job_id=job_id,
                    source_filename=img.source_filename,
                    page_number=img.page_number,
                    image_index=img.image_index,
                    marked_for_removal=True,
                )

                # Use DB flag if it already existed (PATCH may have flipped it)
                db_row = existing.get(img_id)
                marked = bool(db_row["marked_for_removal"]) if db_row else True

                b64 = ""
                if img.image_bytes:
                    b64 = base64.b64encode(img.image_bytes).decode("ascii")

                response_items.append({
                    "id": img_id,
                    "job_id": job_id,
                    "source_filename": img.source_filename,
                    "page_number": img.page_number,
                    "image_index": img.image_index,
                    "marked_for_removal": marked,
                    "b64": b64,
                })

        return response_items

    finally:
        conn.close()


@router.patch("/jobs/{job_id}/images/{image_id}")
def update_image(job_id: str, image_id: str, body: ImageFlagBody, request: Request):
    """Toggle the marked_for_removal flag for a specific image."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        # Upsert the image record (in case GET /images has not been called yet)
        # and then update the flag
        existing = get_image_by_id(conn, image_id)
        if existing is None:
            # Insert a placeholder record so we can store the flag
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
