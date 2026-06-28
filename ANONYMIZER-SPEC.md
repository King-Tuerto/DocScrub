# DocScrub — Standalone Document Anonymizer

## Overview

A local-first, browser-based tool that strips PII from PDF and Word documents using a self-hosted LLM + regex safety net. Produces anonymized files safe to send to cloud LLMs. Reversible — a local mapping table allows re-identification when needed. Model-agnostic on the LLM side.

This is **Phase 1** — a standalone anonymizer. Phase 2 (not in scope) adds rubric-based grading workflows for professors.

---

## Architecture

Three layers, loosely coupled:

### 1. File Layer
- Reads PDF (.pdf) and Word (.docx) files
- Extracts raw text preserving document structure
- Extracts embedded images for review
- Identifies headers/footers as separate structural elements
- Writes anonymized output in the same format as input

### 2. Anonymizer Layer
- Sends extracted text to any local LLM via OpenAI-compatible API (Ollama default)
- Runs regex safety net for pattern-based PII (SSN, email, phone, etc.)
- Merges LLM + regex findings, deduplicates
- Generates reversible mapping (real value → placeholder)
- Applies replacements to document text

### 3. Storage Layer
- SQLite database, local only, never touches the network
- Stores mapping tables per job
- Each job is timestamped and named for later retrieval

---

## PII Target List

The anonymizer detects and replaces:

| Category | Examples | Detection Method |
|---|---|---|
| Person names | Full names, first/last | LLM |
| Organization names | Companies, schools, agencies | LLM |
| Email addresses | user@domain.com | Regex + LLM |
| Phone numbers | All formats | Regex + LLM |
| Physical addresses | Street, city, state, zip | LLM |
| Student / Employee IDs | Numeric or alphanumeric codes | Regex + LLM |
| SSN / Tax IDs | XXX-XX-XXXX patterns | Regex |
| Account numbers | Bank, financial, policy numbers | Regex + LLM |
| Dates of birth | All date formats when contextually a DOB | LLM |
| Unique identifiers | Case numbers, loan numbers, etc. | LLM |
| Headers/Footers | Letterheads, footer text with PII | Structural extraction |
| Logos/Images | Letterheads, headshots, identifying images | User review panel |

---

## Replacement Strategy

Replacements are **consistent and typed**:

- Person names → `[PERSON_1]`, `[PERSON_2]`, etc.
- Organizations → `[ORG_1]`, `[ORG_2]`, etc.
- Emails → `[EMAIL_1]`, `[EMAIL_2]`, etc.
- Phone numbers → `[PHONE_1]`, `[PHONE_2]`, etc.
- Addresses → `[ADDRESS_1]`, `[ADDRESS_2]`, etc.
- IDs → `[ID_1]`, `[ID_2]`, etc.
- SSN/Tax → `[SSN_1]`, `[SSN_2]`, etc.
- Accounts → `[ACCOUNT_1]`, `[ACCOUNT_2]`, etc.
- DOB → `[DOB_1]`, `[DOB_2]`, etc.

Same real value always maps to same placeholder within a job. Cross-referencing is preserved (if "Jane Smith" appears 15 times, all become `[PERSON_1]`).

---

## User Workflow

### Step 1: Upload
User drags/drops one or more PDF or Word files into the app. Files are listed with filename, page count, and size.

### Step 2: Configure
- **LLM Endpoint**: URL field, defaults to `http://localhost:11434` (Ollama). User can change to any OpenAI-compatible endpoint.
- **Model**: Dropdown auto-populated from the endpoint's model list.

### Step 3: Image Review
Before anonymization runs, the app extracts all embedded images from all uploaded documents and displays them in a review panel as a thumbnail grid. Each image shows:
- Source document and page number
- Checkbox (default: checked for removal)

User unchecks any images they want to **keep** (charts, diagrams, graphs). Checked images will be stripped from the output.

### Step 4: Anonymize
User clicks "Scrub." Progress shown per document.

