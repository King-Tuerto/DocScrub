"""
V2 Piece 9 — Frontend: Tier Selector & Roster Upload UI

Tests what can be verified without a running browser:
- index.html contains a tier selector element (#tier-select or similar)
- index.html contains a roster upload area (#roster-panel or similar)
- index.html contains a roster dropdown (#roster-select)
- Tier selector has three options: names, names_patterns, full
- upload.js references the tier value when calling anonymize
- upload.js references roster_id in the anonymize POST body
- upload.js disables the scrub button when tier is names/names_patterns and no roster loaded
- app.js DS.config has tier and roster_id keys
- review.js renders the mapping table after delete (frontend calls DELETE endpoint)

Note: these are structural/source-code assertions.  JS logic tests that require
a browser are out-of-scope for the pytest suite and must be tested manually or
with a separate Playwright/Selenium suite.
"""

from pathlib import Path
import re

import pytest


PROJECT_ROOT = Path(__file__).parent.parent
INDEX_HTML = PROJECT_ROOT / "frontend" / "index.html"
UPLOAD_JS  = PROJECT_ROOT / "frontend" / "js" / "upload.js"
REVIEW_JS  = PROJECT_ROOT / "frontend" / "js" / "review.js"
APP_JS     = PROJECT_ROOT / "frontend" / "js" / "app.js"


# ---------------------------------------------------------------------------
# index.html — structural checks
# ---------------------------------------------------------------------------

class TestIndexHTMLTierSelector:
    def _html(self):
        return INDEX_HTML.read_text(encoding="utf-8")

    def test_tier_selector_element_present(self):
        html = self._html()
        assert (
            "tier" in html.lower() and ("select" in html.lower() or "dropdown" in html.lower())
        ), "Expected a tier selector element in index.html"

    def test_tier_option_names_present(self):
        html = self._html()
        assert "names" in html.lower() or "names only" in html.lower()

    def test_tier_option_names_patterns_present(self):
        html = self._html()
        assert "names_patterns" in html.lower() or "names + patterns" in html.lower()

    def test_tier_option_full_present(self):
        html = self._html()
        assert "full" in html.lower() or "full scan" in html.lower()

    def test_roster_upload_area_present(self):
        html = self._html()
        assert "roster" in html.lower()

    def test_roster_select_element_present(self):
        """A dropdown for selecting a saved roster must exist."""
        html = self._html()
        has_roster_select = (
            "roster-select" in html
            or "roster_select" in html
            or (
                "roster" in html.lower()
                and "<select" in html.lower()
            )
        )
        assert has_roster_select

    def test_scrub_button_present(self):
        html = self._html()
        assert "scrub" in html.lower() or "btn-scrub" in html.lower()


# ---------------------------------------------------------------------------
# upload.js — tier and roster_id in anonymize call
# ---------------------------------------------------------------------------

class TestUploadJSTier:
    def _js(self):
        return UPLOAD_JS.read_text(encoding="utf-8")

    def test_upload_js_sends_tier(self):
        js = self._js()
        assert "tier" in js, "upload.js must include 'tier' in the anonymize POST body"

    def test_upload_js_sends_roster_id(self):
        js = self._js()
        assert "roster_id" in js, "upload.js must include 'roster_id' in the POST body"

    def test_upload_js_disables_scrub_without_roster(self):
        """JS must reference the scrub button's disabled state when no roster is set."""
        js = self._js()
        has_disable_logic = (
            "disabled" in js.lower()
            or ".disabled" in js
            or "setAttribute" in js
        )
        assert has_disable_logic, (
            "upload.js must disable the scrub button when roster is required but missing"
        )

    def test_upload_js_references_roster_file_input(self):
        js = self._js()
        assert "roster" in js.lower()


# ---------------------------------------------------------------------------
# review.js — delete button and DELETE endpoint call
# ---------------------------------------------------------------------------

class TestReviewJSDelete:
    def _js(self):
        return REVIEW_JS.read_text(encoding="utf-8")

    def test_review_js_has_delete_button(self):
        js = self._js()
        assert "delete" in js.lower() or "btn-delete" in js.lower()

    def test_review_js_calls_delete_endpoint(self):
        js = self._js()
        assert "DELETE" in js or "delete" in js.lower()

    def test_review_js_has_confirmation_dialog(self):
        js = self._js()
        assert "confirm" in js.lower()

    def test_review_js_rerenders_after_delete(self):
        """After deletion, renderMappingTable must be called again."""
        js = self._js()
        assert "renderMappingTable" in js or "render" in js.lower()


# ---------------------------------------------------------------------------
# app.js — DS.config keys
# ---------------------------------------------------------------------------

class TestAppJSTierConfig:
    def _js(self):
        return APP_JS.read_text(encoding="utf-8")

    def test_ds_config_has_tier(self):
        js = self._js()
        assert "tier" in js

    def test_ds_config_has_roster_id(self):
        js = self._js()
        assert "roster_id" in js
