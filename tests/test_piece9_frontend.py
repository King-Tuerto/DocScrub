"""
Piece 9 — Frontend (Static Files & Screen Structure)

Tests:
- FastAPI serves index.html at GET /
- FastAPI serves styles.css
- FastAPI serves all JS files
- index.html contains required structural elements for all 6 screens:
    1. Home/Upload — drag-drop zone, file list, settings trigger, Next button
    2. Image Review — thumbnail grid, select-all toggles, Scrub button
    3. Processing — progress area, step indicator
    4. Review — side-by-side area, mapping table panel, Export button
    5. Export — download buttons, job summary, New Job button
    6. Re-identify — upload zone, Restore button
- Settings modal contains LLM endpoint field and model dropdown
- All 6 screens are present as distinct sections or routes
- No external CDN references (local-first requirement)
"""

import re

import pytest
from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# Fixture: parse index.html via the app client
# ---------------------------------------------------------------------------

@pytest.fixture
def index_html(app_client):
    resp = app_client.get("/")
    assert resp.status_code == 200
    return resp.text


@pytest.fixture
def soup(index_html):
    return BeautifulSoup(index_html, "html.parser")


# ---------------------------------------------------------------------------
# Static file serving
# ---------------------------------------------------------------------------

class TestStaticFileServing:
    def test_root_returns_200(self, app_client):
        assert app_client.get("/").status_code == 200

    def test_root_is_html(self, app_client):
        resp = app_client.get("/")
        assert "text/html" in resp.headers.get("content-type", "")

    def test_css_served(self, app_client):
        resp = app_client.get("/css/styles.css")
        assert resp.status_code == 200

    def test_css_is_css(self, app_client):
        resp = app_client.get("/css/styles.css")
        assert "text/css" in resp.headers.get("content-type", "")

    def test_app_js_served(self, app_client):
        resp = app_client.get("/js/app.js")
        assert resp.status_code == 200

    def test_upload_js_served(self, app_client):
        resp = app_client.get("/js/upload.js")
        assert resp.status_code == 200

    def test_review_js_served(self, app_client):
        resp = app_client.get("/js/review.js")
        assert resp.status_code == 200

    def test_export_js_served(self, app_client):
        resp = app_client.get("/js/export.js")
        assert resp.status_code == 200

    def test_nonexistent_static_returns_404(self, app_client):
        assert app_client.get("/js/nonexistent.js").status_code == 404


# ---------------------------------------------------------------------------
# No external CDN dependencies
# ---------------------------------------------------------------------------

class TestNoExternalDependencies:
    def test_no_cdn_script_tags(self, soup):
        """All <script> tags must reference local paths, not CDN URLs."""
        script_tags = soup.find_all("script", src=True)
        for tag in script_tags:
            src = tag["src"]
            assert not src.startswith("http"), (
                f"External script found: {src}. All JS must be local."
            )

    def test_no_cdn_link_tags(self, soup):
        """All <link rel='stylesheet'> must reference local paths."""
        link_tags = soup.find_all("link", rel="stylesheet")
        for tag in link_tags:
            href = tag.get("href", "")
            assert not href.startswith("http"), (
                f"External stylesheet found: {href}. All CSS must be local."
            )


# ---------------------------------------------------------------------------
# Screen 1: Home / Upload
# ---------------------------------------------------------------------------

class TestHomeScreen:
    def test_has_drag_drop_zone(self, soup):
        """A drag-and-drop upload target must exist."""
        drop_zone = (
            soup.find(id="drop-zone")
            or soup.find(class_=re.compile(r"drop.?zone", re.I))
            or soup.find(attrs={"data-upload": True})
        )
        assert drop_zone is not None, "No drag-drop zone found in index.html"

    def test_has_file_list(self, soup):
        file_list = (
            soup.find(id="file-list")
            or soup.find(class_=re.compile(r"file.?list", re.I))
        )
        assert file_list is not None, "No file list container found"

    def test_has_settings_trigger(self, soup):
        """Settings gear icon or button must exist."""
        settings = (
            soup.find(id="settings-btn")
            or soup.find(class_=re.compile(r"settings", re.I))
            or soup.find(attrs={"data-action": "settings"})
        )
        assert settings is not None, "No settings trigger found"

    def test_has_next_button(self, soup):
        next_btn = (
            soup.find(id="btn-next")
            or soup.find(attrs={"data-action": "next"})
        )
        if next_btn is None:
            # Fallback: look for any button with 'next' text
            buttons = soup.find_all("button")
            next_btn = next(
                (b for b in buttons if "next" in b.get_text(strip=True).lower()), None
            )
        assert next_btn is not None, "No 'Next' button found on upload screen"


# ---------------------------------------------------------------------------
# Screen 2: Image Review
# ---------------------------------------------------------------------------

