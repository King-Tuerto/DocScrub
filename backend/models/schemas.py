"""
Pydantic data models for DocScrub.
All inter-service data is typed through these schemas.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class PIIType(str, Enum):
    PERSON  = "PERSON"
    ORG     = "ORG"
    EMAIL   = "EMAIL"
    PHONE   = "PHONE"
    ADDRESS = "ADDRESS"
    ID      = "ID"
    SSN     = "SSN"
    ACCOUNT = "ACCOUNT"
    DOB     = "DOB"
    OTHER   = "OTHER"


class Confidence(str, Enum):
    HIGH   = "high"
    MEDIUM = "medium"


class JobStatus(str, Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    COMPLETE   = "complete"
    ERROR      = "error"
    COMPLETE_WITH_WARNINGS = "complete_with_warnings"
    SKIPPED    = "skipped"


class FileType(str, Enum):
    PDF  = "pdf"
    DOCX = "docx"


# ---------------------------------------------------------------------------
# Core schemas
# ---------------------------------------------------------------------------

class PIIFinding(BaseModel):
    text:       str
    type:       PIIType
    confidence: Confidence
    source:     Optional[str] = None


class MappingEntry(BaseModel):
    original:    str
    placeholder: str
    pii_type:    str
    source:      Optional[str] = None


class Job(BaseModel):
    id:         str
    name:       str
    status:     JobStatus = JobStatus.PENDING
    created_at: datetime  = None  # type: ignore[assignment]

    def model_post_init(self, __context):
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc).replace(tzinfo=None))


class FileRecord(BaseModel):
    job_id:     str
    filename:   str
    file_type:  FileType
    size_bytes: int
    page_count: int

    @field_validator("size_bytes")
    @classmethod
    def size_must_be_positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("size_bytes must be non-negative")
        return v


class ImageRecord(BaseModel):
    job_id:             str = ""
    source_filename:    str
    page_number:        int
    image_index:        int
    marked_for_removal: bool = True
    image_bytes:        Optional[bytes] = None
    id:                 str = ""

    def model_post_init(self, __context):
        if not self.id:
            object.__setattr__(self, "id", str(uuid.uuid4()))


class ExportManifest(BaseModel):
    job_id:         str
    file_count:     int
    pii_items_found: int
    model_used:     str
    exported_at:    datetime = None  # type: ignore[assignment]

    def model_post_init(self, __context):
        if self.exported_at is None:
            object.__setattr__(self, "exported_at", datetime.now(timezone.utc).replace(tzinfo=None))


class ReidentifyRequest(BaseModel):
    job_id:  str
    mapping: Dict[str, str]

    @field_validator("mapping")
    @classmethod
    def mapping_must_not_be_empty(cls, v: Dict[str, str]) -> Dict[str, str]:
        if not v:
            raise ValueError("mapping must not be empty")
        return v


class ExtractedDocument(BaseModel):
    job_id:               str = ""
    filename:             str
    file_type:            FileType
    body_text:            str
    header_text:          str = ""
    footer_text:          str = ""
    page_count:           int
    is_scanned:           bool
    is_password_protected: bool
    table_cells:          Optional[List[List[str]]] = None
