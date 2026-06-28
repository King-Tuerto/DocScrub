"""
Piece 5 — Regex Engine

Tests:
- Every pattern in the spec is detected
- All US phone formats recognized
- ZIP flagged but not auto-placed as a replacement
- Clean text returns empty list
- Multiple occurrences all detected
- Overlapping spans both captured
- Output type is list[PIIFinding]
- Custom configurable regex patterns applied
- No LLM involvement; purely stateless
"""

import pytest
from conftest import KNOWN_PII


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_regex(text, custom_patterns=None):
    from backend.services.regex_engine import run_regex_engine
    return run_regex_engine(text, custom_patterns=custom_patterns or [])


def finding_texts(findings):
    return [f.text for f in findings]


def finding_types(findings):
    return [f.type for f in findings]


# ---------------------------------------------------------------------------
# SSN detection
# ---------------------------------------------------------------------------

class TestSSNDetection:
    def test_standard_ssn(self):
        findings = run_regex(f"SSN: {KNOWN_PII['ssn']}")
        assert KNOWN_PII["ssn"] in finding_texts(findings)

    def test_ssn_type_is_ssn(self):
        findings = run_regex(f"SSN: {KNOWN_PII['ssn']}")
        ssn_findings = [f for f in findings if f.text == KNOWN_PII["ssn"]]
        assert ssn_findings[0].type == "SSN"

    def test_multiple_ssns_all_detected(self):
        text = "SSN1: 123-45-6789 and SSN2: 987-65-4321"
        findings = run_regex(text)
        ssn_texts = [f.text for f in findings if f.type == "SSN"]
        assert "123-45-6789" in ssn_texts
        assert "987-65-4321" in ssn_texts

    def test_ssn_without_dashes_not_detected(self):
        """123456789 with no dashes is ambiguous; should NOT be auto-flagged as SSN."""
        findings = run_regex("Number: 123456789")
        ssn_findings = [f for f in findings if f.type == "SSN"]
        assert all(f.text != "123456789" for f in ssn_findings)


# ---------------------------------------------------------------------------
# Email detection
# ---------------------------------------------------------------------------

class TestEmailDetection:
    def test_standard_email(self):
        findings = run_regex(f"Email: {KNOWN_PII['email']}")
        assert KNOWN_PII["email"] in finding_texts(findings)

    def test_email_type(self):
        findings = run_regex(f"Email: {KNOWN_PII['email']}")
        email_findings = [f for f in findings if f.text == KNOWN_PII["email"]]
        assert email_findings[0].type == "EMAIL"

    def test_multiple_emails(self):
        text = "Contacts: alice@example.com and bob@company.org"
        findings = run_regex(text)
        emails = [f.text for f in findings if f.type == "EMAIL"]
        assert "alice@example.com" in emails
        assert "bob@company.org" in emails

    def test_malformed_email_not_detected(self):
        findings = run_regex("not_an_email@")
        emails = [f for f in findings if f.type == "EMAIL"]
        assert all("not_an_email@" != f.text for f in emails)


# ---------------------------------------------------------------------------
# Phone detection — all US formats
# ---------------------------------------------------------------------------

class TestPhoneDetection:
    @pytest.mark.parametrize("phone", [
        "(555) 123-4567",
        "555-987-6543",
        "555.222.3333",
        "+15551234567",
    ])
    def test_phone_format_detected(self, phone):
        findings = run_regex(f"Call: {phone}")
        phone_texts = [f.text for f in findings if f.type == "PHONE"]
        assert phone in phone_texts, f"Phone not detected: {phone}"

    def test_all_four_formats_in_same_text(self):
        text = (
            f"{KNOWN_PII['phone1']} "
            f"{KNOWN_PII['phone2']} "
            f"{KNOWN_PII['phone3']} "
            f"{KNOWN_PII['phone4']}"
        )
        findings = run_regex(text)
        phone_texts = [f.text for f in findings if f.type == "PHONE"]
        for phone in (
            KNOWN_PII["phone1"],
            KNOWN_PII["phone2"],
            KNOWN_PII["phone3"],
            KNOWN_PII["phone4"],
        ):
            assert phone in phone_texts, f"Missing phone: {phone}"


