# DocScrub — CLAUDE.md

## Project Overview

DocScrub is a local-first, browser-based document anonymizer. It strips PII from PDF and Word files using a self-hosted LLM (Ollama default) plus a regex safety net, producing anonymized outputs safe to send to cloud LLMs. Replacements are reversible via a local mapping table. Model-agnostic on the LLM side. No data leaves the machine except calls to the configured LLM endpoint.

This is **Phase 1** — standalone anonymizer only. Phase 2 (rubric grading for professors) is out of scope.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| Frontend | HTML / CSS / Vanilla JS (no framework) |
| PDF processing | PyMuPDF (fitz) |
| Word processing | python-docx |
| LLM client | httpx (OpenAI-compatible API) |
| Regex engine | Python `re` module |
| Database | SQLite3 (local only) |
| Distribution | PyInstaller + start.bat |

No frontend framework. This is a tool, not a SaaS. Vanilla JS keeps the dependency tree small and distribution trivial (~5 screens).

---

## Agent Roles

### El Código (architect / coder)
- Owns all implementation decisions
- Writes production code to pass Nitpick's tests
- Does not merge without Nitpick sign-off
- Breaks work into build pieces and presents them before writing a line

### Nitpick (tester / reviewer)
- Reviews the build plan before work begins
- Writes tests for each piece AND the assembled whole before El Código builds
- Runs tests after each build cycle; failures go back to El Código
- Reviews code quality, edge cases, and security after tests pass
- Recommends push only when all tests pass — never recommends merge

---

## TDD Workflow

```
Step 0  Branch repo (feature branch per piece of work)
Step 1  El Código breaks work into logical pieces → presents build plan
Step 2  Nitpick reviews plan → writes tests (unit + integration)
Step 3  El Código builds to pass the tests
Step 4  Nitpick runs tests + reviews code → failures return to El Código
        Loop until pass
Step 5  Nitpick recommends push
Step 6  Hold PR — do not merge until owner approves
```

**Rule:** No code is committed without a Nitpick review. No PR is merged without owner approval.

---

## Architecture — Three Layers

### 1. File Layer
- Reads `.pdf` (PyMuPDF) and `.docx` (python-docx)
- Extracts raw text preserving structure (including tables)
- Extracts embedded images for user review
- Identifies headers/footers as separate structural elements
- Writes anonymized output in same format as input

### 2. Anonymizer Layer
- Sends text to local LLM via OpenAI-compatible API (chunked, 200-token overlap)
- Runs regex safety net independently (SSN, email, phone, ZIP, URLs, IDs)
- Merges LLM + regex findings, deduplicates
- Builds reversible mapping: real value → typed placeholder (`[PERSON_1]`, `[EMAIL_2]`, etc.)
- Same real value always maps to same placeholder within a job
- Applies replacements to document text and headers/footers

### 3. Storage Layer
- SQLite, local only, never network
- Stores mapping tables per job (timestamped, named)
- User can purge via settings

---

## Key Architectural Decisions

1. **LLM returns JSON only** — structured output `[{text, type, confidence}]`. Validation layer checks structure; falls back to regex-only with a warning if LLM returns garbage.
2. **Regex runs independently** — not as a post-filter on LLM output. Merge happens after both complete.
3. **Chunked LLM input** — text split at token limit with 200-token overlap to catch PII spanning chunk boundaries.
4. **Typed, consistent placeholders** — `[PERSON_1]`, `[ORG_2]`, etc. Same real value → same placeholder within a job. Cross-references preserved.
5. **Images are user-reviewed before scrub** — extracted thumbnails shown in a grid; user unchecks what to keep (charts, diagrams). Checked images stripped from output.
6. **Localhost only** — FastAPI binds to `127.0.0.1:8000` by default. Not exposed to network.
7. **No frontend framework** — HTML + CSS + Vanilla JS. Keeps distribution as a simple zip.
8. **Scanned PDFs are rejected** — text extraction yielding empty triggers a user-facing warning; OCR is Phase 2.

---

## File Structure

```
DockScrub/
├── ANONYMIZER-SPEC.md
├── CLAUDE.md
├── start.bat
├── config.json
├── docscrub.db
├── backend/
│   ├── main.py
│   ├── routes/
│   │   ├── upload.py
│   │   ├── anonymize.py
│   │   ├── review.py
│   │   ├── export.py
│   │   └── reidentify.py
│   ├── services/
│   │   ├── file_reader.py
│   │   ├── image_extractor.py
│   │   ├── llm_client.py
│   │   ├── regex_engine.py
│   │   ├── mapper.py
│   │   └── replacer.py
│   ├── models/
│   │   └── schemas.py
│   └── db/
│       └── database.py
├── frontend/
│   ├── index.html
│   ├── css/styles.css
│   └── js/
│       ├── app.js
│       ├── upload.js
│       ├── review.js
│       └── export.js
├── output/
├── mappings/
└── tests/
```

---

## PII Target List

| Category | Placeholder | Detection |
|---|---|---|
| Person names | `[PERSON_N]` | LLM |
| Organization names | `[ORG_N]` | LLM |
| Email addresses | `[EMAIL_N]` | Regex + LLM |
| Phone numbers | `[PHONE_N]` | Regex + LLM |
| Physical addresses | `[ADDRESS_N]` | LLM |
| Student/Employee IDs | `[ID_N]` | Regex + LLM |
| SSN / Tax IDs | `[SSN_N]` | Regex |
| Account numbers | `[ACCOUNT_N]` | Regex + LLM |
| Dates of birth | `[DOB_N]` | LLM |
| Unique identifiers | `[OTHER_N]` | LLM |
| Headers/Footers | (inline) | Structural extraction |
| Logos/Images | (stripped) | User review |

---

## Edge Cases (must handle)

- LLM unreachable → clear error, "Check Ollama is running"
- LLM returns garbage → fall back to regex-only, warn user
- Huge documents → chunk text, sequential processing, merge mappings
- Scanned PDFs → detect empty extraction, warn user, skip
- Password-protected files → detect and skip with message
- Overlapping PII → handle as separate entities (name + email in same span)
- PII in tables → extraction must preserve cell boundaries
- Mixed batch → PDF and .docx in same job, each routed to correct reader

---

## Known Gaps

None outstanding for Phase 1. All spec requirements met as of Piece 10.

---

## Success Criteria

1. Non-technical user installs and runs on Windows in under 10 minutes
2. 10-page Word doc anonymized in under 2 minutes on an 8B model
3. PII detection catches ≥95% of items in the target list
4. Reversible mapping restores 100% of replacements
5. No data leaves the local machine (except LLM API calls to configured endpoint)
