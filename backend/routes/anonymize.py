"""
Anonymize route — POST /jobs/{job_id}/anonymize
                  POST /jobs/{job_id}/anonymize/stream (SSE)
"""

import json
from pathlib import Path
from typing import Generator, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.db.database import (
    get_db,
    get_file_records,
    get_images_for_job,
    get_job,
    save_mappings,
    update_job_status,
)
from backend.services.pipeline import run_pipeline

router = APIRouter()


class AnonymizeBody(BaseModel):
    model: Optional[str] = None
    llm_endpoint: Optional[str] = None


def _strip_job_images(conn, job_id: str, output_dir: Path) -> None:
    """
    Remove images marked for removal from the anonymized output files.

    Called after run_pipeline writes the format-preserving output.  If the user
    never visited the image review screen the images table will be empty and this
    is a no-op, which is correct: images are only stripped after explicit review.
    """
    from backend.services.file_writer import strip_images_from_pdf, strip_images_from_docx

    images = get_images_for_job(conn, job_id)
    if not images:
        return

    # Group marked-for-removal indices by filename
    by_file: dict = {}
    for img in images:
        if img['marked_for_removal']:
            fname = img['source_filename']
            by_file.setdefault(fname, set()).add(img['image_index'])

    for filename, indices in by_file.items():
        output_path = output_dir / filename
        if not output_path.exists():
            continue

        ext = Path(filename).suffix.lower()
        tmp = output_path.with_suffix(output_path.suffix + '.strip_tmp')
        try:
            if ext == '.pdf':
                strip_images_from_pdf(output_path, tmp, indices)
            elif ext == '.docx':
                strip_images_from_docx(output_path, tmp, indices)
            else:
                continue
            if tmp.exists():
                tmp.replace(output_path)
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception:
                    pass


def _get_staged_paths(output_dir: Path, job_id: str, file_records: list) -> list:
    """Resolve input file paths from staging directory."""
    staging_dir = output_dir / job_id / "input"
    paths = []
    for rec in file_records:
        p = staging_dir / rec["filename"]
        if p.exists():
            paths.append(p)
    return paths


def _run_and_store(job_id: str, request: Request, progress_cb=None, overrides: Optional[dict] = None) -> dict:
    """Run the pipeline and persist results; return response payload."""
    config: dict = dict(request.app.state.config)
    if overrides:
        if overrides.get("model"):
            config["default_model"] = overrides["model"]
        if overrides.get("llm_endpoint"):
            config["llm_endpoint"] = overrides["llm_endpoint"]
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

        # Output directory for format-preserving files
        output_job_dir = output_dir / job_id / "output"

        pipeline_result = run_pipeline(
            job_id=job_id,
            file_paths=file_paths,
            config=config,
            progress_cb=progress_cb,
            output_dir=output_job_dir,
        )

        # Strip images that the user marked for removal (no-op if user skipped image review)
        _strip_job_images(conn, job_id, output_job_dir)

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

        # Determine job status
        has_warnings = bool(pipeline_result.warnings)
        status = "complete_with_warnings" if has_warnings else "complete"
        update_job_status(conn, job_id, status)

        return {
            "job_id": job_id,
            "status": status,
            "warnings": pipeline_result.warnings,
            "files": [
                {
                    "filename": fr.filename,
                    "anonymized_text": fr.anonymized_text,
                    "positions": fr.positions,
                    "file_type": fr.file_type,
                    "is_scanned": fr.is_scanned,
                    "is_password_protected": fr.is_password_protected,
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
def anonymize_job(job_id: str, request: Request, body: Optional[AnonymizeBody] = None):
    """Run the anonymization pipeline synchronously."""
    return _run_and_store(job_id, request, overrides=body.model_dump() if body else None)


@router.post("/jobs/{job_id}/anonymize/stream")
def anonymize_job_stream(job_id: str, request: Request, body: Optional[AnonymizeBody] = None):
    """
    SSE streaming version — emits progress events while the pipeline runs.
    Each event: data: {"step": "...", "message": "..."}\n\n
    """

    overrides = body.model_dump() if body else None

    def event_stream() -> Generator[str, None, None]:
        events: list = []

        def collect(step: str, msg: str = ""):
            events.append({"step": step, "message": msg})

        try:
            result = _run_and_store(job_id, request, progress_cb=collect, overrides=overrides)
        except HTTPException as exc:
            yield f"data: {json.dumps({'error': exc.detail})}\n\n"
            return

        # Emit collected progress events first
        for ev in events:
            yield f"data: {json.dumps(ev)}\n\n"

        # Final done event
        yield f"data: {json.dumps({'step': 'complete', 'status': 'complete'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
