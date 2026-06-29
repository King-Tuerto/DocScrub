# DocScrub

DocScrub is a local-first document anonymizer for Windows. It strips personally identifiable information (PII) from PDF and Word files before you share them with cloud AI tools, producing clean output files with a reversible mapping table so originals can always be restored — entirely on your own machine, with no data sent anywhere.

---

## Requirements

| Requirement | Notes |
|---|---|
| **Windows 10 or 11** | 64-bit |
| **Python 3.11+** | [python.org/downloads](https://www.python.org/downloads/) — tick "Add Python to PATH" during install |
| **Ollama** *(optional)* | Only needed for **Tier 3 – Full Scan**. [ollama.com](https://ollama.com) |

---

## Install

**Download/clone → run setup.bat → done.** That's the entire install.

1. Download and unzip `DocScrub.zip` — or clone this repo
2. Double-click **`setup.bat`**
3. A **DocScrub** shortcut appears on your Desktop

`setup.bat` installs all Python dependencies, generates the app icon, and creates the shortcut. You only need to run it once.

> **Windows SmartScreen warning?** Click **More info → Run anyway**. DocScrub runs entirely on your machine and makes no network calls except to your local LLM.

---

## Usage

1. Double-click the **DocScrub** icon on your Desktop (or double-click `start.bat`)
2. DocScrub starts minimised in your taskbar and your browser opens automatically
3. Drag your PDF or Word files onto the upload zone and follow the steps
4. When you're done: right-click **DocScrub** in your taskbar and close it to stop the server, or click **End Session** in the browser

---

## The Five-Step Flow

| Step | Screen | What you do |
|---|---|---|
| 1 | **Upload** | Drag PDF / DOCX files into the drop zone |
| 2 | **Image Review** | Uncheck charts and diagrams you want to keep; choose anonymization tier |
| 3 | **Processing** | DocScrub scrubs PII — watch the live progress |
| 4 | **Review** | See a side-by-side diff; edit or delete mapping entries if needed |
| 5 | **Export** | Download clean files and a mapping JSON for later re-identification |

---

## Anonymization Tiers

Choose a tier on the upload screen before adding your documents.

| Tier | What it does | Requires |
|---|---|---|
| **Full Scan** | LLM + regex — catches names, orgs, addresses, SSNs, emails, phones, IDs | Ollama running locally |
| **Names + Patterns** | Names from your list + regex patterns — no LLM needed | A name list CSV |
| **Names Only** | Exact and nickname matching from your name list — fastest, zero AI | A name list CSV |

### Tier 3 — performance expectations

Tier 3 speed depends entirely on the hardware running your local LLM. Be realistic:

| Setup | Speed per chunk | 10-page doc | 100-page board packet |
|---|---|---|---|
| 8B model on a mini PC (CPU) | ~60–90 s | 2–5 min | **2–3 hours** |
| 8B model on a mid-range GPU | ~5–15 s | 15–45 min | 2–4 hours |
| 70B model on a Mac Studio / high-end GPU | ~3–8 s | 5–20 min | 30–90 min |

DocScrub shows live progress ("Processing chunk 3 of 140 · ~45 min remaining") so you can see it's working and estimate when it will finish.

**Recommendation:** use Tier 2 (Names + Patterns) for daily work — it runs in seconds and catches the PII you actually know about. Switch to Tier 3 for short documents where you don't have a name list, or after upgrading to faster hardware. A well-prepared Tier 2 name list beats Tier 3 on a slow machine every time.

### Using a name list (Tiers 1 and 2)

Click **⬇ Download blank template** on the upload screen to get a ready-to-fill CSV with the correct headers and two example rows.

Upload a CSV in one of two formats:

**Full format** — one person per row, all columns optional except first/last name:

```
first_name,last_name,preferred_name,student_id,email,also_remove
```

| Column | Description |
|---|---|
| `first_name`, `last_name` | Required (or use a single `name` column) |
| `preferred_name` | Nickname/alias — also matched |
| `student_id` | Student or employee ID — exact match, replaced as `[ID_N]` |
| `email` | Email address — exact match, replaced as `[EMAIL_N]` |
| `also_remove` | Catch-all: company names, project names, addresses, etc. Replaced as `[REDACTED_N]`. Separate multiple values with semicolons: `Acme Corp;Project Alpha;123 Main St` |

Example:

```csv
first_name,last_name,preferred_name,student_id,email,also_remove
Jane,Smith,,,jane@example.com,Acme Corp;Project Alpha
Joseph,Doe,Joe,12345,jdoe@example.com,
```

DocScrub automatically handles nickname variants (Joe → Joseph, Bill → William, etc.) and format variations (Smith Jane, Smith, Jane, J. Smith).

**Simple term list** — single column, one removal target per row, replaced as `[REDACTED_N]`:

```csv
text
Acme Corp
Project Alpha
Classified Initiative
```

The column header can be `text`, `term`, `terms`, or `remove`. Use this when you don't have a people roster — just a list of things to strip.

Click **Upload name list** on the upload screen to add a new name list. Name lists are saved locally and can be reused across jobs.

---

## Screenshots

*Coming soon.*

---

## Re-identification

To restore original content from anonymized files:

1. Go to the **Re-identify** screen (link in the export screen)
2. Upload your anonymized files and the mapping JSON you downloaded
3. Click **Restore** — original values are written back

The mapping JSON stays on your machine. Guard it like the original document.

---

## Security & Privacy

- Runs on `127.0.0.1` only — not reachable from other devices on your network
- **No telemetry, no analytics, no phoning home**
- All data stays local: SQLite database, mapping files, and output files are on your machine
- LLM calls go to your locally configured endpoint (default: `http://localhost:11434`)
- Name list files contain real names — store and delete them according to your organization's data policy

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Python is not installed" or startup fails | Install Python 3.11+ from python.org; tick "Add Python to PATH"; re-run `setup.bat` |
| Browser doesn't open automatically | Navigate to `http://127.0.0.1:8000` manually |
| "LLM not reachable" warning | Start Ollama (`ollama serve`) or switch to Names/Names+Patterns tier |
| Scanned PDF shows no text | DocScrub requires a text layer; OCR is not supported in this release |
| Port 8000 already in use | Another service is using that port; stop it or change the port in `config.json` |
| DocScrub disappears from taskbar immediately | An error occurred during startup — double-click `start.bat` directly to see the error message in the terminal |

---

## License

MIT — free to use, modify, and distribute.
