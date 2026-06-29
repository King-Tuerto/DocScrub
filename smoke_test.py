#!/usr/bin/env python3
"""
DocScrub end-to-end smoke test.

Expects a running server at http://127.0.0.1:8000.
Exit code 0 = all tests passed, 1 = at least one failed.

Usage: python smoke_test.py
       (smoke_test.bat manages server lifecycle; run via that for fresh-db tests)
"""

import io
import json
import sys

import httpx
from docx import Document

BASE = "http://127.0.0.1:8000"

# PII we embed in the test document
FIRST1, LAST1 = "Valentina", "Rosenstein"
FIRST2, LAST2 = "Marcus", "Okonkwo"
TEST_EMAIL = "valentina.rosenstein@smoketest.example"
TEST_PHONE = "555-867-5309"

_results: list[tuple[str, bool, str]] = []


def _ok(label: str) -> None:
    print(f"  [PASS] {label}")
    _results.append((label, True, ""))


def _fail(label: str, detail: str) -> None:
    print(f"  [FAIL] {label}")
    print(f"         {detail}")
    _results.append((label, False, detail))


def run(label: str, fn):
    """Run fn(); record PASS/FAIL.  Returns the fn() return value or None on failure."""
    try:
        result = fn()
        _ok(label)
        return result
    except Exception as exc:
        _fail(label, str(exc))
        return None


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

