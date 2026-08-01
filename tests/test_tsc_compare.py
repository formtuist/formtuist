"""Tests for the report comparison helper in scripts.tsc_compare."""

from typing import Any

from scripts import tsc_compare

FULL_PERCENT = 100.0
THREE_QUARTERS_PERCENT = 75.0
TOTAL_FUNCTIONS = 4
STATUS_ROW_COUNT = 4


def test_percent_guards_against_zero_total() -> None:
    """_percent returns 100 when the total is zero."""
    assert tsc_compare._percent(0, 0) == FULL_PERCENT
    assert tsc_compare._percent(3, 4) == THREE_QUARTERS_PERCENT


def test_summary_rows_builds_four_status_rows() -> None:
    """_summary_rows renders the four status categories."""
    rows = tsc_compare._summary_rows(
        {
            "directly_tested": 3,
            "indirectly_tested": 1,
            "untested": 0,
            "unresolved": 0,
        },
        TOTAL_FUNCTIONS,
    )
    assert len(rows) == STATUS_ROW_COUNT
    assert rows[0] == ("Directly Tested", "3", "75.0%")


def test_status_disagreements_lists_only_differences() -> None:
    """_status_disagreements reports functions whose status differs."""
    first = {
        "functions": {
            "m:a:1": {"test_status": "direct"},
            "m:b:1": {"test_status": "indirect"},
        }
    }
    second = {
        "functions": {
            "m:a:1": {"test_status": "direct"},
            "m:b:1": {"test_status": "none"},
        }
    }
    disagreements = tsc_compare._status_disagreements(first, second)
    assert disagreements == [("m:b:1", "indirect", "none")]


def test_status_disagreements_ignore_missing_functions() -> None:
    """_status_disagreements skips functions absent from one report."""
    first: dict[str, Any] = {"functions": {"m:a:1": {"test_status": "direct"}}}
    second: dict[str, Any] = {"functions": {}}
    assert tsc_compare._status_disagreements(first, second) == []
