"""Check which functions in formtuitous are directly tested vs. indirectly tested.

If a function is indirectly covered that means that a test case calls a
function that transitively calls that function. Importantly, a function
that is indirectly tested does not have a test case that calls it
directly and this could be a sign that the function is not being tested
as thoroughly as it should be.

This checker is the trailmark implementation of the same analysis that
scripts.tsc performs with tree-sitter. It parses the whole project once
with the trailmark programmatic API, producing a code graph of
functions, methods, and call edges, and then classifies every source
function as directly tested, indirectly tested, or untested.

Trailmark resolves cross-file calls to precise node ids (for example
src.formtuitous.auth:fetch_github_identity). A source function counts
as directly tested only when a test_* function calls it through a
resolved call edge. Unresolved dotted or ambiguous calls are credited
only when the call name matches exactly one source function, so names
that appear many times (for example compose) are never given blanket
credit. The report schema is identical to scripts.tsc so the two
approaches can be compared.

Usage:
    uv run python -m scripts.tsc_trailmark [OPTIONS]

Options:
    --threshold, -t INT  Minimum percentage of directly tested functions
                         required (default 100).
    --output, -o PATH    Path for the JSON report file (default
                         tsc-trailmark.json).
    --verbose, --no-verbose
                         Show detailed coverage analysis output (default:
                         no-verbose).

Exit code:
    0 - at least THRESHOLD% of functions are directly tested
    1 - fewer than THRESHOLD% of functions are directly tested

Output:
    Writes a JSON report and prints a color-coded summary to stdout.
"""

import json
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from trailmark.models.graph import CodeGraph
from trailmark.models.nodes import CodeUnit, NodeKind
from trailmark.parse import parse_directory, supported_languages
from trailmark.query.api import QueryEngine

CONSOLE = Console()

DEFAULT_THRESHOLD = 100
DEFAULT_OUTPUT = "tsc-trailmark.json"
MIN_PERCENT = 100.0
UTF8 = "utf-8"
DUNDER_PREFIX = "__"
DUNDER_SUFFIX = "__"
TEST_FILE_PREFIX = "test_"
TEST_FUNC_PREFIX = "test_"
INIT_FILE = "__init__.py"
SOURCE_DIR = "formtuitous"
FUNCTION_KINDS = (NodeKind.FUNCTION, NodeKind.METHOD)
REPORT_TOOL = "trailmark"


def _is_dunder(name: str) -> bool:
    """Return True when name is a dunder name like __init__."""
    return name.startswith(DUNDER_PREFIX) and name.endswith(DUNDER_SUFFIX)


def _make_function_id(relative_file: str, name: str, line: int) -> str:
    """Build a unique function id from file, name, and line."""
    return f"{relative_file}:{name}:{line}"


def _relative_file(path: Path, project_root: Path) -> str:
    """Return the project-root-relative string form of a file path."""
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path)


def _final_component(raw: str) -> str:
    """Return the last module- or attribute-qualified component of a symbol."""
    for sep in (":", "."):
        if sep in raw:
            raw = raw.rsplit(sep, 1)[-1]
    return raw


def _unambiguous_source_ids(
    final_name: str,
    source_by_name: dict[str, list[str]],
) -> list[str]:
    """Return matching source ids only when the name match is unique."""
    matches = source_by_name.get(final_name, [])
    if len(matches) == 1:
        return matches
    return []


def _record_direct_call(
    directly_tested: set[str],
    func_to_test_details: dict[str, list[dict[str, Any]]],
    func_id: str,
    detail: dict[str, Any],
) -> None:
    """Record a direct call from a test to a source function id."""
    directly_tested.add(func_id)
    if func_id not in func_to_test_details:
        func_to_test_details[func_id] = []
    if detail not in func_to_test_details[func_id]:
        func_to_test_details[func_id].append(detail)


def _test_detail(test_unit: CodeUnit, project_root: Path) -> dict[str, Any]:
    """Build the test detail dict recorded for a direct call."""
    return {
        "test_name": test_unit.name,
        "test_file": _relative_file(
            Path(test_unit.location.file_path), project_root
        ),
        "test_start_line": test_unit.location.start_line,
        "test_end_line": test_unit.location.end_line,
    }


