"""Upload route — POST /upload, GET /jobs, GET /jobs/{job_id}/summary."""

import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, HTTPException, Request, UploadFile

from backend.db.database import (
    create_job,
    get_db,
    get_file_records,
    get_job,
    get_mappings,
    list_jobs,
    save_file_record,
)

router = APIRouter()

_ALLOWED_EXTENSIONS = {".pdf", ".docx"}


@router.post("/upload")
async def upload_files(request: Request, files: List[UploadFile] = File(...)):
    """
    Accept one or more PDF/DOCX files.  Creates a new job, saves files to a
    temp staging directory, records file metadata in the DB.
    Returns: {job_id, files: [{filename, size_bytes, file_type, page_count}]}
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

        output_dir: Path = request.app.state.output_dir
        staging_dir = output_dir / job_id / "input"
        staging_dir.mkdir(parents=True, exist_ok=True)

        saved_files = []
        for upload in files:
            ext = Path(upload.filename or "unknown").suffix.lower()
            file_type = "pdf" if ext == ".pdf" else "docx"

            dest = staging_dir / Path(upload.filename or f"file{ext}").name
            content = await upload.read()
            dest.write_bytes(content)

            # Extract page count from the saved file
            page_count = _get_page_count(dest)

            record = {
                "filename": upload.filename,
                "file_type": file_type,
                "size_bytes": len(content),
                "page_count": page_count,
            }
            save_file_record(conn, job_id, record)
            saved_files.append(record)

        return {"job_id": job_id, "files": saved_files}
    finally:
        conn.close()


def _get_page_count(path: Path) -> int:
    """Extract page count from a PDF or DOCX. Returns 1 on failure."""
    try:
        ext = path.suffix.lower()
        if ext == ".pdf":
            import fitz
            doc = fitz.open(str(path))
            n = doc.page_count
            doc.close()
            return max(1, n)
        elif ext == ".docx":
            from docx import Document
            doc = Document(str(path))
            # python-docx has no native page count; approximate by paragraph count
            para_count = len(doc.paragraphs)
            return max(1, para_count // 10 + 1)
    except Exception:
        pass
    return 1


@router.get("/jobs")
def list_all_jobs(request: Request):
    """Return all jobs ordered newest-first."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        return list_jobs(conn)
    finally:
        conn.close()


@router.get("/jobs/{job_id}/summary")
def job_summary(job_id: str, request: Request):
    """
    Return a summary of job metadata: file count, PII items found, model used.
    Intended for the export screen summary panel.
    """
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path

    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        file_records = get_file_records(conn, job_id)
        mappings = get_mappings(conn, job_id)

        return {
            "job_id": job_id,
            "file_count": len(file_records),
            "pii_items_found": len(mappings),
            "model_used": config.get("default_model", "llama3.1:8b"),
            "status": job.get("status", "pending"),
            "created_at": job.get("created_at", ""),
        }
    finally:
        conn.close()
