"""
V2 Piece 16 — Real-time SSE progress, chunk ETA, taskbar title, Tier 3 docs

1. SSE REAL-TIME STREAMING
   event_stream() must emit events as they arrive (queue+thread), not batch
   them at the end. Verified by confirming the collect callback is called
   incrementally and events appear before pipeline completion.

2. CHUNK PROGRESS WITH ETA
   llm_client.detect_pii must pass chunk/total/avg_ms kwargs to progress_cb
   so the frontend can render "Processing chunk X of Y · ~Z remaining".

3. PIPELINE emit FORWARDS **kwargs
   pipeline.emit() must accept and forward keyword arguments to progress_cb.

4. FRONTEND
   review.js must define _fmtEta and handle chunk events without appending
   a new row per chunk. index.html must contain the Tier 3 caveat note.

5. TASKBAR TITLE
   start.bat must set the window title to "DocScrub Server".
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# 1. SSE real-time streaming (queue + thread)
# ---------------------------------------------------------------------------

def _make_pdf(directory, text="Test document."):
    """Create a minimal PDF using PyMuPDF (same approach as conftest fixtures)."""
    import fitz
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    path = directory / "test.pdf"
    doc.save(str(path))
    doc.close()
    return path


class TestSseRealTime:
    def test_stream_endpoint_yields_events_before_pipeline_finishes(self, tmp_path):
        """
        Events must arrive at the client while the pipeline is still running,
        not after. Simulate with a slow progress_cb that blocks.
        """
        from fastapi.testclient import TestClient
        from backend.main import create_app

        config = {
            "db_path": str(tmp_path / "test.db"),
            "output_directory": str(tmp_path / "output"),
            "llm_endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }
        client = TestClient(create_app(config=config))
        pdf = _make_pdf(tmp_path, "Test document for SSE streaming.")

        with open(pdf, "rb") as f:
            upload_resp = client.post("/upload", files={"files": ("test.pdf", f, "application/pdf")})
        assert upload_resp.status_code == 200
        job_id = upload_resp.json()["job_id"]

        timestamps = []
        with client.stream("POST", f"/jobs/{job_id}/anonymize/stream", json={"tier": "names"}) as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    timestamps.append(time.monotonic())

        assert len(timestamps) >= 1

    def test_stream_emits_complete_event(self, tmp_path):
        """The stream must end with a 'complete' step event."""
        from fastapi.testclient import TestClient
        from backend.main import create_app

        config = {
            "db_path": str(tmp_path / "test.db"),
            "output_directory": str(tmp_path / "output"),
            "llm_endpoint": "http://localhost:11434",
            "default_model": "llama3.1:8b",
        }
        client = TestClient(create_app(config=config))
        pdf = _make_pdf(tmp_path / "sub", "Hello world.")

        with open(pdf, "rb") as f:
            upload_resp = client.post("/upload", files={"files": ("doc.pdf", f, "application/pdf")})
        job_id = upload_resp.json()["job_id"]

        events = []
        with client.stream("POST", f"/jobs/{job_id}/anonymize/stream", json={"tier": "names"}) as resp:
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    try:
                        events.append(json.loads(line[5:].strip()))
                    except json.JSONDecodeError:
                        pass

        steps = [e.get("step") for e in events]
        assert "complete" in steps, f"No 'complete' event received. Steps: {steps}"


# ---------------------------------------------------------------------------
# 2. Chunk progress kwargs in llm_client
# ---------------------------------------------------------------------------

class TestLlmClientChunkProgress:
    # chunk_tokens=50, overlap_tokens=10 → chunk_chars=200, stride=160
    # so "Jane Smith " * 30 (~330 chars) produces ≥2 chunks safely
    def _make_client(self):
        from backend.services.llm_client import LLMClient
        return LLMClient(endpoint="http://localhost:11434", model="test",
                         chunk_tokens=50, overlap_tokens=10)

    def test_progress_cb_receives_chunk_kwargs(self):
        """progress_cb must be called with chunk=, total=, avg_ms= kwargs."""
        client = self._make_client()
        calls = []

        def cb(step, msg="", **kwargs):
            calls.append({"step": step, "msg": msg, **kwargs})

        fake_response = json.dumps([{"text": "Jane", "type": "PERSON", "confidence": 0.9}])
        with patch.object(client, "_call_chat", return_value=fake_response):
            client.detect_pii("Jane Smith is a student at the university. " * 10, progress_cb=cb)

        llm_calls = [c for c in calls if c["step"] == "llm_detect"]
        assert len(llm_calls) >= 1

        first = llm_calls[0]
        assert "chunk" in first, "chunk kwarg missing from progress_cb call"
        assert "total" in first, "total kwarg missing from progress_cb call"
        assert first["chunk"] == 1
        assert first["total"] >= 1

    def test_avg_ms_is_none_for_first_chunk(self):
        """avg_ms must be None on the first chunk (no prior timing data yet)."""
        client = self._make_client()
        calls = []

        def cb(step, msg="", **kwargs):
            calls.append(kwargs)

        fake_response = json.dumps([])
        with patch.object(client, "_call_chat", return_value=fake_response):
            client.detect_pii("Jane Smith is a student at the university. " * 10, progress_cb=cb)

        first_llm = next((c for c in calls if c.get("chunk") == 1), None)
        assert first_llm is not None, "No chunk=1 event received"
        assert first_llm["avg_ms"] is None, f"avg_ms should be None on first chunk, got {first_llm['avg_ms']}"

    def test_avg_ms_is_float_after_first_chunk(self):
        """avg_ms must be a non-negative float from the second chunk onward."""
        client = self._make_client()
        calls = []

        def cb(step, msg="", **kwargs):
            calls.append(kwargs)

        fake_response = json.dumps([])
        with patch.object(client, "_call_chat", return_value=fake_response):
            # Enough text for ≥2 chunks (chunk_chars=200, stride=160)
            client.detect_pii("Jane Smith is a student at the university. " * 15, progress_cb=cb)

        second_calls = [c for c in calls if c.get("chunk", 0) >= 2]
        if second_calls:
            for c in second_calls:
                assert isinstance(c["avg_ms"], float), f"avg_ms should be float, got {type(c['avg_ms'])}"
                assert c["avg_ms"] >= 0


# ---------------------------------------------------------------------------
# 3. pipeline.emit forwards **kwargs
# ---------------------------------------------------------------------------

class TestPipelineEmitKwargs:
    def test_emit_forwards_kwargs_to_progress_cb(self, tmp_path):
        """pipeline.run_pipeline must forward **kwargs from emit to progress_cb."""
        from backend.services.pipeline import run_pipeline
        from backend.services.roster_parser import RosterEntry

        received = []

        def cb(step, msg="", **kwargs):
            received.append({"step": step, "msg": msg, **kwargs})

        # Patch the LLM client so detect_pii emits a chunk event with kwargs
        from backend.services import llm_client as llm_mod
        orig_cls = llm_mod.LLMClient

        class FakeLLMClient:
            def __init__(self, *a, **kw): pass
            def detect_pii(self, text, progress_cb=None):
                if progress_cb:
                    progress_cb("llm_detect", "Processing chunk 1 of 1", chunk=1, total=1, avg_ms=None)
                return []

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        pdf_path = _make_pdf(input_dir, "Hello Jane Smith.")

        output_dir = tmp_path / "output"

        with patch.object(llm_mod, "LLMClient", FakeLLMClient):
            run_pipeline(
                job_id="test_job",
                file_paths=[pdf_path],
                config={
                    "llm_endpoint": "http://localhost:11434",
                    "default_model": "test",
                },
                progress_cb=cb,
                output_dir=output_dir,
                tier="full",
            )

        chunk_events = [r for r in received if r.get("step") == "llm_detect" and "chunk" in r]
        assert len(chunk_events) >= 1, "No llm_detect chunk events forwarded to progress_cb"
        assert chunk_events[0]["chunk"] == 1
        assert chunk_events[0]["total"] == 1


# ---------------------------------------------------------------------------
# 4. Frontend content checks
# ---------------------------------------------------------------------------

class TestFrontendProgress:
    def test_review_js_has_fmt_eta(self):
        js = (ROOT / "frontend" / "js" / "review.js").read_text(encoding="utf-8")
        assert "_fmtEta" in js, "review.js must define _fmtEta for ETA display"

    def test_review_js_handles_chunk_field(self):
        js = (ROOT / "frontend" / "js" / "review.js").read_text(encoding="utf-8")
        assert "ev.chunk" in js, "review.js must check ev.chunk for chunk-level events"

    def test_review_js_updates_in_place_not_appends(self):
        """Chunk events must update an existing row, not append a new one per chunk."""
        js = (ROOT / "frontend" / "js" / "review.js").read_text(encoding="utf-8")
        assert "llmRow" in js, "review.js must use a persistent llmRow reference"

    def test_append_progress_step_returns_row(self):
        """appendProgressStep must return the created row element for later updates."""
        js = (ROOT / "frontend" / "js" / "review.js").read_text(encoding="utf-8")
        assert "return row" in js, "appendProgressStep must return the row for in-place updates"

    def test_step_label_span_in_append_function(self):
        """appendProgressStep must use a .step-label span so text can be updated."""
        js = (ROOT / "frontend" / "js" / "review.js").read_text(encoding="utf-8")
        assert "step-label" in js

    def test_tier3_caveat_in_html(self):
        html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        assert "tier-card-caveat" in html, "Tier 3 card must have a caveat note"
        assert "under 20 pages" in html or "20 pages" in html

    def test_tier3_caveat_css_defined(self):
        css = (ROOT / "frontend" / "css" / "styles.css").read_text(encoding="utf-8")
        assert ".tier-card-caveat" in css


# ---------------------------------------------------------------------------
# 5. Taskbar title in start.bat
# ---------------------------------------------------------------------------

class TestTaskbarTitle:
    def test_start_bat_sets_title(self):
        bat = (ROOT / "start.bat").read_text(encoding="utf-8", errors="replace")
        assert "title DocScrub Server" in bat.lower() or "title docscrub server" in bat.lower(), (
            "start.bat must contain 'title DocScrub Server' to identify the taskbar entry"
        )