def find_source_functions(
    graph: CodeGraph,
    source_dir: Path,
    project_root: Path,
) -> dict[str, dict[str, Any]]:
    """Collect every source function and method from the trailmark graph.

    A node counts as a source function when it is a function or method
    whose file lives under source_dir, is not named __init__.py, and
    whose name is not a dunder name. Entries are keyed by the trailmark
    node id and record the shared file:name:line report id.

    """
    source_dir_resolved = source_dir.resolve()
    functions: dict[str, dict[str, Any]] = {}
    for node_id, unit in graph.nodes.items():
        if unit.kind not in FUNCTION_KINDS:
            continue
        file_path = Path(unit.location.file_path)
        if not file_path.resolve().is_relative_to(source_dir_resolved):
            continue
        if file_path.name == INIT_FILE:
            continue
        if _is_dunder(unit.name):
            continue
        relative_file = _relative_file(file_path, project_root)
        line = unit.location.start_line
        func_id = _make_function_id(relative_file, unit.name, line)
        functions[node_id] = {
            "id": func_id,
            "name": unit.name,
            "file": relative_file,
            "line": line,
            "end_line": unit.location.end_line,
            "trailmark_id": node_id,
        }
    return functions


def find_test_function_ids(
    graph: CodeGraph,
    test_dir: Path,
) -> dict[str, CodeUnit]:
    """Collect trailmark nodes for every test_* function under test_dir."""
    test_dir_resolved = test_dir.resolve()
    test_units: dict[str, CodeUnit] = {}
    for node_id, unit in graph.nodes.items():
        if unit.kind not in FUNCTION_KINDS:
            continue
        if not unit.name.startswith(TEST_FUNC_PREFIX):
            continue
        file_path = Path(unit.location.file_path)
        if not file_path.resolve().is_relative_to(test_dir_resolved):
            continue
        if not file_path.name.startswith(TEST_FILE_PREFIX):
            continue
        test_units[node_id] = unit
    return test_units


def find_direct_test_calls(
    engine: QueryEngine,
    test_units: dict[str, CodeUnit],
    source_by_id: dict[str, dict[str, Any]],
    project_root: Path,
) -> tuple[set[str], dict[str, list[dict[str, Any]]], dict[str, int]]:
    """Scan test functions for direct calls to source functions.

    Uses trailmark's callees_of to list every direct callee of each
    test_* function. A callee that resolves to a source function is
    directly tested; an unresolved proxy callee is credited only when
    its name matches exactly one source function (for example
    server._make_app resolves uniquely, while compose does not).

    Returns a tuple of:
    - set of directly-tested source function ids
    - dict mapping each directly-tested id to a list of test detail
      dicts with keys test_name, test_file, test_start_line,
      test_end_line
    - resolution stats counting resolved edges, unique-name matches,
      ambiguous proxy calls that were skipped, and unmatched proxy
      calls

    """
    source_by_name: dict[str, list[str]] = {}
    for node_id, info in source_by_id.items():
        source_by_name.setdefault(info["name"], []).append(node_id)
    resolution: dict[str, int] = {
        "resolved_direct_calls": 0,
        "unique_name_matches": 0,
        "ambiguous_proxy_calls": 0,
        "unmatched_proxy_calls": 0,
    }
    directly_tested: set[str] = set()
    func_to_test_details: dict[str, list[dict[str, Any]]] = {}
    for test_id, test_unit in test_units.items():
        detail = _test_detail(test_unit, project_root)
        for callee in engine.callees_of(test_id):
            callee_id = callee.get("id", "")
            if callee_id in source_by_id:
                _record_direct_call(
                    directly_tested, func_to_test_details, callee_id, detail
                )
                resolution["resolved_direct_calls"] += 1
                continue
            if callee.get("kind") == NodeKind.PROXY.value:
                final_name = _final_component(str(callee.get("name", "")))
                matches = _unambiguous_source_ids(final_name, source_by_name)
                if matches:
                    resolution["unique_name_matches"] += 1
                    for match_id in matches:
                        _record_direct_call(
                            directly_tested,
                            func_to_test_details,
                            match_id,
                            detail,
                        )
                elif final_name in source_by_name:
                    resolution["ambiguous_proxy_calls"] += 1
                else:
                    resolution["unmatched_proxy_calls"] += 1
    return directly_tested, func_to_test_details, resolution


