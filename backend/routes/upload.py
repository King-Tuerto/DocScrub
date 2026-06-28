"""Upload route — POST /upload, GET /jobs."""

import shutil
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.db.database import (
    create_job,
    get_db,
    list_jobs,
    save_file_record,
)

router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".docx"}
_ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@router.post("/upload")
async def upload_files(request: Request, files: List[UploadFile] = File(...)):
    """
    Accept one or more PDF/DOCX files.  Creates a new job, saves files to a
    temp staging directory, records file metadata in the DB.
    Returns: {job_id, files: [{filename, size_bytes, file_type}]}
    """
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path

    # Validate extensions
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        if ext not in _ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {f.filename!r}. Only PDF and DOCX are accepted.",
            )

    conn = get_db(db_path)
    try:
        job_id = create_job(conn, name=f"job-{uuid.uuid4().hex[:8]}")

        # Create staging directory for this job's files
        output_dir = Path(config.get("output_directory", "./output"))
        staging_dir = output_dir / job_id / "input"
        staging_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []
        for upload in files:
            ext = Path(upload.filename or "unknown").suffix.lower()
            file_type = "pdf" if ext == ".pdf" else "docx"

            dest = staging_dir / (upload.filename or f"file{ext}")
            content = await upload.read()
            dest.write_bytes(content)

            record = {
                "filename": upload.filename,
                "file_type": file_type,
                "size_bytes": len(content),
                "page_count": 0,  # determined during extraction
            }
            save_file_record(conn, job_id, record)
            saved_files.append(record)

        return {"job_id": job_id, "files": saved_files}
    finally:
        conn.close()


@router.get("/jobs")
def list_all_jobs(request: Request):
    """Return all jobs ordered newest-first."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        return list_jobs(conn)
    finally:
        conn.close()
