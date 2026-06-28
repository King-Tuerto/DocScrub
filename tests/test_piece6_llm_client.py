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
