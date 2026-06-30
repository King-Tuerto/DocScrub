"""
V2 Piece 17 — Single-name roster entry fallback

When a roster entry has first_name but no last_name (or vice versa), the
name-matcher cannot generate useful "First Last" / "Last, First" / etc.
variants.  Rather than silently dropping the entry, it should treat the
single value as an exact-match removal term → [REDACTED_N], identical to
the also_remove behaviour.

Tests:
- first_name only ("Copper State Credit Union") → matched as [REDACTED_N]
- last_name only ("Acme") → matched as [REDACTED_N]
- Match is case-insensitive (lowercase variant also emitted)
- Match respects word boundaries (does NOT fire inside a larger word)
- Two-person roster: one with both names → [PERSON_1]; one with first only
  → [REDACTED_1].  Counters are independent.
- Single-name entry that does NOT appear in text → not emitted (filter mode)
- Single-name entry too short (1 char) → skipped
- also_remove AND single-name on same entry both work
- Duplicate single-name entries are deduplicated (seen_redacted shared pool)
- CSV round-trip: "Copper State Credit Union" in first_name column → matched
"""

import pytest
from backend.services.roster_parser import RosterEntry
from backend.services.name_matcher import build_name_mapping


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _originals(table):
    return {e.original for e in table.entries}

def _placeholders(table):
    return {e.placeholder for e in table.entries}

def _by_placeholder(table, ph):
    return {e.original for e in table.entries if e.placeholder == ph}


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------

def test_first_name_only_emitted_as_redacted():
    """'Copper State Credit Union' in first_name with no last_name → [REDACTED_1]."""
    entries = [RosterEntry(first_name="Copper State Credit Union", last_name=None)]
    table = build_name_mapping(entries)
    assert any(e.placeholder.startswith("[REDACTED_") for e in table.entries), (
        "Expected a [REDACTED_N] entry for first_name-only roster entry"
    )
    assert "Copper State Credit Union" in _originals(table)


def test_last_name_only_emitted_as_redacted():
    """Entry with last_name only → [REDACTED_1]."""
    entries = [RosterEntry(first_name=None, last_name="Acme")]
    table = build_name_mapping(entries)
    assert "Acme" in _originals(table)
    assert any(e.placeholder.startswith("[REDACTED_") for e in table.entries)


def test_single_name_case_insensitive_variant_emitted():
    """Lowercase variant is also in the mapping so replacer catches mixed-case text."""
    entries = [RosterEntry(first_name="Copper State Credit Union", last_name=None)]
    table = build_name_mapping(entries)
    assert "copper state credit union" in _originals(table)


def test_single_name_not_matched_inside_larger_word():
    """Word-boundary check: 'Acme' should not fire inside 'Acmesoft'."""
    from backend.services.name_matcher import _appears_in_text
    assert not _appears_in_text("Acme", "Acmesoft is the vendor")
    assert _appears_in_text("Acme", "Acme is the vendor")


def test_single_name_text_filter_present():
    """With text filter, single-name entry that appears → emitted."""
    text = "The contract is with Copper State Credit Union for services."
    entries = [RosterEntry(first_name="Copper State Credit Union", last_name=None)]
    table = build_name_mapping(entries, text=text)
    assert "Copper State Credit Union" in _originals(table)


def test_single_name_text_filter_absent():
    """With text filter, single-name entry absent from text → NOT emitted."""
    text = "The contract is with Another Bank for services."
    entries = [RosterEntry(first_name="Copper State Credit Union", last_name=None)]
    table = build_name_mapping(entries, text=text)
    assert "Copper State Credit Union" not in _originals(table)
    assert len(table.entries) == 0


def test_single_name_too_short_skipped():
    """Single token of length < 2 is skipped."""
    entries = [RosterEntry(first_name="A", last_name=None)]
    table = build_name_mapping(entries)
    assert len(table.entries) == 0


# ---------------------------------------------------------------------------
# Mixed roster: person with both names + single-name entry
# ---------------------------------------------------------------------------

def test_mixed_roster_independent_counters():
    """
    Roster has Jane Smith (both names) and 'Copper State Credit Union' (first only).
    Jane → [PERSON_1], Copper State → [REDACTED_1].  Counters are independent.
    """
    entries = [
        RosterEntry(first_name="Jane", last_name="Smith"),
        RosterEntry(first_name="Copper State Credit Union", last_name=None),
    ]
    table = build_name_mapping(entries)
    person_phs = {e.placeholder for e in table.entries if e.placeholder.startswith("[PERSON_")}
    redacted_phs = {e.placeholder for e in table.entries if e.placeholder.startswith("[REDACTED_")}
    assert "[PERSON_1]" in person_phs
    assert "[REDACTED_1]" in redacted_phs
    # They must not share a placeholder
    assert person_phs.isdisjoint(redacted_phs)


def test_single_name_and_also_remove_same_entry():
    """An entry with first_name only AND also_remove both produce output."""
    entries = [RosterEntry(
        first_name="Copper State Credit Union",
        last_name=None,
        also_remove="Project Alpha",
    )]
    table = build_name_mapping(entries)
    originals = _originals(table)
    assert "Copper State Credit Union" in originals
    assert "Project Alpha" in originals


def test_duplicate_single_names_deduplicated():
    """Two entries with the same first_name-only value → one [REDACTED_1] placeholder."""
    entries = [
        RosterEntry(first_name="Acme Corp", last_name=None),
        RosterEntry(first_name="Acme Corp", last_name=None),
    ]
    table = build_name_mapping(entries)
    redacted = [e for e in table.entries if e.placeholder.startswith("[REDACTED_")]
    placeholders = {e.placeholder for e in redacted}
    assert len(placeholders) == 1, "Duplicate single-name entries should share one placeholder"


def test_single_name_dedup_shared_pool_with_also_remove():
    """
    A first_name-only entry 'Acme Corp' and an also_remove 'Acme Corp' on a
    different entry should not produce two [REDACTED_N] counters for the same term.
    """
    entries = [
        RosterEntry(first_name="Acme Corp", last_name=None),
        RosterEntry(first_name="Jane", last_name="Smith", also_remove="Acme Corp"),
    ]
    table = build_name_mapping(entries)
    acme_phs = {e.placeholder for e in table.entries if e.original == "Acme Corp"}
    assert len(acme_phs) == 1, "Same term via two paths must resolve to one placeholder"


# ---------------------------------------------------------------------------
# CSV round-trip: realistic scenario
# ---------------------------------------------------------------------------

def test_csv_roundtrip_org_in_first_name_column():
    """
    A user who puts 'Copper State Credit Union' in the first_name column
    of a CSV (no last_name) should get a match after parsing + mapping.
    """
    from backend.services.roster_parser import parse_roster

    csv_bytes = (
        "first_name,last_name\n"
        "Copper State Credit Union,\n"
    ).encode()
    parsed = parse_roster(csv_bytes, "roster.csv")
    assert len(parsed) == 1
    assert parsed[0].first_name == "Copper State Credit Union"
    assert not parsed[0].last_name

    text = "The partnership with Copper State Credit Union begins next quarter."
    table = build_name_mapping(parsed, text=text)
    assert "Copper State Credit Union" in _originals(table)
    assert any(e.placeholder.startswith("[REDACTED_") for e in table.entries)
