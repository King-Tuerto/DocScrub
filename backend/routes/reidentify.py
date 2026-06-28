"""
Re-identify route — POST /reidentify
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Dict

from backend.db.database import get_db, get_file_records, get_job, get_mappings
from backend.services.mapper import MappingEntry, MappingTable
from backend.services.replacer import reverse_replacements

router = APIRouter()


class ReidentifyBody(BaseModel):
    job_id: str
    mapping: Dict[str, str]  # {placeholder: original}


@router.post("/reidentify")
def reidentify(body: ReidentifyBody, request: Request):
    """
    Swap placeholders back to originals using the provided mapping dict.
    Returns restored text for each file in the job.
    """
    if not body.mapping:
        raise HTTPException(status_code=400, detail="mapping must not be empty")

    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, db_path if False else body.job_id)
        # get_job takes conn + job_id
        job = get_job(conn, body.job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {body.job_id!r} not found")

        # Build reverse mapping table from provided dict
        entries = [
            MappingEntry(original=original, placeholder=placeholder, pii_type="")
            for placeholder, original in body.mapping.items()
        ]
        mapping_table = MappingTable(entries=entries)

        # Re-identify each output file
        output_job_dir = output_dir / body.job_id / "output"
        file_records = get_file_records(conn, body.job_id)

        restored_files = []
        for rec in file_records:
            out_path = output_job_dir / rec["filename"]
            if out_path.exists():
                anon_text = out_path.read_text(encoding="utf-8")
                try:
                    restored = reverse_replacements(anon_text, mapping_table)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                restored_files.append({
                    "filename": rec["filename"],
                    "restored_text": restored,
                })

        return {"job_id": body.job_id, "files": restored_files}
    finally:
        conn.close()
