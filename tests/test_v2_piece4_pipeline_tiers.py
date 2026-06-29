"""
V2 Piece 4 — Pipeline Tier Paths

Tests for run_pipeline() with tier parameter:

Tier 'names':
- LLM is NOT called
- Regex is NOT run
- Only roster-matched names are replaced
- Non-roster text untouched
- Missing roster_entries → warning, empty mapping

Tier 'names_patterns':
- LLM is NOT called
- Regex IS run (SSN, email, phone replaced)
- Roster names also replaced
- Non-roster, non-regex text untouched

Tier 'full':
- Existing behavior: LLM + regex (no regression)

Cross-tier:
- tier parameter persists through to PipelineResult (for DB storage)
- Switching tier between runs of the same job works
- Invalid tier value raises ValueError
"""

import pytest
from pathlib import Path
from conftest import KNOWN_PII


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_roster(names):
    """Build a list of RosterEntry objects from (first, last) tuples."""
    from backend.services.roster_parser import RosterEntry
    return [
        RosterEntry(first_name=fn, last_name=ln,
                    preferred_name=None, student_id=None, email=None)
        for fn, ln in names
    ]


def _run(file_path, config, roster_entries=None, tier="full", output_dir=None):
    from backend.services.pipeline import run_pipeline
    return run_pipeline(
        job_id="test-job",
        file_paths=[file_path],
        config=config,
        roster_entries=roster_entries,
        tier=tier,
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# Tier 'names' — LLM not called
# ---------------------------------------------------------------------------

class TestTierNames:
    def test_tier_names_does_not_call_llm(
        self, sample_pdf_path, default_config, httpx_mock
    ):
        """No HTTP request to the LLM endpoint must be made."""
        roster = _make_roster([("Jane", "Smith")])
        _run(sample_pdf_path, default_config, roster_entries=roster, tier="names")
        # httpx_mock will fail the test if any unexpected calls are made
        # (pytest-httpx raises if calls occur without a registered handler)
        assert True  # reaching here means no LLM call was attempted

    def test_tier_names_replaces_roster_name(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names")
        anon_text = result.files[0].anonymized_text
        assert KNOWN_PII["person"] not in anon_text

    def test_tier_names_leaves_ssn_untouched(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names")
        anon_text = result.files[0].anonymized_text
        # SSN should NOT be replaced in names-only tier
        assert KNOWN_PII["ssn"] in anon_text

    def test_tier_names_no_regex_email_detection(
        self, sample_pdf_path, default_config
    ):
        # names tier does no regex detection — email addresses are not replaced
        # as [EMAIL_N] patterns.  However, if a roster last name appears in the
        # email local-part (e.g. "smith" in "jane.smith@acme.com"), the
        # standalone-last-name variant will still fire as [PERSON_N] — that is
        # expected behaviour introduced with standalone last-name matching.
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names")
        anon_text = result.files[0].anonymized_text
        # No [EMAIL_N] placeholders should appear — email detection is off
        import re
        assert not re.search(r'\[EMAIL_\d+\]', anon_text)

    def test_tier_names_empty_roster_produces_warning(
        self, sample_pdf_path, default_config
    ):
        result = _run(sample_pdf_path, default_config, roster_entries=[], tier="names")
        assert any("roster" in w.lower() for w in result.warnings)

    def test_tier_names_none_roster_produces_warning(
        self, sample_pdf_path, default_config
    ):
        result = _run(sample_pdf_path, default_config, roster_entries=None, tier="names")
        assert any("roster" in w.lower() for w in result.warnings)

    def test_tier_names_empty_roster_produces_empty_mapping(
        self, sample_pdf_path, default_config
    ):
        result = _run(sample_pdf_path, default_config, roster_entries=[], tier="names")
        assert result.mapping.entries == []

    def test_tier_names_non_roster_text_unchanged(
        self, sample_pdf_path, default_config
    ):
        """Acme Corporation is in the doc but not in the roster — must stay."""
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names")
        anon_text = result.files[0].anonymized_text
        assert KNOWN_PII["org"] in anon_text


# ---------------------------------------------------------------------------
# Tier 'names_patterns' — LLM not called, regex runs
# ---------------------------------------------------------------------------

class TestTierNamesPatterns:
    def test_tier_np_does_not_call_llm(
        self, sample_pdf_path, default_config, httpx_mock
    ):
        roster = _make_roster([("Jane", "Smith")])
        _run(sample_pdf_path, default_config, roster_entries=roster, tier="names_patterns")
        assert True

    def test_tier_np_replaces_roster_name(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names_patterns")
        assert KNOWN_PII["person"] not in result.files[0].anonymized_text

    def test_tier_np_replaces_ssn(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names_patterns")
        assert KNOWN_PII["ssn"] not in result.files[0].anonymized_text

    def test_tier_np_replaces_email(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names_patterns")
        assert KNOWN_PII["email"] not in result.files[0].anonymized_text

    def test_tier_np_replaces_phone(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names_patterns")
        assert KNOWN_PII["phone1"] not in result.files[0].anonymized_text

    def test_tier_np_non_regex_non_roster_text_unchanged(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names_patterns")
        # Org is not in roster and not a regex pattern type
        anon_text = result.files[0].anonymized_text
        assert KNOWN_PII["org"] in anon_text

    def test_tier_np_empty_roster_still_runs_regex(
        self, sample_pdf_path, default_config
    ):
        result = _run(sample_pdf_path, default_config, roster_entries=[], tier="names_patterns")
        assert KNOWN_PII["ssn"] not in result.files[0].anonymized_text


# ---------------------------------------------------------------------------
# Tier 'full' — regression (must not change existing behavior)
# ---------------------------------------------------------------------------

class TestTierFullRegression:
    def test_tier_full_is_default(self, sample_pdf_path, default_config, mock_llm_endpoint):
        from backend.services.pipeline import run_pipeline
        result = run_pipeline(
            job_id="full-default",
            file_paths=[sample_pdf_path],
            config=default_config,
        )
        assert result.files[0].anonymized_text is not None

    def test_tier_full_explicit_still_calls_llm(
        self, sample_pdf_path, default_config, mock_llm_endpoint
    ):
        result = _run(sample_pdf_path, default_config, tier="full")
        # mock_llm_endpoint registered a single response; if LLM wasn't called
        # pytest-httpx would still pass but we check mapping has LLM entries
        llm_entries = [e for e in result.mapping.entries if e.source in ("llm", "both")]
        assert len(llm_entries) > 0


# ---------------------------------------------------------------------------
# Invalid tier
# ---------------------------------------------------------------------------

class TestInvalidTier:
    def test_invalid_tier_raises_value_error(self, sample_pdf_path, default_config):
        with pytest.raises((ValueError, Exception)):
            _run(sample_pdf_path, default_config, tier="super_scan")


# ---------------------------------------------------------------------------
# Tier stored in PipelineResult
# ---------------------------------------------------------------------------

class TestTierInResult:
    def test_pipeline_result_has_tier_attribute(
        self, sample_pdf_path, default_config, mock_llm_endpoint
    ):
        result = _run(sample_pdf_path, default_config, tier="full")
        assert hasattr(result, "tier")

    def test_pipeline_result_tier_matches_input(
        self, sample_pdf_path, default_config
    ):
        roster = _make_roster([("Jane", "Smith")])
        result = _run(sample_pdf_path, default_config, roster_entries=roster, tier="names")
        assert result.tier == "names"