def build_call_graph(
    engine: QueryEngine,
    source_by_id: dict[str, dict[str, Any]],
) -> dict[str, set[str]]:
    """Build a call graph of which source functions call which others.

    Resolved trailmark call edges provide the primary edges. Unresolved
    proxy targets are added only when the call name matches exactly one
    source function, mirroring the direct-call semantics. Returns a
    dict mapping each source function id to the set of source function
    ids it invokes.

    """
    source_ids = set(source_by_id)
    source_by_name: dict[str, list[str]] = {}
    for node_id, info in source_by_id.items():
        source_by_name.setdefault(info["name"], []).append(node_id)
    call_graph: dict[str, set[str]] = {fid: set() for fid in source_ids}
    for func_id in source_ids:
        for callee in engine.callees_of(func_id):
            callee_id = callee.get("id", "")
            if callee_id in source_ids and callee_id != func_id:
                call_graph[func_id].add(callee_id)
                continue
            if callee.get("kind") == NodeKind.PROXY.value:
                final_name = _final_component(str(callee.get("name", "")))
                for match_id in _unambiguous_source_ids(
                    final_name, source_by_name
                ):
                    if match_id != func_id:
                        call_graph[func_id].add(match_id)
    return call_graph


def compute_coverage_status(
    source_ids: set[str],
    directly_tested: set[str],
    call_graph: dict[str, set[str]],
) -> dict[str, str]:
    """Determine test status for every function.

    Returns a dict mapping each function id to one of:
    - "direct" - called directly by at least one test
    - "indirect" - not called directly, but reachable via the
      call graph from a directly-tested function
    - "none" - no test coverage (direct or indirect)

    """
    status: dict[str, str] = {}
    for func_id in source_ids:
        status[func_id] = "direct" if func_id in directly_tested else "unknown"
    # breadth-first search through the call graph starting from directly-tested functions
    queue = list(directly_tested)
    while queue:
        caller = queue.pop(0)
        for callee in call_graph.get(caller, []):
            if status[callee] == "unknown":
                status[callee] = "indirect"
                queue.append(callee)
    # remaining unknown functions have no coverage at all
    for func_id in source_ids:
        if status[func_id] == "unknown":
            status[func_id] = "none"
    return status


