"""
Anonymization pipeline — orchestrates extract → detect → map → replace → write.

FileResult gains is_scanned / is_password_protected / file_type flags.
PipelineResult collects warnings as a list (not a single string).
run_pipeline accepts an optional output_dir; when provided it writes
format-preserving output files (real PDF/DOCX, not plain text).

Tiers:
  'full'           — LLM + regex (default, existing behaviour)
  'names'          — roster-only name matching, no LLM, no regex
  'names_patterns' — roster names + regex, no LLM
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from backend.services.file_reader import extract_file

logger = logging.getLogger(__name__)
from backend.services.llm_client import LLMClient, LLMUnreachableError
from backend.services.mapper import MappingEntry, MappingTable, build_mapping
from backend.services.regex_engine import run_regex_engine
from backend.services.replacer import apply_replacements


_VALID_TIERS = {"full", "names", "names_patterns"}


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
    tier: str = "full"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    job_id: str,
    file_paths: List[Path],
    config: dict,
    progress_cb: Optional[Callable[[str, str], None]] = None,
    output_dir: Optional[Path] = None,
    roster_entries=None,
    tier: str = "full",
) -> PipelineResult:
    """
    Run the anonymization pipeline on a list of files.

    progress_cb(step, message) is called at each pipeline step if provided.
    output_dir: when provided, format-preserving output files are written here.
    roster_entries: list of RosterEntry objects used in 'names' and 'names_patterns' tiers.
    tier: 'full' | 'names' | 'names_patterns'
    """

    if tier not in _VALID_TIERS:
        raise ValueError(
            f"Invalid tier {tier!r}. Must be one of: {', '.join(sorted(_VALID_TIERS))}"
        )

    def emit(step: str, msg: str = ""):
        if progress_cb:
            progress_cb(step, msg)

    logger.info("Pipeline start — job=%s files=%d tier=%s", job_id, len(file_paths), tier)
    result = PipelineResult(job_id=job_id, tier=tier)

    # --- Step 1: Extract text from all files --------------------------------
    emit("extract", "Extracting text from documents")

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

    skipped = len(file_paths) - len(processable)
    if skipped:
        logger.warning("Skipped %d file(s) (scanned or password-protected)", skipped)
    logger.info("Processable files: %d", len(processable))

    if not processable:
        return result

    extracted_docs = [item[0] for item in processable]

    # --- Step 2: Combine all body texts for detection -----------------------
    def _doc_to_combined_text(d) -> str:
        parts = [d.body_text, d.header_text, d.footer_text]
        if d.table_cells:
            for row in d.table_cells:
                parts.append(" ".join(cell for cell in row if cell))
        return " ".join(p for p in parts if p)

    all_text = "\n\n".join(_doc_to_combined_text(d) for d in extracted_docs)
    logger.info("Combined text length: %d chars", len(all_text))

    # --- Step 3: LLM detection (full tier only) -----------------------------
    llm_findings = []
    if tier == "full":
        llm_endpoint = config.get("llm_endpoint", "http://localhost:11434")
        llm_model = config.get("default_model", "llama3.1:8b")
        logger.info("LLM detection — endpoint=%s model=%s", llm_endpoint, llm_model)

        llm_client = LLMClient(endpoint=llm_endpoint, model=llm_model)
        try:
            llm_findings = llm_client.detect_pii(all_text, progress_cb=emit)
            logger.info("LLM returned %d finding(s)", len(llm_findings))
            if llm_client.last_warning:
                logger.warning("LLM response warning: %s", llm_client.last_warning)
                result.warnings.append(llm_client.last_warning)
        except LLMUnreachableError as exc:
            logger.warning("LLM unreachable — falling back to regex-only: %s", exc)
            result.warnings.append(
                f"LLM fallback: {exc}. Falling back to regex-only detection."
            )

    # --- Step 4: Regex detection (full and names_patterns tiers) -----------
    regex_findings = []
    if tier in ("full", "names_patterns"):
        emit("regex_detect", "Running regex safety net")
        custom_patterns = config.get("custom_regex_patterns", [])
        regex_findings = run_regex_engine(all_text, custom_patterns)
        logger.info("Regex returned %d finding(s)", len(regex_findings))

    # --- Step 5: Build mapping ---------------------------------------------
    emit("map", "Building replacement mapping")

    if tier == "full":
        # Optional roster pass — run first so roster names take priority
        roster_mapping = MappingTable(entries=[])
        if roster_entries:
            from backend.services.name_matcher import build_name_mapping
            roster_mapping = build_name_mapping(roster_entries, text=all_text)
            logger.info(
                "Full tier roster: %d name variants for %d student(s)",
                len(roster_mapping.entries), len(roster_entries),
            )

        # Filter LLM + regex findings: skip text already covered by roster
        roster_originals = {e.original for e in roster_mapping.entries}
        extra_findings = [
            f for f in (llm_findings + regex_findings)
            if f.text not in roster_originals
        ]
        extra_mapping = build_mapping(extra_findings)
        logger.info(
            "Merging: %d LLM + %d regex (%d after roster dedup), %d roster variants",
            len(llm_findings), len(regex_findings),
            len(extra_findings), len(roster_mapping.entries),
        )

        # Renumber extra PERSON entries to avoid collision with roster [PERSON_N]
        person_count = len({
            e.placeholder for e in roster_mapping.entries if e.pii_type == "PERSON"
        })
        if person_count:
            shifted: list = []
            for e in extra_mapping.entries:
                if e.pii_type == "PERSON":
                    old_n = int(e.placeholder[len("[PERSON_"):-1])
                    e = MappingEntry(
                        original=e.original,
                        placeholder=f"[PERSON_{old_n + person_count}]",
                        pii_type=e.pii_type,
                        source=e.source,
                    )
                shifted.append(e)
            extra_mapping = MappingTable(entries=shifted)

        mapping = MappingTable(entries=roster_mapping.entries + extra_mapping.entries)

    elif tier == "names":
        if not roster_entries:
            result.warnings.append(
                "No roster provided for 'names' tier — no name replacements will be made."
            )
            mapping = MappingTable(entries=[])
        else:
            from backend.services.name_matcher import build_name_mapping
            mapping = build_name_mapping(roster_entries, text=all_text)

    else:  # names_patterns
        if not roster_entries:
            result.warnings.append(
                "No roster provided for 'names_patterns' tier — "
                "only regex patterns will be replaced."
            )
            name_mapping = MappingTable(entries=[])
        else:
            from backend.services.name_matcher import build_name_mapping
            name_mapping = build_name_mapping(roster_entries, text=all_text)
        regex_mapping = build_mapping(regex_findings)
        mapping = MappingTable(entries=name_mapping.entries + regex_mapping.entries)

    logger.info("Mapping table: %d unique entr(ies)", len(mapping.entries))

    # --- Step 6: Apply replacements and write format-preserving output ------
    emit("replace", "Applying replacements")

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    for doc, src_path in processable:
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

        if output_dir:
            _write_output_file(src_path, doc.filename, Path(output_dir), mapping)

    result.mapping = mapping

    logger.info("Pipeline complete — job=%s entries=%d warnings=%d tier=%s",
                job_id, len(mapping.entries), len(result.warnings), tier)
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
        # Non-fatal for the in-memory result, but log so it shows up in the server log
        logger.exception("Failed to write format-preserving output for %s", filename)
