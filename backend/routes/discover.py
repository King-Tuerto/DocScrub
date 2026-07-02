"""
Discover route — POST /discover

Stateless PII scan. Accepts a single file, extracts text, runs the
regex engine (quick) or regex + LLM (deep), and returns a deduplicated
list of findings. Does NOT create a job, modify the database, or write
any output files.

Form fields:
  file          — uploaded PDF or DOCX
  method        — "quick" | "deep"  (default: "quick")
  llm_endpoint  — optional, for deep scan (falls back to app config)
  model         — optional, for deep scan (falls back to app config)

Response:
  {
    "filename": "...",
    "method": "quick",
    "findings": [{"text": "...", "pii_type": "EMAIL", "confidence": "high", "source": "regex"}, ...],
    "warnings": []
  }
"""

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from backend.services.file_reader import extract_file
from backend.services.regex_engine import run_regex_engine

router = APIRouter()


@router.post("/discover")
async def discover_pii(
    request: Request,
    file: UploadFile = File(...),
    method: str = Form("quick"),
    llm_endpoint: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
):
    """
    Scan a single document for PII and return findings without creating a job.
    """
    if method not in {"quick", "deep"}:
        raise HTTPException(status_code=422, detail="method must be 'quick' or 'deep'")

    filename = file.filename or "document"
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type {suffix!r}. Only PDF and DOCX are supported.",
        )

    data = await file.read()
    warnings: list[str] = []

    # Write to a temp file so extract_file can inspect the format
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)

        doc = extract_file(tmp_path)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)

    if doc.is_password_protected:
        raise HTTPException(
            status_code=422, detail="Password-protected files cannot be scanned."
        )
    if doc.is_scanned:
        raise HTTPException(
            status_code=422,
            detail="Scanned PDFs (no text layer) cannot be processed. OCR is not supported.",
        )

    # Combine body, headers, footers, and table cells
    parts = [doc.body_text, doc.header_text, doc.footer_text]
    if doc.table_cells:
        for row in doc.table_cells:
            parts.append(" ".join(cell for cell in row if cell))
    full_text = " ".join(p for p in parts if p)

    # --- Regex scan (always) ------------------------------------------------
    all_findings = list(run_regex_engine(full_text))

    # --- LLM scan (deep only) -----------------------------------------------
    if method == "deep":
        config: dict = request.app.state.config
        endpoint = llm_endpoint or config.get("llm_endpoint", "http://localhost:11434")
        mdl = model or config.get("default_model", "llama3.1:8b")
        try:
            from backend.services.llm_client import LLMClient, LLMUnreachableError  # noqa: F401
            client = LLMClient(endpoint=endpoint, model=mdl)
            llm_findings = client.detect_pii(full_text)
            all_findings.extend(llm_findings)
        except Exception as exc:
            warnings.append(
                f"LLM unavailable — results are regex-only. ({exc})"
            )

    # --- Deduplicate by (text_lower, pii_type) ------------------------------
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for f in all_findings:
        key = (f.text.lower(), f.type.value)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({
            "text": f.text,
            "pii_type": f.type.value,
            "confidence": f.confidence.value,
            "source": f.source or "regex",
        })

    return {
        "filename": filename,
        "method": method,
        "findings": deduped,
        "warnings": warnings,
    }
