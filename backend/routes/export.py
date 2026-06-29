"""
Export routes — GET /jobs/{job_id}/export
               GET /jobs/{job_id}/export/mapping
"""

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from backend.db.database import get_db, get_file_records, get_job, get_mappings

router = APIRouter()


@router.get("/jobs/{job_id}/export/mapping")
def export_mapping(job_id: str, request: Request):
    """Download the mapping table as JSON."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
        mappings = get_mappings(conn, job_id)
        return JSONResponse(
            content=mappings,
            headers={"Content-Disposition": f'attachment; filename="mapping_{job_id}.json"'},
        )
    finally:
        conn.close()


@router.post("/jobs/{job_id}/export")
def export_files_post(job_id: str, request: Request):
    """POST alias — allows callers to trigger export without a body."""
    return _do_export(job_id, request)


@router.get("/jobs/{job_id}/export")
def export_files(job_id: str, request: Request):
    """
    Download anonymized output files.
    Single file → returns the file directly.
    Multiple files → returns a ZIP archive.
    """
    return _do_export(job_id, request)


def _do_export(job_id: str, request: Request):
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        file_records = get_file_records(conn, job_id)
        output_job_dir = output_dir / job_id / "output"

        # Collect available output files
        available = []
        for rec in file_records:
            out_path = output_job_dir / rec["filename"]
            if out_path.exists():
                available.append((rec["filename"], out_path))

        if not available:
            raise HTTPException(status_code=404, detail="No output files found for this job")

        if len(available) == 1:
            filename, path = available[0]
            content = path.read_bytes()
            media_type = (
                "application/pdf" if filename.endswith(".pdf")
                else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            )
            return Response(
                content=content,
                media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="anon_{filename}"'},
            )

        # Multiple files → ZIP
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, path in available:
                zf.write(path, arcname=f"anon_{filename}")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="docscrub_{job_id}.zip"'},
        )
    finally:
        conn.close()
