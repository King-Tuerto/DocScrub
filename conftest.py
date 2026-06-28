"""
Root conftest — applies httpx_mock options project-wide.

pytest-httpx 0.36 raises teardown errors when registered responses go
unused (e.g. mock_llm_endpoint registers POST+GET but a test only uses
one).  Adding the marker via the collection hook lets us keep
assert_all_responses_were_requested=False and
can_send_already_matched_responses=True globally without modifying
any test file.
"""

import pytest


def pytest_collection_modifyitems(items):
    """Attach lenient httpx_mock options to every test item."""
    marker = pytest.mark.httpx_mock(
        assert_all_responses_were_requested=False,
        can_send_already_matched_responses=True,
    )
    for item in items:
        item.add_marker(marker, append=False)