Processing pipeline per document:
1. Extract text (preserving structure)
2. Extract and process headers/footers separately
3. Send text to LLM with PII-detection prompt
4. Run regex patterns over same text
5. Merge findings, build mapping table
6. Apply replacements to document
7. Strip checked images
8. Replace header/footer PII
9. Generate anonymized output file

### Step 5: Review
Results screen shows:
- Side-by-side or diff view: original vs anonymized text
- Highlighted replacements (color-coded by PII type)
- Mapping table visible and editable (user can fix mistakes)
- User can manually flag missed PII or undo false positives

### Step 6: Export
- Download anonymized files (same format as input)
- Download mapping file (JSON) — for later re-identification
- Job saved to local SQLite with timestamp

### Re-identification (separate screen)
User uploads anonymized files + mapping file → app swaps placeholders back to real values → downloads restored files.

---

## LLM Prompt Strategy

The anonymizer prompt is critical. It must:

1. Instruct the model to identify ALL PII in the text
2. Return structured output (JSON) with each PII item, its type, and its location
3. Not attempt to analyze or summarize the content
4. Handle partial/ambiguous PII conservatively (flag it)

Example system prompt:
```
You are a PII detection engine. Your ONLY job is to find personally identifiable information in the text provided.

For each PII item found, return a JSON array of objects with:
- "text": the exact text as it appears in the document
- "type": one of [PERSON, ORG, EMAIL, PHONE, ADDRESS, ID, SSN, ACCOUNT, DOB, OTHER]
- "confidence": "high" or "medium"

Be aggressive — it is better to flag something that might be PII than to miss real PII.

Do NOT summarize, analyze, or comment on the content. Return ONLY the JSON array.
```

Text is sent in chunks if it exceeds the model's context window. Chunks overlap by 200 tokens to catch PII that spans chunk boundaries.

---

## Regex Safety Net

Runs independently of the LLM. Catches pattern-based PII the model might miss:

- **SSN**: `\d{3}-\d{2}-\d{4}` and variants
- **Email**: Standard email regex
- **Phone**: US formats `(xxx) xxx-xxxx`, `xxx-xxx-xxxx`, `xxx.xxx.xxxx`, `+1xxxxxxxxxx`
- **ZIP codes**: `\d{5}(-\d{4})?` (flagged, not auto-replaced — context needed)
- **URLs with PII**: Patterns containing usernames or IDs
- **Student ID patterns**: Configurable regex per institution

Results are merged with LLM findings. Duplicates removed. Net-new regex finds are added to the mapping.

---

## Tech Stack

| Component | Technology |
|---|---|
| Backend | Python 3.11+ / FastAPI |
| Frontend | HTML / CSS / JavaScript (no framework — keep it simple) |
| PDF processing | PyMuPDF (fitz) |
| Word processing | python-docx |
| LLM communication | httpx (OpenAI-compatible API) |
| Regex engine | Python `re` module |
| Database | SQLite3 |
| Bundling | PyInstaller or similar (for distribution) |

### Why no frontend framework
This is a tool, not a SaaS product. Vanilla JS keeps the dependency tree small, the build simple, and distribution easy. The UI is ~5 screens.

---

## Deployment Modes

### Self-contained (default)
Everything runs on one machine. User installs:
1. Ollama (one-click installer)
2. DocScrub (unzip and double-click `start.bat`)

`start.bat` launches the Python backend, opens the browser to `http://localhost:8000`.

### Server mode
App points to a remote Ollama instance on the network. User changes the LLM Endpoint URL in settings. Everything else identical.

---

## Configuration (saved to local config file)

```json
{
  "llm_endpoint": "http://localhost:11434",
  "default_model": "llama3.1:8b",
  "output_directory": "./output",
  "db_path": "./docscrub.db",
  "image_review_default": "remove",
  "custom_regex_patterns": []
}
```

---

## File Structure