class TestImageReviewScreen:
    def test_has_image_grid(self, soup):
        grid = (
            soup.find(id="image-grid")
            or soup.find(id="image-review")
            or soup.find(class_=re.compile(r"image.?grid|thumbnail.?grid", re.I))
        )
        assert grid is not None, "No image thumbnail grid found"

    def test_has_select_all_toggle(self, soup):
        toggle = (
            soup.find(id="select-all")
            or soup.find(attrs={"data-action": "select-all"})
        )
        if toggle is None:
            buttons = soup.find_all("button")
            toggle = next(
                (b for b in buttons if "select all" in b.get_text(strip=True).lower()), None
            )
        assert toggle is not None, "No 'Select All' toggle found on image review screen"

    def test_has_scrub_button(self, soup):
        scrub = (
            soup.find(id="btn-scrub")
            or soup.find(attrs={"data-action": "scrub"})
        )
        if scrub is None:
            buttons = soup.find_all("button")
            scrub = next(
                (b for b in buttons if "scrub" in b.get_text(strip=True).lower()), None
            )
        assert scrub is not None, "No 'Scrub Documents' button found"


# ---------------------------------------------------------------------------
# Screen 3: Processing
# ---------------------------------------------------------------------------

class TestProcessingScreen:
    def test_has_progress_area(self, soup):
        progress = (
            soup.find(id="progress-area")
            or soup.find(id="processing")
            or soup.find(class_=re.compile(r"progress", re.I))
        )
        assert progress is not None, "No progress area found for processing screen"

    def test_has_step_indicator(self, soup):
        step = (
            soup.find(id="step-indicator")
            or soup.find(class_=re.compile(r"step.?indicator|current.?step", re.I))
        )
        assert step is not None, "No step indicator found for processing screen"


# ---------------------------------------------------------------------------
# Screen 4: Review
# ---------------------------------------------------------------------------

class TestReviewScreen:
    def test_has_side_by_side_area(self, soup):
        review = (
            soup.find(id="review-area")
            or soup.find(id="diff-view")
            or soup.find(class_=re.compile(r"review|diff.?view|side.?by.?side", re.I))
        )
        assert review is not None, "No side-by-side review area found"

    def test_has_mapping_table_panel(self, soup):
        panel = (
            soup.find(id="mapping-panel")
            or soup.find(id="mapping-table")
            or soup.find(class_=re.compile(r"mapping", re.I))
        )
        assert panel is not None, "No mapping table panel found"

    def test_has_export_button(self, soup):
        export = (
            soup.find(id="btn-export")
            or soup.find(attrs={"data-action": "export"})
        )
        if export is None:
            buttons = soup.find_all("button")
            export = next(
                (b for b in buttons if "export" in b.get_text(strip=True).lower()), None
            )
        assert export is not None, "No 'Export' button found on review screen"


# ---------------------------------------------------------------------------
# Screen 5: Export
# ---------------------------------------------------------------------------

class TestExportScreen:
    def test_has_download_buttons(self, soup):
        downloads = soup.find_all(attrs={"data-action": re.compile(r"download", re.I)})
        if not downloads:
            downloads = [
                b for b in soup.find_all("button")
                if "download" in b.get_text(strip=True).lower()
            ]
        assert len(downloads) >= 1, "No download buttons found on export screen"

    def test_has_job_summary(self, soup):
        summary = (
            soup.find(id="job-summary")
            or soup.find(class_=re.compile(r"summary", re.I))
        )
        assert summary is not None, "No job summary section found on export screen"

    def test_has_new_job_button(self, soup):
        new_job = (
            soup.find(id="btn-new-job")
            or soup.find(attrs={"data-action": "new-job"})
        )
        if new_job is None:
            buttons = soup.find_all("button")
            new_job = next(
                (
                    b for b in buttons
                    if "new job" in b.get_text(strip=True).lower()
                    or "new" in b.get_text(strip=True).lower()
                ),
                None,
            )
        assert new_job is not None, "No 'New Job' button found on export screen"


# ---------------------------------------------------------------------------
# Screen 6: Re-identify
# ---------------------------------------------------------------------------

class TestReidentifyScreen:
    def test_has_reidentify_section(self, soup):
        reidentify = (
            soup.find(id="reidentify")
            or soup.find(id="re-identify")
            or soup.find(class_=re.compile(r"re.?identif", re.I))
        )
        assert reidentify is not None, "No re-identify screen section found"

    def test_has_restore_button(self, soup):
        restore = (
            soup.find(id="btn-restore")
            or soup.find(attrs={"data-action": "restore"})
        )
        if restore is None:
            buttons = soup.find_all("button")
            restore = next(
                (b for b in buttons if "restore" in b.get_text(strip=True).lower()), None
            )
        assert restore is not None, "No 'Restore' button found on re-identify screen"


# ---------------------------------------------------------------------------
# Settings modal
# ---------------------------------------------------------------------------

class TestSettingsModal:
    def test_has_llm_endpoint_input(self, soup):
        field = (
            soup.find(id="llm-endpoint")
            or soup.find(attrs={"name": "llm_endpoint"})
            or soup.find(attrs={"placeholder": re.compile(r"localhost|endpoint", re.I)})
        )
        assert field is not None, "No LLM endpoint input field found"

    def test_has_model_dropdown(self, soup):
        dropdown = (
            soup.find(id="model-select")
            or soup.find("select", attrs={"name": re.compile(r"model", re.I)})
        )
        assert dropdown is not None, "No model dropdown found in settings"
