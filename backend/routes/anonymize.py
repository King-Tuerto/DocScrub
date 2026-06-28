"""
Anonymize route — POST /jobs/{job_id}/anonymize
                  POST /jobs/{job_id}/anonymize/stream (SSE)
"""

import json
from pathlib import Path
from typing import Generator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.db.database import (
    get_db,
    get_file_records,
    get_job,
    save_mappings,
    update_job_status,
)
from backend.services.pipeline import run_pipeline

router = APIRouter()


def _get_staged_paths(output_dir: Path, job_id: str, file_records: list) -> list:
    """Resolve input file paths from staging directory."""
    staging_dir = output_dir / job_id / "input"
    paths = []
    for rec in file_records:
        p = staging_dir / rec["filename"]
        if p.exists():
            paths.append(p)
    return paths


def _run_and_store(job_id: str, request: Request, progress_cb=None) -> dict:
    """Run the pipeline and persist results; return response payload."""
    config: dict = request.app.state.config
    db_path: Path = request.app.state.db_path
    output_dir = Path(config.get("output_directory", "./output"))

    conn = get_db(db_path)
    try:
        job = get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")

        file_records = get_file_records(conn, job_id)
        file_paths = _get_staged_paths(output_dir, job_id, file_records)

        update_job_status(conn, job_id, "processing")

        pipeline_result = run_pipeline(
            job_id=job_id,
            file_paths=file_paths,
            config=config,
            progress_cb=progress_cb,
        )

        # Persist mapping
        mapping_entries = [
            {
                "original": e.original,
                "placeholder": e.placeholder,
                "pii_type": e.pii_type,
                "source": e.source,
            }
            for e in pipeline_result.mapping.entries
        ]
        save_mappings(conn, job_id, mapping_entries)

        # Save anonymized output files
        output_job_dir = output_dir / job_id / "output"
        output_job_dir.mkdir(parents=True, exist_ok=True)
        for fr in pipeline_result.files:
            out_path = output_job_dir / fr.filename
            out_path.write_text(fr.anonymized_text, encoding="utf-8")

        update_job_status(conn, job_id, "complete")

        return {
            "job_id": job_id,
            "status": "complete",
            "warning": pipeline_result.warning,
            "files": [
                {
                    "filename": fr.filename,
                    "anonymized_text": fr.anonymized_text,
                    "positions": fr.positions,
                }
                for fr in pipeline_result.files
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        update_job_status(conn, job_id, "error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/jobs/{job_id}/anonymize")
def anonymize_job(job_id: str, request: Request):
    """Run the anonymization pipeline synchronously."""
    return _run_and_store(job_id, request)


@router.post("/jobs/{job_id}/anonymize/stream")
def anonymize_job_stream(job_id: str, request: Request):
    """
    SSE streaming version — emits progress events while the pipeline runs.
    Each event: data: {"step": "...", "message": "..."}\n\n
    """

    def event_stream() -> Generator[str, None, None]:
        events: list = []

        def collect(step: str, msg: str = ""):
            events.append({"step": step, "message": msg})

        try:
            result = _run_and_store(job_id, request, progress_cb=collect)
        except HTTPException as exc:
            yield f"data: {json.dumps({'error': exc.detail})}\n\n"
            return

        # Emit collected progress events first
        for ev in events:
            yield f"data: {json.dumps(ev)}\n\n"

        # Final done event
        yield f"data: {json.dumps({'step': 'complete', 'status': 'complete'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