```
docscrub/
├── start.bat
├── config.json
├── docscrub.db
├── backend/
│   ├── main.py              # FastAPI app entry
│   ├── routes/
│   │   ├── upload.py         # File upload endpoints
│   │   ├── anonymize.py      # Anonymization pipeline
│   │   ├── review.py         # Review and edit endpoints
│   │   ├── export.py         # Export and download
│   │   └── reidentify.py     # Re-identification workflow
│   ├── services/
│   │   ├── file_reader.py    # PDF and Word text extraction
│   │   ├── image_extractor.py # Image extraction and management
│   │   ├── llm_client.py     # OpenAI-compatible API client
│   │   ├── regex_engine.py   # Regex PII detection
│   │   ├── mapper.py         # Mapping table management
│   │   └── replacer.py       # Text replacement engine
│   ├── models/
│   │   └── schemas.py        # Pydantic models
│   └── db/
│       └── database.py       # SQLite operations
├── frontend/
│   ├── index.html
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── app.js            # Main app logic
│       ├── upload.js          # Upload and drag-drop
│       ├── review.js          # Review and diff view
│       └── export.js          # Export handling
├── output/                    # Anonymized files land here
└── mappings/                  # Mapping JSON files
```

---

## Screens

### 1. Home / Upload
- App title and brief description
- Large drag-and-drop zone
- File list showing queued documents
- Settings gear icon (LLM endpoint, model selection)
- "Next" button → Image Review

### 2. Image Review
- Thumbnail grid of all extracted images
- Each has checkbox, source doc name, page number
- "Select All for Removal" / "Deselect All" toggles
- "Scrub Documents" button → Processing

### 3. Processing
- Per-document progress bars
- Current step indicator (extracting → detecting → replacing → generating)
- Overall batch progress

### 4. Review
- Document selector (tabs or dropdown for multi-doc batches)
- Side-by-side view: original text (left) vs anonymized (right)
- Color-coded highlights by PII type
- Mapping table panel (collapsible)
  - Editable: user can change a placeholder or remove a replacement
  - "Add Manual" button: user highlights text and marks it as PII
- "Re-run" button (if user wants to try with a different model)
- "Export" button → Export

### 5. Export
- Download anonymized files (zip if multiple)
- Download mapping file (JSON)
- Job summary: file count, PII items found, model used, timestamp
- "New Job" button → back to Home

### 6. Re-identify (accessible from nav)
- Upload anonymized files
- Upload or select mapping file from history
- "Restore" button
- Download restored files

---

## Edge Cases and Error Handling

- **LLM unreachable**: Clear error message with "Check that Ollama is running" guidance
- **LLM returns garbage**: Validation layer checks JSON structure; falls back to regex-only with a warning
- **Huge documents**: Chunk text, process sequentially, merge mappings
- **Scanned PDFs (image-only)**: Detect via text extraction yielding empty; warn user OCR is not supported in Phase 1
- **Password-protected files**: Detect and skip with clear message
- **Overlapping PII**: "John Smith at john.smith@email.com" — handle name and email as separate entities, both replaced
- **PII in tables**: Ensure extraction preserves table cell boundaries
- **Mixed file batch**: PDF and Word docs in the same job — each processed by its appropriate reader

---

## Security Considerations

- No network calls except to the configured LLM endpoint
- No telemetry, no analytics, no phoning home
- Mapping files contain the real PII — stored locally, user's responsibility
- SQLite DB contains mapping history — user can purge via settings
- App binds to localhost only by default (not exposed to network)

---

## Out of Scope (Phase 1)

- OCR for scanned PDFs
- Rubric-based grading
- Frontier model integration
- Calibration anchors
- Multi-user / authentication
- Cloud deployment
- Excel/CSV file support
- Automated re-identification (manual upload required)
- Custom PII categories defined by user (fixed list only)
- Batch scheduling / cron jobs

---

## Success Criteria

1. A non-technical user can install and run the app on Windows in under 10 minutes
2. A 10-page Word doc is anonymized in under 2 minutes on an 8B model
3. PII detection catches ≥95% of items in the target list
4. Reversible mapping correctly restores 100% of replacements
5. No data leaves the local machine (except LLM API calls to configured endpoint)
