"""
V2 Piece 11 — Mapping filter: only emit entries that appear in document text

Tests:
  _appears_in_text helper
  - word-bounded match found
  - partial-word boundary not matched (STU001 vs STU0010)
  - case-sensitive check (original case)
  - non-word-char boundaries (email with @) matched without \b
  - multi-word term matched
  - empty text → no match

  build_name_mapping(entries, text=None) — backward compat
  - text=None: all variants included (no change to existing behaviour)
  - text='': returns empty mapping regardless of roster size

  PERSON filtering
  - person present in text → included with correct placeholder
  - person NOT in text → excluded, no [PERSON_N] entry
  - two people; one in text → only that person's entries emitted
  - counter is gap-free: if person 2 of 3 is missing, result is [PERSON_1], [PERSON_2]
  - variant in text but not canonical → still included (catches any matching variant)
  - preferred-name variant matched → included
  - nickname variant matched → included
  - case-insensitive: lowercase "jane smith" in text counts

  ID filtering
  - ID in text → [ID_1] emitted
  - ID NOT in text → no ID entry
  - partial match (word boundary) not counted

  EMAIL filtering
  - email in text → [EMAIL_1] emitted
  - email not in text → no email entry

  REDACTED filtering (also_remove)
  - term in text → [REDACTED_1] emitted
  - term NOT in text → excluded
  - semicolon list: only matching terms emitted
  - all terms absent → no REDACTED entries

  Mixed roster
  - roster with 5 people; text contains 2 → mapping has exactly 2 PERSON entries
  - IDs and emails only for people whose values appear in text
"""

import pytest


# ============================================================
# Helpers
# ============================================================

def _entry(first="Jane", last="Smith", preferred=None, student_id=None, email=None, also_remove=None):
    from backend.services.roster_parser import RosterEntry
    return RosterEntry(
        first_name=first, last_name=last,
        preferred_name=preferred,
        student_id=student_id,
        email=email,
        also_remove=also_remove,
    )


def _mapping(entries, text=None):
    from backend.services.name_matcher import build_name_mapping
    return build_name_mapping(entries, text=text)


# ============================================================
# _appears_in_text
# ============================================================

class TestAppearsInText:
    def _check(self, original, text):
        from backend.services.name_matcher import _appears_in_text
        return _appears_in_text(original, text)

    def test_exact_word_match(self):
        assert self._check("Smith", "Hello Smith goodbye") is True

    def test_word_in_middle_of_sentence(self):
        assert self._check("Jane Smith", "Student: Jane Smith submitted.") is True

    def test_word_not_present(self):
        assert self._check("Smith", "Hello Jones goodbye") is False

    def test_partial_word_not_matched(self):
        # "STU001" must NOT match "STU0010" (word boundary)
        assert self._check("STU001", "ID is STU0010.") is False

    def test_exact_id_matched(self):
        assert self._check("STU001", "ID is STU001.") is True

    def test_email_matched(self):
        # email has non-word char (@) so boundary check is relaxed
        assert self._check("jane@example.com", "Contact jane@example.com") is True

    def test_email_not_present(self):
        assert self._check("bob@example.com", "Contact jane@example.com") is False

    def test_multi_word_term(self):
        assert self._check("Acme Corp", "Acme Corp submitted the form.") is True

    def test_multi_word_term_not_present(self):
        assert self._check("Acme Corp", "Widget LLC submitted.") is False

    def test_empty_text_no_match(self):
        assert self._check("Smith", "") is False


# ============================================================
# Backward compat: text=None
# ============================================================

class TestBackwardCompat:
    def test_text_none_includes_all_variants(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text=None)
        assert len(mapping.entries) > 0

    def test_text_none_includes_nickname_variants(self):
        entry = _entry(first="Joseph", last="Doe")
        mapping = _mapping([entry], text=None)
        originals = {e.original for e in mapping.entries}
        assert "Joe Doe" in originals  # Joe is a nickname for Joseph

    def test_empty_text_returns_empty_mapping(self):
        entry = _entry()
        mapping = _mapping([entry], text="")
        assert mapping.entries == []

    def test_no_text_arg_same_as_none(self):
        from backend.services.name_matcher import build_name_mapping
        entry = _entry(first="Jane", last="Smith")
        m1 = build_name_mapping([entry])
        m2 = build_name_mapping([entry], text=None)
        assert {e.original for e in m1.entries} == {e.original for e in m2.entries}


# ============================================================
# PERSON filtering
# ============================================================