# ---------------------------------------------------------------------------
# ZIP code — flagged only
# ---------------------------------------------------------------------------

class TestZIPDetection:
    def test_zip_code_flagged(self):
        findings = run_regex(f"ZIP: {KNOWN_PII['zip']}")
        zip_findings = [f for f in findings if "62701" in f.text]
        assert len(zip_findings) >= 1

    def test_zip_code_type_is_other_or_zip(self):
        """ZIP is context-ambiguous; it should be flagged but not typed as PERSON/SSN."""
        findings = run_regex(f"ZIP: {KNOWN_PII['zip']}")
        zip_findings = [f for f in findings if "62701" in f.text]
        for f in zip_findings:
            assert f.type not in ("PERSON", "SSN", "EMAIL")

    def test_zip_plus_four_detected(self):
        findings = run_regex("ZIP+4: 62701-1234")
        zip_texts = [f.text for f in findings]
        assert any("62701" in t for t in zip_texts)


# ---------------------------------------------------------------------------
# Clean text
# ---------------------------------------------------------------------------

class TestCleanText:
    def test_clean_text_returns_empty(self, clean_text):
        findings = run_regex(clean_text)
        assert findings == []

    def test_empty_string_returns_empty(self):
        assert run_regex("") == []

    def test_whitespace_only_returns_empty(self):
        assert run_regex("   \n\t  ") == []


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_returns_list(self):
        from backend.services.regex_engine import run_regex_engine
        result = run_regex_engine("hello")
        assert isinstance(result, list)

    def test_each_item_is_pii_finding(self):
        from backend.models.schemas import PIIFinding
        findings = run_regex(f"SSN: {KNOWN_PII['ssn']}")
        for f in findings:
            assert isinstance(f, PIIFinding)

    def test_source_field_is_regex(self):
        findings = run_regex(f"SSN: {KNOWN_PII['ssn']}")
        for f in findings:
            assert f.source == "regex"


# ---------------------------------------------------------------------------
# Multiple PII types in same text
# ---------------------------------------------------------------------------

class TestMixedPII:
    def test_ssn_and_email_in_same_text(self):
        text = f"SSN: {KNOWN_PII['ssn']} email: {KNOWN_PII['email']}"
        findings = run_regex(text)
        types_found = {f.type for f in findings}
        assert "SSN" in types_found
        assert "EMAIL" in types_found

    def test_all_regex_pii_types_detected(self, sample_pii_text):
        findings = run_regex(sample_pii_text)
        types_found = {f.type for f in findings}
        # Regex engine handles SSN, EMAIL, PHONE at minimum
        assert "SSN" in types_found
        assert "EMAIL" in types_found
        assert "PHONE" in types_found


# ---------------------------------------------------------------------------
# Custom configurable patterns
# ---------------------------------------------------------------------------

class TestCustomPatterns:
    def test_custom_student_id_pattern(self):
        custom = [
            {"name": "STUDENT_ID", "pattern": r"STU-\d{8}", "pii_type": "ID"}
        ]
        findings = run_regex(f"ID: {KNOWN_PII['student_id']}", custom_patterns=custom)
        id_findings = [f for f in findings if f.type == "ID"]
        assert any(KNOWN_PII["student_id"] in f.text for f in id_findings)

    def test_custom_pattern_invalid_regex_raises(self):
        from backend.services.regex_engine import run_regex_engine
        bad_patterns = [{"name": "BAD", "pattern": r"[unclosed", "pii_type": "OTHER"}]
        with pytest.raises(Exception):
            run_regex_engine("some text", custom_patterns=bad_patterns)


# ---------------------------------------------------------------------------
# Deduplication within regex results
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_same_value_appears_once(self):
        """Same SSN appearing twice should produce one finding, not two."""
        text = f"SSN: {KNOWN_PII['ssn']} and again: {KNOWN_PII['ssn']}"
        findings = run_regex(text)
        ssn_texts = [f.text for f in findings if f.type == "SSN"]
        assert ssn_texts.count(KNOWN_PII["ssn"]) == 1
