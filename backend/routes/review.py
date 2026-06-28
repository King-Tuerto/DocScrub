"""
Review route — GET  /jobs/{job_id}/review
              GET  /jobs/{job_id}/mapping
              PATCH /jobs/{job_id}/mapping/{placeholder}
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from backend.db.database import (
    get_db,
    get_file_records,
    get_job,
    get_mappings,
    save_mappings,
)
from backend.services.replacer import apply_replacements
from backend.services.mapper import MappingEntry, MappingTable

router = APIRouter()


class MappingPatch(BaseModel):
    original: str


@router.get("/jobs/{job_id}/review")
def review_job(job_id: str, request: Request, restored: bool = False):
    """
    Return original text, anonymized text, mapping, and positions for each file.

    When ?restored=true, also returns restored_text extracted from the re-identified
    output files (written by POST /reidentify).
    """
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        raw_mappings = get_mappings(conn, job_id)
        mapping_table = MappingTable(entries=[
            MappingEntry(
                original=m["original"],
                placeholder=m["placeholder"],
                pii_type=m["pii_type"],
                source=m.get("source"),
            )
            for m in raw_mappings
        ])

        file_records = get_file_records(conn, job_id)
        staging_dir = output_dir / job_id / "input"
        restored_dir = output_dir / job_id / "restored"

        files_out = []
        for rec in file_records:
            input_path = staging_dir / rec["filename"]
            original_text = ""
            if input_path.exists():
                try:
                    from backend.services.file_reader import extract_file
                    doc = extract_file(input_path)
                    original_text = doc.body_text
                except Exception:
                    original_text = ""

            replaced = apply_replacements(original_text, mapping_table)
            entry = {
                "filename": rec["filename"],
                "original_text": original_text,
                "anonymized_text": replaced.text,
                "positions": [
                    {
                        "start": p.start,
                        "end": p.end,
                        "pii_type": p.pii_type,
                        "placeholder": p.placeholder,
                    }
                    for p in replaced.positions
                ],
            }

            if restored:
                restored_path = restored_dir / rec["filename"]
                restored_text = ""
                if restored_path.exists():
                    try:
                        from backend.services.file_reader import extract_file as _ef
                        restored_doc = _ef(restored_path)
                        restored_text = restored_doc.body_text
                    except Exception:
                        restored_text = ""
                entry["restored_text"] = restored_text

            files_out.append(entry)

        return {
            "job_id": job_id,
            "files": files_out,
            "mapping": raw_mappings,
        }
    finally:
        conn.close()


@router.get("/jobs/{job_id}/mapping")
def get_mapping(job_id: str, request: Request):
    """Return the raw mapping list for a job."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
        return get_mappings(conn, job_id)
    finally:
        conn.close()


@router.patch("/jobs/{job_id}/mapping/{placeholder:path}")
def patch_mapping_entry(job_id: str, placeholder: str, body: MappingPatch, request: Request):
    """Update the original value for a specific placeholder."""
    db_path: Path = request.app.state.db_path
    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        current = get_mappings(conn, job_id)
        updated = False
        new_entries = []
        for entry in current:
            if entry["placeholder"] == placeholder:
                new_entries.append({**entry, "original": body.original})
                updated = True
            else:
                new_entries.append(entry)

        if not updated:
            raise HTTPException(status_code=404, detail=f"Placeholder {placeholder!r} not found")

        save_mappings(conn, job_id, new_entries)
        return {"ok": True, "placeholder": placeholder, "original": body.original}
    finally:
        conn.close()
