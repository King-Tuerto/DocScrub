"""
LLM client — OpenAI-compatible API (Ollama default).

Synchronous (httpx.Client). Chunks large text with 200-token overlap.
Falls back gracefully on garbage responses; raises LLMUnreachableError
when the endpoint cannot be reached.
"""

import json
import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

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

Each object must have exactly these three fields:
  "text"       — the exact string as it appears in the input
  "type"       — MUST be one of these exact values: PERSON, ORG, EMAIL, PHONE, ADDRESS, ID, SSN, ACCOUNT, DOB, OTHER
                 Do NOT use ORGANIZATION, COMPANY, NAME, TELEPHONE, or any other variant. Use ONLY the values listed above.
  "confidence" — one of: "high", "medium"

Rules:
- Output ONLY the JSON array. No explanation, no markdown, no code fences.
- Each element must be a JSON object (curly braces), NOT a nested array.
- Return [] if no PII is found.

Example input: "John Smith works at Acme Corp. His email is john@acme.com and SSN is 123-45-6789."
Example output: [{"text": "John Smith", "type": "PERSON", "confidence": "high"}, {"text": "Acme Corp", "type": "ORG", "confidence": "high"}, {"text": "john@acme.com", "type": "EMAIL", "confidence": "high"}, {"text": "123-45-6789", "type": "SSN", "confidence": "high"}]
"""

# ---------------------------------------------------------------------------
# Type normalisation — map common LLM label variants to valid PIIType values
# ---------------------------------------------------------------------------

_TYPE_ALIASES: dict = {
    # ORG
    "ORGANIZATION": "ORG",
    "ORGANISATION": "ORG",
    "COMPANY":      "ORG",
    "BUSINESS":     "ORG",
    "CORPORATION":  "ORG",
    "INSTITUTION":  "ORG",
    "EMPLOYER":     "ORG",
    # PERSON
    "NAME":         "PERSON",
    "FULL_NAME":    "PERSON",
    "INDIVIDUAL":   "PERSON",
    "HUMAN":        "PERSON",
    # PHONE
    "TELEPHONE":    "PHONE",
    "MOBILE":       "PHONE",
    "MOBILE_PHONE": "PHONE",
    "TEL":          "PHONE",
    "CELL":         "PHONE",
    "PHONE_NUMBER": "PHONE",
    # SSN
    "SOCIAL_SECURITY":        "SSN",
    "SOCIAL_SECURITY_NUMBER": "SSN",
    "TAX_ID":                 "SSN",
    "TIN":                    "SSN",
    "NIN":                    "SSN",
    # ADDRESS
    "LOCATION":  "ADDRESS",
    "ADDR":      "ADDRESS",
    "RESIDENCE": "ADDRESS",
    # ACCOUNT
    "ACCOUNT_NUMBER": "ACCOUNT",
    "CREDIT_CARD":    "ACCOUNT",
    "BANK_ACCOUNT":   "ACCOUNT",
    # ID
    "EMPLOYEE_ID": "ID",
    "STUDENT_ID":  "ID",
    "IDENTIFIER":  "ID",
    "ID_NUMBER":   "ID",
    # DOB
    "DATE_OF_BIRTH": "DOB",
    "BIRTHDAY":      "DOB",
    "BIRTH_DATE":    "DOB",
    "DATE":          "DOB",
}

_VALID_PII_TYPES: frozenset = frozenset(
    "PERSON ORG EMAIL PHONE ADDRESS ID SSN ACCOUNT DOB OTHER".split()
)


def _normalize_type(raw: str) -> str:
    """Map non-standard LLM type labels to a valid PIIType value.

    Never drops a finding — unknown types fall back to OTHER so the text
    is still anonymised even if the category label is wrong.
    """
    upper = raw.strip().upper()
    if upper in _VALID_PII_TYPES:
        return upper
    canonical = _TYPE_ALIASES.get(upper)
    if canonical:
        return canonical
    logger.debug("Unknown PII type %r normalised to OTHER", raw)
    return "OTHER"

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
            logger.warning("LLM JSON parse failure: %s", self.last_warning)
            return []

        if not isinstance(data, list):
            self.last_warning = (
                "LLM response was not a JSON array — fallback to regex-only. "
                f"Got type: {type(data).__name__!r}, raw: {content[:120]!r}"
            )
            logger.warning("LLM response not a list: %s", self.last_warning)
            return []

        # Flatten one level of nesting — some models return [[{...}]] instead of [{...}].
        # This passes the isinstance(list) check above but all items fail isinstance(dict),
        # causing a silent empty result with no warning.
        if data and isinstance(data[0], list):
            flat = [item for sub in data for item in (sub if isinstance(sub, list) else [sub])]
            logger.warning(
                "LLM returned a nested array ([[...]]) — flattening automatically. "
                "Check system prompt if this recurs."
            )
            data = flat

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
                # Normalise type — never drop a finding for a bad label
                norm_type = _normalize_type(str(type_val))
                # Normalise confidence — accept HIGH/MEDIUM case-insensitively
                norm_conf = str(conf_val).lower() if str(conf_val).lower() in ("high", "medium") else "medium"
                finding = PIIFinding(
                    text=str(text_val),
                    type=PIIType(norm_type),
                    confidence=Confidence(norm_conf),
                    source="llm",
                )
                findings.append(finding)
            except Exception as exc:
                logger.debug("Skipping malformed item %r: %s", item, exc)
                continue

        return findings