def _make_docx_bytes() -> bytes:
    doc = Document()
    doc.add_paragraph(
        f"Meeting notes for {FIRST1} {LAST1} and {FIRST2} {LAST2}."
    )
    doc.add_paragraph(f"Primary contact: {TEST_EMAIL}")
    doc.add_paragraph(f"Call back at: {TEST_PHONE}")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _docx_full_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=120.0)

    roster_id: str | None = None
    job_id: str | None = None

    # ------------------------------------------------------------------
    # A. Create roster
    # ------------------------------------------------------------------
    def step_a():
        nonlocal roster_id
        resp = client.post("/rosters", json={"name": "Smoke Test Roster"})
        assert resp.status_code == 200, f"POST /rosters {resp.status_code}: {resp.text}"
        roster_id = resp.json()["id"]

        csv_bytes = (
            "first_name,last_name\n"
            f"{FIRST1},{LAST1}\n"
            f"{FIRST2},{LAST2}\n"
        ).encode()
        resp2 = client.post(
            f"/rosters/{roster_id}/entries",
            files={"file": ("roster.csv", csv_bytes, "text/csv")},
        )
        assert resp2.status_code == 200, (
            f"POST /rosters/.../entries {resp2.status_code}: {resp2.text}"
        )
        count = resp2.json()["count"]
        assert count == 2, f"Expected 2 entries, got {count}"

    run("A. Create roster with 2 names", step_a)

    if roster_id is None:
        print("\n  Cannot continue without a roster. Aborting.")
        _summary()
        client.close()
        return

    # ------------------------------------------------------------------
    # B. Upload test DOCX
    # ------------------------------------------------------------------
    def step_b():
        nonlocal job_id
        docx_bytes = _make_docx_bytes()
        resp = client.post(
            "/upload",
            files={
                "files": (
                    "smoke_test.docx",
                    docx_bytes,
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document",
                )
            },
        )
        assert resp.status_code == 200, f"POST /upload {resp.status_code}: {resp.text}"
        job_id = resp.json()["job_id"]
        assert job_id, "No job_id in upload response"

    run("B. Upload test DOCX (in-memory)", step_b)

    if job_id is None:
        print("\n  Cannot continue without a job. Aborting.")
        _summary()
        client.close()
        return

    # ------------------------------------------------------------------
    # C. Tier 2 anonymization via SSE stream
    # ------------------------------------------------------------------
    def step_c():
        with client.stream(
            "POST",
            f"/jobs/{job_id}/anonymize/stream",
            json={"tier": "names_patterns", "roster_id": roster_id},
        ) as resp:
            assert resp.status_code == 200, (
                f"POST /anonymize/stream {resp.status_code}"
            )
            completed = False
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                ev = json.loads(line[5:].strip())
                if ev.get("error"):
                    raise RuntimeError(f"Pipeline error: {ev['error']}")
                if ev.get("step") == "complete":
                    completed = True
                    break
        assert completed, "Stream closed without a 'complete' event"

    run("C. Tier 2 anonymization (SSE stream)", step_c)

    # ------------------------------------------------------------------
    # D. Review — verify all PII replaced
    # ------------------------------------------------------------------
    def step_d():
        resp = client.get(f"/jobs/{job_id}/review")
        assert resp.status_code == 200, f"GET /review {resp.status_code}"
        files = resp.json().get("files", [])
        assert files, "No files in review response"
        anon = files[0]["anonymized_text"]

        problems = []
        if "[PERSON_" not in anon:
            problems.append("No [PERSON_N] placeholder found")
        if f"{FIRST1} {LAST1}" in anon:
            problems.append(f"Original name '{FIRST1} {LAST1}' still present")
        if f"{FIRST2} {LAST2}" in anon:
            problems.append(f"Original name '{FIRST2} {LAST2}' still present")
        if "[EMAIL_" not in anon:
            problems.append("No [EMAIL_N] placeholder found")
        if TEST_EMAIL in anon:
            problems.append(f"Original email still present")
        if "[PHONE_" not in anon:
            problems.append("No [PHONE_N] placeholder found")
        if TEST_PHONE in anon:
            problems.append(f"Original phone still present")

        if problems:
            raise AssertionError(
                "; ".join(problems) + f"\n         anonymized_text: {anon[:300]}"
            )

    run("D. Review — names, email, phone all replaced", step_d)

    # ------------------------------------------------------------------
    # E. Export DOCX — verify placeholder in file
    # ------------------------------------------------------------------
    exported_bytes: bytes | None = None

    def step_e():
        nonlocal exported_bytes
        resp = client.get(f"/jobs/{job_id}/export")
        assert resp.status_code == 200, f"GET /export {resp.status_code}: {resp.text}"
        exported_bytes = resp.content
        assert len(exported_bytes) > 100, "Exported file is suspiciously small"

        full_text = _docx_full_text(exported_bytes)
        assert "[PERSON_" in full_text, (
            f"[PERSON_N] not in exported DOCX text. Got: {full_text[:300]}"
        )
        assert f"{FIRST1} {LAST1}" not in full_text, (
            "Original name still present in exported DOCX"
        )

    run("E. Export DOCX — valid file, placeholder present", step_e)

    # ------------------------------------------------------------------
    # F. Export mapping JSON
    # ------------------------------------------------------------------
    mapping_dict: dict | None = None

    def step_f():
        nonlocal mapping_dict
        resp = client.get(f"/jobs/{job_id}/export/mapping")
        assert resp.status_code == 200, f"GET /export/mapping {resp.status_code}"
        mappings = resp.json()
        assert mappings, "Mapping list is empty"
        mapping_dict = {m["placeholder"]: m["original"] for m in mappings}
        assert mapping_dict, "Could not build placeholder→original dict"
        # Sanity: at least one PERSON placeholder present
        person_keys = [k for k in mapping_dict if k.startswith("[PERSON_")]
        assert person_keys, f"No [PERSON_N] keys in mapping. Keys: {list(mapping_dict)}"

    run("F. Export mapping JSON", step_f)

    # ------------------------------------------------------------------
    # G. Re-identify — verify original names restored in DOCX
    # ------------------------------------------------------------------
    def step_g():
        assert exported_bytes is not None, "No exported bytes (step E failed)"
        assert mapping_dict is not None, "No mapping (step F failed)"

        resp = client.post(
            "/reidentify",
            json={"job_id": job_id, "mapping": mapping_dict},
        )
        assert resp.status_code == 200, (
            f"POST /reidentify {resp.status_code}: {resp.text}"
        )

        restored_text = _docx_full_text(resp.content)
        assert LAST1 in restored_text or FIRST1 in restored_text, (
            f"Original name not restored. Got: {restored_text[:300]}"
        )
        person_keys = [k for k in mapping_dict if k.startswith("[PERSON_")]
        for key in person_keys:
            assert key not in restored_text, (
                f"Placeholder {key!r} still in re-identified DOCX"
            )

    run("G. Re-identify — original names restored in DOCX", step_g)

    # ------------------------------------------------------------------
    # H. Shutdown
    # ------------------------------------------------------------------
    def step_h():
        resp = client.post("/shutdown")
        assert resp.status_code == 200, f"POST /shutdown {resp.status_code}"

    run("H. POST /shutdown", step_h)

    client.close()
    _summary()


def _summary() -> None:
    total = len(_results)
    passed = sum(1 for _, ok, _ in _results if ok)
    print()
    print(f"  Result: {passed}/{total} passed")
    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
