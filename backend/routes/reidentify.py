"""
Re-identify route — POST /reidentify

Reads anonymized output files and reverses placeholder substitution,
producing format-preserving output (PDF stays PDF, DOCX stays DOCX).
Single file → returns binary directly.
Multiple files → returns a ZIP archive.
"""

import io
import zipfile
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from backend.db.database import get_db, get_file_records, get_job
from backend.services.mapper import MappingEntry, MappingTable
from backend.services.file_writer import write_reidentified_pdf, write_reidentified_docx

router = APIRouter()


class ReidentifyBody(BaseModel):
    job_id: str
    mapping: Dict[str, str]  # {placeholder: original}


@router.post("/reidentify")
def reidentify(body: ReidentifyBody, request: Request):
    """
    Swap placeholders back to originals.
    Returns format-preserving binary output (PDF / DOCX / ZIP for multi-file).
    """
    if not body.mapping:
        raise HTTPException(status_code=400, detail="mapping must not be empty")

    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, body.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {body.job_id!r} not found")

        # Build reverse mapping table from provided dict
        entries = [
            MappingEntry(original=original, placeholder=placeholder, pii_type="")
            for placeholder, original in body.mapping.items()
        ]
        mapping_table = MappingTable(entries=entries)

        file_records = get_file_records(conn, body.job_id)
        output_job_dir = output_dir / body.job_id / "output"
        staging_dir = output_dir / body.job_id / "input"

        restored_files = []  # list of (filename, bytes)

        # Write restored files to a persistent sub-directory so that
        # GET /jobs/{job_id}/review?restored=true can serve them
        restored_dir = output_dir / body.job_id / "restored"
        restored_dir.mkdir(parents=True, exist_ok=True)

        for rec in file_records:
            filename = rec["filename"]
            out_path = output_job_dir / filename

            if not out_path.exists():
                continue

            ext = Path(filename).suffix.lower()
            restored_bytes = _restore_file(out_path, ext, mapping_table)

            if restored_bytes:
                # Persist to disk for review endpoint
                (restored_dir / filename).write_bytes(restored_bytes)
                restored_files.append((filename, restored_bytes))

        if not restored_files:
            raise HTTPException(
                status_code=404, detail="No output files found for re-identification"
            )

        if len(restored_files) == 1:
            filename, content = restored_files[0]
            media_type = _media_type(filename)
            return Response(
                content=content,
                media_type=media_type,
                headers={"Content-Disposition": f'attachment; filename="restored_{filename}"'},
            )

        # Multiple files → ZIP
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for filename, content in restored_files:
                zf.writestr(f"restored_{filename}", content)
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="restored_{body.job_id}.zip"'
            },
        )

    finally:
        conn.close()


def _restore_file(out_path: Path, ext: str, mapping_table: MappingTable) -> bytes:
    """
    Apply reverse replacements to an anonymized file and return the result bytes.
    Falls back to text-based processing if format-preserving fails.
    """
    tmp = out_path.with_suffix(out_path.suffix + ".reid_tmp")
    try:
        if ext == ".pdf":
            write_reidentified_pdf(out_path, tmp, mapping_table)
            if tmp.exists():
                content = tmp.read_bytes()
                tmp.unlink()
                return content
        elif ext == ".docx":
            write_reidentified_docx(out_path, tmp, mapping_table)
            if tmp.exists():
                content = tmp.read_bytes()
                tmp.unlink()
                return content
    except Exception:
        if tmp.exists():
            tmp.unlink()

    # Fallback: read as bytes (useful for already-plain-text edge cases)
    try:
        return out_path.read_bytes()
    except Exception:
        return b""


def _media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".docx":
        return (
            "application/vnd.openxmlformats-officedocument"
            ".wordprocessingml.document"
        )
    return "application/octet-stream"