def compute_indirect_paths(
    call_graph: dict[str, set[str]],
    directly_tested: set[str],
    func_to_test_details: dict[str, list[dict[str, Any]]],
    source_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Find every call chain from a test to each indirectly-tested function.

    For each directly-tested function, performs a BFS through the call
    graph. Whenever a function not in directly_tested is reached, a
    path entry is recorded showing which test invoked it, through
    which chain of production-function calls, and the file/line
    location of every step.

    Returns a dict mapping each indirectly-tested function id to a
    list of path entries, each with test and chain keys. Every
    chain element contains name, file, start_line, and end_line.

    """
    indirect_info: dict[str, list[dict[str, Any]]] = {}
    for func_id in sorted(directly_tested):
        for test_detail in func_to_test_details.get(func_id, []):
            queue: list[tuple[str, list[str]]] = [(func_id, [func_id])]
            visited: set[str] = {func_id}
            while queue:
                current, path = queue.pop(0)
                for callee in sorted(call_graph.get(current, set())):
                    if callee not in visited and callee not in directly_tested:
                        new_path = [*path, callee]
                        if callee not in indirect_info:
                            indirect_info[callee] = []
                        chain = [
                            {
                                "name": source_by_id[fn]["name"],
                                "file": source_by_id[fn]["file"],
                                "start_line": source_by_id[fn]["line"],
                                "end_line": source_by_id[fn]["end_line"],
                            }
                            for fn in new_path
                        ]
                        indirect_info[callee].append(
                            {
                                "test": {
                                    "name": test_detail["test_name"],
                                    "file": test_detail["test_file"],
                                    "start_line": test_detail[
                                        "test_start_line"
                                    ],
                                    "end_line": test_detail["test_end_line"],
                                },
                                "chain": chain,
                            }
                        )
                        visited.add(callee)
                        queue.append((callee, new_path))
    return indirect_info


def classify_and_report(
    source_by_id: dict[str, dict[str, Any]],
    directly_tested: set[str],
    call_graph: dict[str, set[str]],
    func_to_test_details: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Build the coverage report."""
    coverage = compute_coverage_status(
        set(source_by_id), directly_tested, call_graph
    )
    indirect_paths = compute_indirect_paths(
        call_graph,
        directly_tested,
        func_to_test_details,
        source_by_id,
    )
    report: dict[str, Any] = {
        "tool": REPORT_TOOL,
        "functions": {},
        "summary": {
            "total": 0,
            "directly_tested": 0,
            "indirectly_tested": 0,
            "untested": 0,
        },
        "indirectly_tested_list": [],
        "directly_tested_list": [],
        "untested_list": [],
    }
    for node_id, info in sorted(source_by_id.items()):
        entry: dict[str, Any] = {
            **info,
            "test_status": coverage[node_id],
            "directly_tested": coverage[node_id] == "direct",
        }
        report["functions"][info["id"]] = entry
        if coverage[node_id] == "direct":
            test_details = func_to_test_details.get(node_id, [])
            report["directly_tested_list"].append(
                {**info, "direct_calls_by_tests": test_details}
            )
        elif coverage[node_id] == "indirect":
            paths = indirect_paths.get(node_id, [])
            report["indirectly_tested_list"].append(
                {**info, "indirect_paths": paths}
            )
        elif coverage[node_id] == "none":
            report["untested_list"].append({**info})
    s = report["summary"]
    s["total"] = len(source_by_id)
    s["directly_tested"] = sum(
        1 for v in report["functions"].values() if v["directly_tested"]
    )
    s["indirectly_tested"] = sum(
        1
        for v in report["functions"].values()
        if v["test_status"] == "indirect"
    )
    s["untested"] = sum(
        1 for v in report["functions"].values() if v["test_status"] == "none"
    )
    return report


def print_summary(report: dict[str, Any]) -> None:
    """Print a human-readable summary using rich formatting."""
    s = report["summary"]
    table = Table(
        title="Function Coverage Summary",
        box=box.SIMPLE,
        title_style=Style(bold=True),
        header_style=Style(bold=True),
    )
    table.add_column("Status", style="bold")
    table.add_column("Count", justify="right")
    table.add_column("Percent", justify="right")
    total = s["total"] or 1
    table.add_row(
        "Directly tested",
        str(s["directly_tested"]),
        f"{s['directly_tested'] / total * 100:.1f}%",
    )
    table.add_row(
        "Indirectly tested only",
        str(s["indirectly_tested"]),
        f"{s['indirectly_tested'] / total * 100:.1f}%",
    )
    table.add_row(
        "Untested",
        str(s["untested"]),
        f"{s['untested'] / total * 100:.1f}%",
    )
    CONSOLE.print(table)
    if report["indirectly_tested_list"]:
        CONSOLE.print(Rule("Indirectly Tested Functions", style="yellow"))
        CONSOLE.print()
        for entry in report["indirectly_tested_list"]:
            CONSOLE.print(
                f"  {entry['name']}  ({entry['file']}:{entry['line']})"
            )
    if report["untested_list"]:
        CONSOLE.print()
        CONSOLE.print(Rule("Not Tested Functions", style="red"))
        CONSOLE.print()
        for entry in report["untested_list"]:
            CONSOLE.print(
                f"  {entry['name']}  ({entry['file']}:{entry['line']})"
            )


def demo_api(engine: QueryEngine) -> list[str]:
    """Demonstrate the trailmark programmatic API and return lines."""
    lines: list[str] = []
    langs = supported_languages()
    lines.append(f"trailmark supports {len(langs)} languages.")
    summary = engine.summary()
    lines.append(
        f"  QueryEngine.from_graph built {summary['total_nodes']} nodes "
        f"with {summary['call_edges']} call edges."
    )
    return lines


def main(  # noqa: PLR0915
    threshold: int = typer.Option(
        DEFAULT_THRESHOLD,
        "--threshold",
        "-t",
        help="Minimum percentage of directly tested functions required.",
    ),
    output: Path = typer.Option(
        DEFAULT_OUTPUT,
        "--output",
        "-o",
        help="Path for the JSON report file.",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose/--no-verbose",
        help="Show detailed coverage analysis output.",
    ),
) -> None:
    """Run the coverage analysis and check against a direct-test threshold."""
    project_root = Path(__file__).resolve().parent.parent
    source_dir = project_root / "src" / SOURCE_DIR
    test_dir = project_root / "tests"
    report_path = Path(output)
    if not report_path.is_absolute():
        report_path = project_root / report_path
    # analysis phase
    graph = parse_directory(str(project_root), language="python")
    engine = QueryEngine.from_graph(graph)
    analysis_lines: list[str] = []
    for line in demo_api(engine):
        analysis_lines.append(line)
    analysis_lines.append("")
    analysis_lines.append(
        "Extracting source functions from the trailmark graph ..."
    )
    all_functions = find_source_functions(graph, source_dir, project_root)
    analysis_lines.append(f"  Found {len(all_functions)} functions.")
    analysis_lines.append("")
    analysis_lines.append("Searching for direct calls in test functions ...")
    test_units = find_test_function_ids(graph, test_dir)
    directly_tested, func_to_test_details, resolution = find_direct_test_calls(
        engine, test_units, all_functions, project_root
    )
    analysis_lines.append(
        f"  Found {len(directly_tested)} directly-tested functions."
    )
    analysis_lines.append(
        f"  Resolution: {resolution['resolved_direct_calls']} resolved "
        f"edges, {resolution['unique_name_matches']} unique-name matches, "
        f"{resolution['ambiguous_proxy_calls']} ambiguous proxies skipped, "
        f"{resolution['unmatched_proxy_calls']} unmatched proxies."
    )
    analysis_lines.append("")
    analysis_lines.append("Building internal call graph ...")
    call_graph = build_call_graph(engine, all_functions)
    total_edges = sum(len(v) for v in call_graph.values())
    analysis_lines.append(f"  Found {total_edges} internal call edges.")
    analysis_lines.append("")
    analysis_lines.append(f"Report written to {report_path}")
    if verbose:
        CONSOLE.print()
        CONSOLE.print(Rule("Coverage Analysis", style="blue"))
        CONSOLE.print()
        for line in analysis_lines:
            CONSOLE.print(line)
    # build report
    report = classify_and_report(
        all_functions,
        directly_tested,
        call_graph,
        func_to_test_details,
    )
    report_path.write_text(json.dumps(report, indent=2), encoding=UTF8)
    if verbose:
        CONSOLE.print()
        CONSOLE.print(Rule("Coverage Results", style="dim"))
        CONSOLE.print()
        print_summary(report)
        CONSOLE.print()
    # threshold check
    s = report["summary"]
    total = s["total"]
    direct_count = s["directly_tested"]
    pct = (direct_count / total * 100) if total > 0 else MIN_PERCENT
    if pct < threshold:
        if verbose:
            CONSOLE.print()
        CONSOLE.print(Rule("Failure", style="red"))
        CONSOLE.print()
        CONSOLE.print(
            f"Only {pct:.1f}% of functions are directly tested "
            f"(threshold: {threshold}%)."
        )
        if not verbose:
            for entry in report["indirectly_tested_list"]:
                CONSOLE.print(
                    f"  {entry['name']}  ({entry['file']}:{entry['line']})"
                )
            for entry in report["untested_list"]:
                CONSOLE.print(
                    f"  {entry['name']}  ({entry['file']}:{entry['line']})"
                )
        raise typer.Exit(code=1)
    if verbose:
        CONSOLE.print()
        CONSOLE.print(Rule("Pass", style="green"))
        CONSOLE.print(
            f"All functions have sufficient direct test coverage "
            f"({pct:.1f}% >= {threshold}%)."
        )
    else:
        CONSOLE.print(
            f"[green]Success[/green]: All functions have sufficient "
            f"direct test coverage ({pct:.1f}% >= {threshold}%)."
        )


if __name__ == "__main__":
    typer.run(main)
