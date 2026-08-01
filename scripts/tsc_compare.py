"""Compare the tree-sitter and trailmark coverage reports for consistency.

Both checkers write the same JSON report schema, so their results can
be diffed directly. This script prints a side-by-side summary of the
two reports and then lists every function whose test_status differs
between them, which is how inconsistencies between the tree-sitter
approach and the trailmark approach show up.

Usage:
    uv run python -m scripts.tsc_compare tsc-treesitter.json tsc-trailmark.json
"""

import json
from pathlib import Path
from typing import Any, cast

import typer
from rich.console import Console
from rich.table import Table

CONSOLE = Console()

STATUS_KEYS = ("directly_tested", "indirectly_tested", "untested")

app = typer.Typer(
    name="tsc-compare",
    help="Compare the tree-sitter and trailmark coverage reports.",
)


def _load_report(report_path: Path) -> dict[str, Any]:
    """Load and return a JSON coverage report."""
    return cast(
        dict[str, Any], json.loads(report_path.read_text(encoding="utf-8"))
    )


def _percent(count: int, total: int) -> float:
    """Return count as a percentage of total, guarding against zero."""
    return (count / total * 100) if total > 0 else 100.0


def _summary_rows(
    summary: dict[str, Any],
    total: int,
) -> list[tuple[str, str, str]]:
    """Return the summary table rows for one report."""
    rows: list[tuple[str, str, str]] = []
    for key in STATUS_KEYS:
        count = summary.get(key, 0)
        rows.append(
            (
                key.replace("_", " ").title(),
                str(count),
                f"{_percent(count, total):.1f}%",
            )
        )
    return rows


def _status_disagreements(
    first: dict[str, Any],
    second: dict[str, Any],
) -> list[tuple[str, str, str]]:
    """Return (function id, first status, second status) triples that differ."""
    first_functions = first.get("functions", {})
    second_functions = second.get("functions", {})
    disagreements: list[tuple[str, str, str]] = []
    for func_id, entry in sorted(first_functions.items()):
        other = second_functions.get(func_id)
        if other is None:
            continue
        first_status = entry.get("test_status")
        second_status = other.get("test_status")
        if first_status != second_status:
            disagreements.append(
                (func_id, str(first_status), str(second_status))
            )
    return disagreements


@app.command()
def compare(tree_sitter_report: Path, trailmark_report: Path) -> None:
    """Print a side-by-side comparison of the two coverage reports."""
    tree_sitter = _load_report(tree_sitter_report)
    trailmark = _load_report(trailmark_report)
    ts_summary = tree_sitter.get("summary", {})
    tm_summary = trailmark.get("summary", {})
    ts_total = int(ts_summary.get("total", 0))
    tm_total = int(tm_summary.get("total", 0))
    table = Table(title="Coverage Report Comparison")
    table.add_column("Metric", style="bold")
    table.add_column("Tree-sitter", justify="right")
    table.add_column("Trailmark", justify="right")
    table.add_row("Total functions", str(ts_total), str(tm_total))
    for ts_row, tm_row in zip(
        _summary_rows(ts_summary, ts_total),
        _summary_rows(tm_summary, tm_total),
    ):
        table.add_row(
            ts_row[0],
            f"{ts_row[1]} ({ts_row[2]})",
            f"{tm_row[1]} ({tm_row[2]})",
        )
    CONSOLE.print(table)
    disagreements = _status_disagreements(tree_sitter, trailmark)
    if not disagreements:
        CONSOLE.print("[green]No per-function status disagreements.[/green]")
        return
    CONSOLE.print(
        f"[yellow]{len(disagreements)} status disagreements:[/yellow]"
    )
    for func_id, first_status, second_status in disagreements:
        CONSOLE.print(
            f"  {func_id}: tree-sitter={first_status}, trailmark={second_status}"
        )


if __name__ == "__main__":
    app()
