"""
Anonymization pipeline — orchestrates extract → detect → map → replace.

Called by both the JSON route and the SSE streaming route.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Generator, List, Optional

from backend.services.file_reader import extract_file
from backend.services.image_extractor import extract_images
from backend.services.llm_client import LLMClient, LLMUnreachableError
from backend.services.mapper import MappingTable, build_mapping
from backend.services.regex_engine import run_regex_engine
from backend.services.replacer import (
    ReplacementResult,
    apply_replacements,
    apply_replacements_to_document,
)


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


@dataclass
class PipelineResult:
    job_id: str
    files: List[FileResult] = field(default_factory=list)
    mapping: MappingTable = field(default_factory=MappingTable)
    warning: Optional[str] = None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    job_id: str,
    file_paths: List[Path],
    config: dict,
    progress_cb: Optional[Callable[[str, str], None]] = None,
) -> PipelineResult:
    """
    Run the full anonymization pipeline on a list of files.

    progress_cb(step, message) is called at each pipeline step if provided.
    """

    def emit(step: str, msg: str = ""):
        if progress_cb:
            progress_cb(step, msg)

    result = PipelineResult(job_id=job_id)
    warning: Optional[str] = None

    # --- Step 1: Extract text from all files --------------------------------
    emit("extract", "Extracting text from documents")
    extracted_docs = []
    for path in file_paths:
        doc = extract_file(path)
        extracted_docs.append(doc)

    # --- Step 2: Combine all body texts for LLM detection ------------------
    emit("llm_detect", "Detecting PII with LLM")
    all_text = "\n\n".join(
        d.body_text + " " + d.header_text + " " + d.footer_text
        for d in extracted_docs
    )

    llm_findings = []
    llm_client = LLMClient(
        endpoint=config.get("llm_endpoint", "http://localhost:11434"),
        model=config.get("default_model", "llama3.1:8b"),
    )
    try:
        llm_findings = llm_client.detect_pii(all_text)
        if llm_client.last_warning:
            warning = llm_client.last_warning
    except LLMUnreachableError as exc:
        warning = str(exc)

    # --- Step 3: Regex detection -------------------------------------------
    emit("regex_detect", "Running regex safety net")
    custom_patterns = config.get("custom_regex_patterns", [])
    regex_findings = run_regex_engine(all_text, custom_patterns)

    # --- Step 4: Merge + build mapping -------------------------------------
    emit("map", "Building replacement mapping")
    all_findings = llm_findings + regex_findings
    mapping = build_mapping(all_findings)

    # --- Step 5: Apply replacements to each file ---------------------------
    emit("replace", "Applying replacements")
    file_results: List[FileResult] = []
    for doc in extracted_docs:
        replaced = apply_replacements(doc.body_text, mapping)
        file_results.append(FileResult(
            filename=doc.filename,
            original_text=doc.body_text,
            anonymized_text=replaced.text,
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

    result.files = file_results
    result.mapping = mapping
    result.warning = warning

    emit("done", "Pipeline complete")
    return result
