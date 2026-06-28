"""
Anonymization pipeline — orchestrates extract → detect → map → replace → write.

FileResult gains is_scanned / is_password_protected / file_type flags.
PipelineResult collects warnings as a list (not a single string).
run_pipeline accepts an optional output_dir; when provided it writes
format-preserving output files (real PDF/DOCX, not plain text).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from backend.services.file_reader import extract_file
from backend.services.llm_client import LLMClient, LLMUnreachableError
from backend.services.mapper import MappingTable, build_mapping
from backend.services.regex_engine import run_regex_engine
from backend.services.replacer import apply_replacements


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FileResult:
    filename: str
    original_text: str
    anonymized_text: str
    positions: list = field(default_factory=list)
    warning: Optional[str] = None
    is_scanned: bool = False
    is_password_protected: bool = False
    file_type: str = ""


@dataclass
class PipelineResult:
    job_id: str
    files: List[FileResult] = field(default_factory=list)
    mapping: MappingTable = field(default_factory=MappingTable)
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    job_id: str,
    file_paths: List[Path],
    config: dict,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    output_dir: Optional[Path] = None,
) -> PipelineResult:
    """
    Run the full anonymization pipeline on a list of files.

    progress_cb(step, message) is called at each pipeline step if provided.
    output_dir: when provided, format-preserving output files are written here.
    """

    def emit(step: str, msg: str = ""):
        if progress_cb:
            progress_cb(step, msg)

    result = PipelineResult(job_id=job_id)

    # --- Step 1: Extract text from all files --------------------------------
    emit("extract", "Extracting text from documents")

    # Track (doc, source_path) together so we can write format-preserving output
    processable: List[Tuple] = []  # (ExtractedDocument, Path)

    for path in file_paths:
        doc = extract_file(path)

        if doc.is_password_protected:
            result.files.append(FileResult(
                filename=doc.filename,
                original_text="",
                anonymized_text="",
                file_type=doc.file_type.value,
                is_password_protected=True,
            ))
            result.warnings.append(
                f"Password-protected PDF ({doc.filename}): "
                "cannot process without the password. File skipped."
            )
            continue

        if doc.is_scanned:
            result.files.append(FileResult(
                filename=doc.filename,
                original_text="",
                anonymized_text="",
                file_type=doc.file_type.value,
                is_scanned=True,
            ))
            result.warnings.append(
                f"Scanned PDF detected ({doc.filename}): no text layer found. "
                "OCR is not supported in Phase 1. File skipped."
            )
            continue

        processable.append((doc, path))

    # If all files were skipped, return early with what we have
    if not processable:
        return result

    extracted_docs = [item[0] for item in processable]

    # --- Step 2: Combine all body texts + table cells for LLM detection ----
    emit("llm_detect", "Detecting PII with LLM")

    def _doc_to_combined_text(d) -> str:
        parts = [d.body_text, d.header_text, d.footer_text]
        if d.table_cells:
            for row in d.table_cells:
                parts.append(" ".join(cell for cell in row if cell))
        return " ".join(p for p in parts if p)

    all_text = "\n\n".join(_doc_to_combined_text(d) for d in extracted_docs)

    llm_findings = []
    llm_client = LLMClient(
        endpoint=config.get("llm_endpoint", "http://localhost:11434"),
        model=config.get("default_model", "llama3.1:8b"),
    )
    try:
        llm_findings = llm_client.detect_pii(all_text)
        if llm_client.last_warning:
            result.warnings.append(llm_client.last_warning)
    except LLMUnreachableError as exc:
        result.warnings.append(
            f"LLM fallback: {exc}. Falling back to regex-only detection."
        )

    # --- Step 3: Regex detection -------------------------------------------
    emit("regex_detect", "Running regex safety net")
    custom_patterns = config.get("custom_regex_patterns", [])
    regex_findings = run_regex_engine(all_text, custom_patterns)

    # --- Step 4: Merge + build mapping -------------------------------------
    emit("map", "Building replacement mapping")
    all_findings = llm_findings + regex_findings
    mapping = build_mapping(all_findings)

    # --- Step 5: Apply replacements and write format-preserving output ------
    emit("replace", "Applying replacements")

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    for doc, src_path in processable:
        # Text-level replacement (used for in-memory display / review)
        replaced = apply_replacements(doc.body_text, mapping)

        result.files.append(FileResult(
            filename=doc.filename,
            original_text=doc.body_text,
            anonymized_text=replaced.text,
            file_type=doc.file_type.value,
            positions=[
                {
                    "start": p.start,
                    "end": p.end,
                    "pii_type": p.pii_type,
                    "placeholder": p.placeholder,
                }
                for p in replaced.positions
            ],
        ))

        # Write format-preserving output file when output_dir is provided.
        # Always write even if mapping is empty so image stripping can operate.
        if output_dir:
            _write_output_file(src_path, doc.filename, Path(output_dir), mapping)

    result.mapping = mapping

    emit("done", "Pipeline complete")
    return result


# ---------------------------------------------------------------------------
# Format-preserving file output
# ---------------------------------------------------------------------------

def _write_output_file(
    src_path: Path,
    filename: str,
    output_dir: Path,
    mapping: MappingTable,
) -> None:
    """Write the anonymized version of a file to *output_dir* in its native format."""
    from backend.services.file_writer import write_anonymized_pdf, write_anonymized_docx

    output_path = output_dir / filename
    ext = Path(filename).suffix.lower()

    try:
        if ext == ".pdf":
            write_anonymized_pdf(src_path, output_path, mapping)
        elif ext == ".docx":
            write_anonymized_docx(src_path, output_path, mapping)
    except Exception:
        # Non-fatal: the in-memory anonymized_text is still correct
        pass
