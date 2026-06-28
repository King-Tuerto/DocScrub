"""
LLM client — OpenAI-compatible API (Ollama default).

Synchronous (httpx.Client). Chunks large text with 200-token overlap.
Falls back gracefully on garbage responses; raises LLMUnreachableError
when the endpoint cannot be reached.
"""

import json
import time
from typing import List, Optional

import httpx

from backend.models.schemas import PIIFinding, PIIType, Confidence

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LLMUnreachableError(Exception):
    """Raised when the LLM endpoint cannot be reached or times out."""


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a PII detection assistant. Analyse the text and return ONLY a JSON array of objects.

Each object must have exactly these fields:
  "text"       — the exact string as it appears in the input
  "type"       — one of: PERSON, ORG, EMAIL, PHONE, ADDRESS, ID, SSN, ACCOUNT, DOB, OTHER
  "confidence" — one of: "high", "medium"

Return [] if no PII is found. Do not include any explanation outside the JSON array.

Example:
[{"text": "Jane Smith", "type": "PERSON", "confidence": "high"},
 {"text": "jane@example.com", "type": "EMAIL", "confidence": "high"}]
"""

# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(
        self,
        endpoint: str,
        model: str,
        chunk_tokens: int = 2048,
        overlap_tokens: int = 200,
        timeout: float = 120.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.chunk_tokens = chunk_tokens
        self.overlap_tokens = overlap_tokens
        self.timeout = timeout
        self.last_warning: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_pii(self, text: str) -> List[PIIFinding]:
        """
        Detect PII in text. Chunks the input if needed. Returns a deduplicated
        list of PIIFinding objects with source="llm". Sets self.last_warning if
        the LLM returns non-parseable output.
        """
        self.last_warning = None
        chunks = self._chunk_text(text)
        seen: set = set()
        findings: List[PIIFinding] = []

        for chunk in chunks:
            raw = self._call_chat(chunk)
            chunk_findings = self._parse_response(raw)
            for f in chunk_findings:
                key = (f.text, f.type)
                if key not in seen:
                    seen.add(key)
                    findings.append(f)

        return findings

    def list_models(self) -> List[str]:
        """Fetch available models from Ollama /api/tags."""
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(f"{self.endpoint}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise LLMUnreachableError(
                f"Ollama is not running or not reachable at {self.endpoint}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Chunking
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks of ~chunk_tokens with overlap_tokens overlap."""
        # Approximate: 1 token ≈ 4 characters
        chunk_chars = self.chunk_tokens * 4
        overlap_chars = self.overlap_tokens * 4

        if len(text) <= chunk_chars:
            return [text]

        stride = chunk_chars - overlap_chars
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_chars
            chunks.append(text[start:end])
            if end >= len(text):
                break
            start += stride
        return chunks

    # ------------------------------------------------------------------
    # HTTP call with retry
    # ------------------------------------------------------------------

    def _call_chat(self, text: str) -> Optional[str]:
        """Call /v1/chat/completions, retry once on 5xx. Returns content string or None."""
        url = f"{self.endpoint}/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }

        last_exc = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=payload)
                if resp.status_code >= 500:
                    last_exc = Exception(f"HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
                raise LLMUnreachableError(
                    f"Ollama is not running or not reachable at {self.endpoint}: {exc}"
                ) from exc
            except (httpx.HTTPStatusError, KeyError, IndexError) as exc:
                last_exc = exc
                continue

        raise LLMUnreachableError(
            f"LLM endpoint returned repeated errors: {last_exc}"
        ) from last_exc

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, content: Optional[str]) -> List[PIIFinding]:
        """Parse LLM JSON response into PIIFinding list. Sets last_warning on failure."""
        if content is None:
            return []

        # Strip markdown code fences if present
        stripped = content.strip()
        if stripped.startswith("```"):
            lines = stripped.split("\n")
            stripped = "\n".join(lines[1:-1]) if len(lines) > 2 else stripped

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            self.last_warning = (
                "LLM returned non-JSON output — fallback to regex-only. "
                f"Raw: {content[:120]!r}"
            )
            return []

        if not isinstance(data, list):
            self.last_warning = (
                "LLM response was not a JSON array — fallback to regex-only."
            )
            return []

        if len(data) == 0:
            return []

        findings: List[PIIFinding] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                text_val = item.get("text")
                type_val = item.get("type")
                conf_val = item.get("confidence", "medium")
                if not text_val or not type_val:
                    continue
                finding = PIIFinding(
                    text=text_val,
                    type=PIIType(type_val),
                    confidence=Confidence(conf_val),
                    source="llm",
                )
                findings.append(finding)
            except (ValueError, KeyError):
                continue

        return findings