class TestPersonFiltering:
    def test_person_in_text_included(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="Jane Smith submitted.")
        person_entries = [e for e in mapping.entries if e.pii_type == "PERSON"]
        assert len(person_entries) > 0

    def test_person_not_in_text_excluded(self):
        entry = _entry(first="Maria", last="Gonzalez")
        mapping = _mapping([entry], text="Robert Chen submitted.")
        person_entries = [e for e in mapping.entries if e.pii_type == "PERSON"]
        assert len(person_entries) == 0

    def test_placeholder_assigned_correctly(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="Jane Smith wrote this.")
        person_entries = [e for e in mapping.entries if e.pii_type == "PERSON"]
        placeholders = {e.placeholder for e in person_entries}
        assert "[PERSON_1]" in placeholders

    def test_two_people_only_present_one_included(self):
        entries = [
            _entry(first="Jane", last="Smith"),
            _entry(first="Maria", last="Gonzalez"),
        ]
        mapping = _mapping(entries, text="This document is by Jane Smith.")
        person_phs = {e.placeholder for e in mapping.entries if e.pii_type == "PERSON"}
        assert len(person_phs) == 1

    def test_counter_gap_free_when_one_person_absent(self):
        """If person 1 absent and person 2 present, result must be [PERSON_1] not [PERSON_2]."""
        entries = [
            _entry(first="Maria", last="Gonzalez"),   # NOT in text
            _entry(first="Jane", last="Smith"),        # in text
        ]
        mapping = _mapping(entries, text="Jane Smith submitted.")
        person_phs = {e.placeholder for e in mapping.entries if e.pii_type == "PERSON"}
        assert person_phs == {"[PERSON_1]"}
        assert "[PERSON_2]" not in person_phs

    def test_three_people_middle_absent_counter_gap_free(self):
        entries = [
            _entry(first="Alice", last="A"),   # in text
            _entry(first="Maria", last="Gonzalez"),   # NOT in text
            _entry(first="Bob", last="B"),     # in text
        ]
        mapping = _mapping(entries, text="Alice A and Bob B are here.")
        person_phs = sorted({e.placeholder for e in mapping.entries if e.pii_type == "PERSON"})
        assert person_phs == ["[PERSON_1]", "[PERSON_2]"]

    def test_only_matching_variants_emitted(self):
        """If only 'jane smith' (lowercase) appears, only that variant should be in mapping."""
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="Submitted by jane smith.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        # Should contain 'jane smith' (found in text)
        assert "jane smith" in person_originals
        # Should NOT contain every possible variant (e.g. "Smith, Jane" not in text)
        assert "Smith, Jane" not in person_originals

    def test_nickname_variant_in_text_included(self):
        """If 'Joe Doe' appears (Joe is nickname for Joseph), that variant is included."""
        entry = _entry(first="Joseph", last="Doe")
        mapping = _mapping([entry], text="Joe Doe submitted the assignment.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert "Joe Doe" in person_originals

    def test_preferred_name_variant_in_text_included(self):
        entry = _entry(first="William", last="Jones", preferred="Bill")
        mapping = _mapping([entry], text="Bill Jones signed the form.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert "Bill Jones" in person_originals

    def test_no_variants_found_no_person_entry(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="No names here at all.")
        assert not any(e.pii_type == "PERSON" for e in mapping.entries)

    def test_initial_format_matched(self):
        entry = _entry(first="Jane", last="Smith")
        mapping = _mapping([entry], text="J. Smith reviewed the document.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert "J. Smith" in person_originals

    def test_unrelated_person_variants_not_included(self):
        """Variants for Maria Gonzalez must not appear in a text about Robert Chen."""
        entries = [
            _entry(first="Robert", last="Chen"),
            _entry(first="Maria", last="Gonzalez"),
        ]
        mapping = _mapping(entries, text="Robert Chen wrote this paper.")
        person_originals = {e.original for e in mapping.entries if e.pii_type == "PERSON"}
        assert not any("Gonzalez" in o for o in person_originals)
        assert not any("Maria" in o for o in person_originals)


# ============================================================
# ID filtering
# ============================================================

class TestIDFiltering:
    def test_id_in_text_included(self):
        entry = _entry(student_id="STU001")
        mapping = _mapping([entry], text="Student STU001 submitted.")
        assert any(e.pii_type == "ID" for e in mapping.entries)

    def test_id_not_in_text_excluded(self):
        entry = _entry(student_id="STU001")
        mapping = _mapping([entry], text="No ID mentioned here.")
        assert not any(e.pii_type == "ID" for e in mapping.entries)

    def test_id_partial_word_not_matched(self):
        entry = _entry(student_id="STU001")
        mapping = _mapping([entry], text="ID is STU0010 something.")
        assert not any(e.pii_type == "ID" for e in mapping.entries)

    def test_id_lowercase_in_text_included(self):
        entry = _entry(student_id="STU001")
        mapping = _mapping([entry], text="Student stu001 enrolled.")
        assert any(e.pii_type == "ID" for e in mapping.entries)


# ============================================================
# EMAIL filtering
# ============================================================

class TestEmailFiltering:
    def test_email_in_text_included(self):
        entry = _entry(email="jane@example.com")
        mapping = _mapping([entry], text="Contact jane@example.com for details.")
        assert any(e.pii_type == "EMAIL" for e in mapping.entries)

    def test_email_not_in_text_excluded(self):
        entry = _entry(email="jane@example.com")
        mapping = _mapping([entry], text="No email here.")
        assert not any(e.pii_type == "EMAIL" for e in mapping.entries)

    def test_different_email_not_matched(self):
        entry = _entry(email="bob@example.com")
        mapping = _mapping([entry], text="Contact jane@example.com.")
        assert not any(e.pii_type == "EMAIL" for e in mapping.entries)


# ============================================================
# REDACTED / also_remove filtering
# ============================================================

class TestRedactedFiltering:
    def test_term_in_text_included(self):
        entry = _entry(also_remove="Acme Corp")
        mapping = _mapping([entry], text="Acme Corp submitted the form.")
        assert any(e.pii_type == "REDACTED" for e in mapping.entries)

    def test_term_not_in_text_excluded(self):
        entry = _entry(also_remove="Acme Corp")
        mapping = _mapping([entry], text="Widget LLC submitted.")
        assert not any(e.pii_type == "REDACTED" for e in mapping.entries)

    def test_semicolon_list_only_matching_terms(self):
        entry = _entry(also_remove="Acme Corp;Project Alpha;Widget LLC")
        mapping = _mapping([entry], text="Acme Corp and Widget LLC collaborated.")
        redacted_phs = {e.placeholder for e in mapping.entries if e.pii_type == "REDACTED"}
        # Two terms found → two placeholders
        assert len(redacted_phs) == 2

    def test_semicolon_list_all_absent(self):
        entry = _entry(also_remove="Acme Corp;Project Alpha")
        mapping = _mapping([entry], text="Nothing here.")
        assert not any(e.pii_type == "REDACTED" for e in mapping.entries)

    def test_term_only_entry_filtered(self):
        from backend.services.roster_parser import RosterEntry
        term_entry = RosterEntry(first_name=None, last_name=None, also_remove="Classified Inc")
        mapping = _mapping([term_entry], text="Nothing relevant.")
        assert mapping.entries == []

    def test_term_only_entry_present_included(self):
        from backend.services.roster_parser import RosterEntry
        term_entry = RosterEntry(first_name=None, last_name=None, also_remove="Classified Inc")
        mapping = _mapping([term_entry], text="Classified Inc did the work.")
        assert any(e.pii_type == "REDACTED" for e in mapping.entries)


# ============================================================
# Mixed roster — multiple people and data types
# ============================================================

class TestMixedRosterFiltering:
    def test_five_people_two_in_text(self):
        entries = [
            _entry(first="Alice", last="Anderson"),
            _entry(first="Bob", last="Brown"),
            _entry(first="Carol", last="Chen"),
            _entry(first="David", last="Davis"),
            _entry(first="Eve", last="Evans"),
        ]
        mapping = _mapping(entries, text="Bob Brown and Eve Evans wrote this.")
        person_phs = {e.placeholder for e in mapping.entries if e.pii_type == "PERSON"}
        assert len(person_phs) == 2
        assert "[PERSON_1]" in person_phs
        assert "[PERSON_2]" in person_phs

    def test_id_email_only_for_found_people(self):
        entries = [
            _entry(first="Jane", last="Smith", student_id="STU001", email="jane@x.com"),
            _entry(first="Bob", last="Jones", student_id="STU002", email="bob@x.com"),
        ]
        # Only Jane's name matches; but neither STU001 nor any email in text
        mapping = _mapping(entries, text="Jane Smith submitted.")
        id_entries = [e for e in mapping.entries if e.pii_type == "ID"]
        email_entries = [e for e in mapping.entries if e.pii_type == "EMAIL"]
        assert len(id_entries) == 0
        assert len(email_entries) == 0

    def test_id_in_text_but_name_absent(self):
        entry = _entry(first="Jane", last="Smith", student_id="STU001")
        # ID appears in text, name doesn't
        mapping = _mapping([entry], text="Student STU001 submitted.")
        assert any(e.pii_type == "ID" for e in mapping.entries)
        assert not any(e.pii_type == "PERSON" for e in mapping.entries)

    def test_mapping_exactly_matches_document_content(self):
        """Spot-check: mapping should contain nothing that isn't in the text."""
        entries = [
            _entry(first="Jane", last="Smith", student_id="STU001",
                   email="jane@x.com", also_remove="Acme Corp"),
        ]
        text = "Jane Smith (STU001) represents Acme Corp."
        mapping = _mapping(entries, text=text)
        for e in mapping.entries:
            # Every original in the mapping should be findable in the text
            # (case-insensitively, since we include lowercase variants)
            assert e.original.lower() in text.lower(), (
                f"Entry {e.original!r} not found in text"
            )
