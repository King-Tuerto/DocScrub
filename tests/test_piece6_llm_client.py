"""
Piece 6 — LLM Client

Tests:
- Happy path: returns list[PIIFinding] from valid JSON response
- LLM returns garbage JSON → empty list + warning flag set
- LLM returns empty array → empty list, no warning
- LLM unreachable → raises LLMUnreachableError
- LLM timeout → raises LLMUnreachableError
- Large text is chunked; chunks overlap by ~200 tokens
- Each chunk sent with the correct system prompt
- Retry logic: retries once on transient failure
- Model list fetched from /api/tags (Ollama format)
- source field on all findings is 'llm'
- Partial/malformed JSON items are skipped gracefully
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from conftest import (
    KNOWN_PII,
    SAMPLE_PII_TEXT,
    VALID_LLM_JSON,
    GARBAGE_LLM_RESPONSE,
    EMPTY_LLM_RESPONSE,
    PARTIAL_VALID_LLM_RESPONSE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LLM_ENDPOINT = "http://localhost:11434"
MODEL = "llama3.1:8b"


def make_chat_response(content: str) -> dict:
    return {"choices": [{"message": {"content": content}}]}


def make_client(endpoint=LLM_ENDPOINT, model=MODEL):
    from backend.services.llm_client import LLMClient
    return LLMClient(endpoint=endpoint, model=model)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestLLMClientHappyPath:
    def test_returns_list_of_findings(self, mock_llm_endpoint):
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        assert isinstance(findings, list)

    def test_findings_are_pii_finding_instances(self, mock_llm_endpoint):
        from backend.models.schemas import PIIFinding
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        for f in findings:
            assert isinstance(f, PIIFinding)

    def test_person_detected(self, mock_llm_endpoint):
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        texts = [f.text for f in findings]
        assert KNOWN_PII["person"] in texts

    def test_email_detected(self, mock_llm_endpoint):
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        texts = [f.text for f in findings]
        assert KNOWN_PII["email"] in texts

    def test_source_field_is_llm(self, mock_llm_endpoint):
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        assert all(f.source == "llm" for f in findings)

    def test_warning_flag_not_set_on_success(self, mock_llm_endpoint):
        client = make_client()
        client.detect_pii(SAMPLE_PII_TEXT)
        assert client.last_warning is None


# ---------------------------------------------------------------------------
# Garbage / malformed LLM response
# ---------------------------------------------------------------------------

class TestLLMGarbageResponse:
    def test_garbage_json_returns_empty_list(self, mock_llm_garbage):
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        assert findings == []

    def test_garbage_json_sets_warning(self, mock_llm_garbage):
        client = make_client()
        client.detect_pii(SAMPLE_PII_TEXT)
        assert client.last_warning is not None
        assert "fallback" in client.last_warning.lower() or "warning" in client.last_warning.lower()

    def test_empty_array_returns_empty_list_no_warning(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(EMPTY_LLM_RESPONSE),
        )
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        assert findings == []
        assert client.last_warning is None

    def test_partial_items_skipped(self, httpx_mock):
        """Items missing required fields should be skipped, not raise."""
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(PARTIAL_VALID_LLM_RESPONSE),
        )
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        # Should not raise; may return whatever valid items exist
        assert isinstance(findings, list)

    def test_null_response_content_returns_empty(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json={"choices": [{"message": {"content": None}}]},
        )
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        assert findings == []


# ---------------------------------------------------------------------------
# LLM unreachable / timeout
# ---------------------------------------------------------------------------

class TestLLMUnreachable:
    def test_raises_llm_unreachable_error(self, mock_llm_unreachable):
        from backend.services.llm_client import LLMUnreachableError
        client = make_client()
        with pytest.raises(LLMUnreachableError):
            client.detect_pii(SAMPLE_PII_TEXT)

    def test_error_message_mentions_ollama(self, mock_llm_unreachable):
        from backend.services.llm_client import LLMUnreachableError
        client = make_client()
        try:
            client.detect_pii(SAMPLE_PII_TEXT)
        except LLMUnreachableError as e:
            assert "ollama" in str(e).lower() or "running" in str(e).lower()

    def test_timeout_raises_llm_unreachable(self, httpx_mock):
        import httpx
        from backend.services.llm_client import LLMUnreachableError
        httpx_mock.add_exception(
            httpx.TimeoutException("timed out"),
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
        )
        client = make_client()
        with pytest.raises(LLMUnreachableError):
            client.detect_pii(SAMPLE_PII_TEXT)


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

class TestRetryLogic:
    def test_retries_once_on_server_error(self, httpx_mock):
        """On HTTP 500, client should retry once before raising."""
        import httpx
        # First call: 500 error
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            status_code=500,
        )
        # Second call: success
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(VALID_LLM_JSON),
        )
        client = make_client()
        findings = client.detect_pii(SAMPLE_PII_TEXT)
        assert isinstance(findings, list)

    def test_raises_after_two_failures(self, httpx_mock):
        from backend.services.llm_client import LLMUnreachableError
        for _ in range(2):
            httpx_mock.add_response(
                method="POST",
                url=f"{LLM_ENDPOINT}/v1/chat/completions",
                status_code=500,
            )
        client = make_client()
        with pytest.raises((LLMUnreachableError, Exception)):
            client.detect_pii(SAMPLE_PII_TEXT)


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

class TestTextChunking:
    def test_large_text_sent_in_multiple_chunks(self, httpx_mock, large_text):
        """A text larger than the token limit should trigger multiple POST requests."""
        # Register enough responses for multiple chunks
        for _ in range(20):
            httpx_mock.add_response(
                method="POST",
                url=f"{LLM_ENDPOINT}/v1/chat/completions",
                json=make_chat_response(VALID_LLM_JSON),
            )
        client = make_client()
        client.detect_pii(large_text)
        requests = httpx_mock.get_requests()
        post_requests = [r for r in requests if r.method == "POST"]
        assert len(post_requests) > 1, "Large text should be split into multiple chunks"

    def test_chunks_overlap_boundary_pii_not_missed(self, httpx_mock):
        """
        PII placed exactly at a chunk boundary must appear in at least one chunk.
        We verify by checking that the client sends it in some request.
        """
        boundary_text = ("x " * 1000) + f" {KNOWN_PII['ssn']} " + ("y " * 1000)
        for _ in range(10):
            httpx_mock.add_response(
                method="POST",
                url=f"{LLM_ENDPOINT}/v1/chat/completions",
                json=make_chat_response(EMPTY_LLM_RESPONSE),
            )
        client = make_client()
        client.detect_pii(boundary_text)
        requests = httpx_mock.get_requests()
        bodies = [
            json.loads(r.content.decode())
            for r in requests if r.method == "POST"
        ]
        # The SSN should appear in at least one chunk's user message
        all_content = " ".join(
            msg["content"]
            for body in bodies
            for msg in body.get("messages", [])
        )
        assert KNOWN_PII["ssn"] in all_content

    def test_chunk_size_is_configurable(self):
        from backend.services.llm_client import LLMClient
        client = LLMClient(endpoint=LLM_ENDPOINT, model=MODEL, chunk_tokens=512)
        assert client.chunk_tokens == 512

    def test_chunk_overlap_is_200_tokens_default(self):
        from backend.services.llm_client import LLMClient
        client = LLMClient(endpoint=LLM_ENDPOINT, model=MODEL)
        assert client.overlap_tokens == 200


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_system_prompt_injected(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(EMPTY_LLM_RESPONSE),
        )
        client = make_client()
        client.detect_pii("Hello world.")
        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content.decode())
        messages = body.get("messages", [])
        system_messages = [m for m in messages if m.get("role") == "system"]
        assert len(system_messages) == 1

    def test_system_prompt_contains_json_instruction(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(EMPTY_LLM_RESPONSE),
        )
        client = make_client()
        client.detect_pii("Hello world.")
        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content.decode())
        messages = body.get("messages", [])
        system_content = next(
            m["content"] for m in messages if m.get("role") == "system"
        )
        assert "JSON" in system_content or "json" in system_content

    def test_system_prompt_mentions_pii_types(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(EMPTY_LLM_RESPONSE),
        )
        client = make_client()
        client.detect_pii("Hello world.")
        requests = httpx_mock.get_requests()
        body = json.loads(requests[0].content.decode())
        messages = body.get("messages", [])
        system_content = next(
            m["content"] for m in messages if m.get("role") == "system"
        )
        assert "PERSON" in system_content


# ---------------------------------------------------------------------------
# Model list
# ---------------------------------------------------------------------------

class TestModelList:
    def test_fetch_models_returns_list(self, mock_llm_endpoint):
        client = make_client()
        models = client.list_models()
        assert isinstance(models, list)
        assert len(models) >= 1

    def test_fetch_models_returns_strings(self, mock_llm_endpoint):
        client = make_client()
        models = client.list_models()
        for m in models:
            assert isinstance(m, str)

    def test_model_list_endpoint_unreachable_raises(self, httpx_mock):
        import httpx
        from backend.services.llm_client import LLMUnreachableError
        httpx_mock.add_exception(
            httpx.ConnectError("refused"),
            url=f"{LLM_ENDPOINT}/api/tags",
        )
        client = make_client()
        with pytest.raises(LLMUnreachableError):
            client.list_models()


# ---------------------------------------------------------------------------
# System prompt — few-shot example
# ---------------------------------------------------------------------------

class TestSystemPromptFewShot:
    def _get_system_content(self, httpx_mock):
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response(EMPTY_LLM_RESPONSE),
        )
        client = make_client()
        client.detect_pii("Hello world.")
        body = json.loads(httpx_mock.get_requests()[0].content.decode())
        return next(m["content"] for m in body["messages"] if m["role"] == "system")

    def test_prompt_contains_example_input(self, httpx_mock):
        """Prompt must show a concrete example input sentence."""
        content = self._get_system_content(httpx_mock)
        assert "Example input" in content or "example input" in content

    def test_prompt_contains_example_output(self, httpx_mock):
        """Prompt must show a concrete example output array."""
        content = self._get_system_content(httpx_mock)
        assert "Example output" in content or "example output" in content

    def test_prompt_example_shows_object_not_nested_array(self, httpx_mock):
        """The example output must use {curly braces}, not nested arrays."""
        content = self._get_system_content(httpx_mock)
        # A valid few-shot example must contain at least one JSON object literal
        assert '{"text"' in content

    def test_prompt_warns_against_nested_arrays(self, httpx_mock):
        """Prompt must explicitly state elements must be objects, not arrays."""
        content = self._get_system_content(httpx_mock)
        lower = content.lower()
        assert "object" in lower or "curly" in lower or "nested" in lower


# ---------------------------------------------------------------------------
# Warning logging — garbage response emits a log record
# ---------------------------------------------------------------------------

class TestWarningLogging:
    def test_garbage_json_emits_log_warning(self, mock_llm_garbage, caplog):
        """_parse_response must call logger.warning when JSON is unparseable."""
        import logging
        client = make_client()
        with caplog.at_level(logging.WARNING, logger="backend.services.llm_client"):
            client.detect_pii(SAMPLE_PII_TEXT)
        assert len(caplog.records) >= 1
        msgs = " ".join(r.getMessage() for r in caplog.records).lower()
        assert "fallback" in msgs or "parse" in msgs or "json" in msgs

    def test_non_list_json_emits_log_warning(self, httpx_mock, caplog):
        """_parse_response must log when the JSON is valid but not an array."""
        import logging
        httpx_mock.add_response(
            method="POST",
            url=f"{LLM_ENDPOINT}/v1/chat/completions",
            json=make_chat_response('{"text": "John", "type": "PERSON", "confidence": "high"}'),
        )
        client = make_client()
        with caplog.at_level(logging.WARNING, logger="backend.services.llm_client"):
            client.detect_pii(SAMPLE_PII_TEXT)
        assert len(caplog.records) >= 1


# ---------------------------------------------------------------------------
# SSE stream — warnings included in complete event
# ---------------------------------------------------------------------------

class TestStreamWarnings:
    def test_stream_complete_event_includes_warnings(self, app_client, sample_pdf_path, mock_llm_garbage):
        """When LLM returns garbage, the SSE complete event must carry warnings[]."""
        with open(sample_pdf_path, "rb") as fh:
            upload = app_client.post(
                "/upload",
                files={"files": (sample_pdf_path.name, fh, "application/pdf")},
            )
        job_id = upload.json()["job_id"]

        with app_client.stream("POST", f"/jobs/{job_id}/anonymize/stream") as resp:
            assert resp.status_code == 200
            complete_event = None
            buf = ""
            for chunk in resp.iter_text():
                buf += chunk
                for line in buf.split("\n"):
                    if line.startswith("data:"):
                        try:
                            ev = json.loads(line[5:].strip())
                            if ev.get("step") == "complete":
                                complete_event = ev
                        except json.JSONDecodeError:
                            pass
                buf = buf.split("\n")[-1]  # keep incomplete line

        assert complete_event is not None, "No complete event found in SSE stream"
        assert "warnings" in complete_event, "complete event must have a 'warnings' key"
        assert isinstance(complete_event["warnings"], list)
        # With garbage LLM, at least one warning about LLM fallback must be present
        assert len(complete_event["warnings"]) >= 1
