"""Tests for the trailmark direct-test coverage checker in scripts.tsc_trailmark."""

from pathlib import Path

from trailmark.models.graph import CodeGraph
from trailmark.parse import parse_directory
from trailmark.query.api import QueryEngine

from scripts import tsc_trailmark

UTF8 = "utf-8"
SOURCE = "src/formtuist"
FUNCTION_COUNT = 4
ALPHA_END_LINE = 3
UNRESOLVED_COUNT = 2
SIXTY_PERCENT = 60.0
FULL_PERCENT = 100.0
SOURCE_CODE = (
    "def alpha() -> None:\n"
    '    """Alpha docstring."""\n'
    "    beta()\n"
    "\n"
    "\n"
    "def beta() -> None:\n"
    '    """Beta docstring."""\n'
    "    return None\n"
    "\n"
    "\n"
    "class FirstScreen:\n"
    "    def compose(self) -> None:\n"
    "        return None\n"
    "\n"
    "\n"
    "class SecondScreen:\n"
    "    def compose(self) -> None:\n"
    "        return None\n"
)
TEST_CODE = (
    "from formtuist.mod import alpha\n"
    "\n"
    "\n"
    "def test_alpha() -> None:\n"
    "    alpha()\n"
    "\n"
    "\n"
    "def test_compose_via_screen() -> None:\n"
    "    screen = FirstScreen()\n"
    "    screen.compose()\n"
)


def _write(path: Path, content: str) -> Path:
    """Write content to a file, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding=UTF8)
    return path


def _build_project(tmp_path: Path) -> Path:
    """Write a small project with source and test files into tmp_path."""
    _write(tmp_path / SOURCE / "mod.py", SOURCE_CODE)
    _write(tmp_path / "tests" / "test_mod.py", TEST_CODE)
    return tmp_path


def _parse(tmp_path: Path) -> tuple[CodeGraph, QueryEngine]:
    """Parse a project root and return its trailmark graph and engine."""
    graph = parse_directory(str(tmp_path), language="python")
    engine = QueryEngine.from_graph(graph)
    return graph, engine


def test_find_source_functions_records_functions_and_methods(
    tmp_path: Path,
) -> None:
    """find_source_functions keeps functions and methods with locations."""
    project_root = _build_project(tmp_path)
    graph, _ = _parse(project_root)
    functions = tsc_trailmark.find_source_functions(
        graph, project_root / SOURCE, project_root
    )
    names = {info["name"] for info in functions.values()}
    assert names == {"alpha", "beta", "compose"}
    assert len(functions) == FUNCTION_COUNT
    alpha = next(
        info for info in functions.values() if info["name"] == "alpha"
    )
    assert alpha["id"] == "src/formtuist/mod.py:alpha:1"
    assert alpha["file"] == "src/formtuist/mod.py"
    assert alpha["line"] == 1
    assert alpha["end_line"] == ALPHA_END_LINE
    assert alpha["trailmark_id"] == "src.formtuist.mod:alpha"


def test_find_source_functions_skips_init_files_and_dunders(
    tmp_path: Path,
) -> None:
    """find_source_functions excludes __init__.py functions and dunders."""
    _write(
        tmp_path / SOURCE / "__init__.py",
        'def main() -> None:\n    """Entry point."""\n    return None\n',
    )
    _write(
        tmp_path / SOURCE / "widget.py",
        "class Widget:\n"
        "    def __init__(self) -> None:\n"
        "        self.value = 1\n"
        "\n"
        "    def render(self) -> None:\n"
        "        return None\n",
    )
    graph, _ = _parse(tmp_path)
    functions = tsc_trailmark.find_source_functions(
        graph, tmp_path / SOURCE, tmp_path
    )
    names = {info["name"] for info in functions.values()}
    assert names == {"render"}


def test_find_test_function_ids_finds_test_functions(tmp_path: Path) -> None:
    """find_test_function_ids collects test_* functions from test files."""
    project_root = _build_project(tmp_path)
    graph, _ = _parse(project_root)
    test_units = tsc_trailmark.find_test_function_ids(
        graph, project_root / "tests"
    )
    names = {unit.name for unit in test_units.values()}
    assert names == {"test_alpha", "test_compose_via_screen"}


def test_find_direct_test_calls_skips_ambiguous_names(
    tmp_path: Path,
) -> None:
    """find_direct_test_calls credits resolved calls but not ambiguous ones."""
    project_root = _build_project(tmp_path)
    graph, engine = _parse(project_root)
    source_by_id = tsc_trailmark.find_source_functions(
        graph, project_root / SOURCE, project_root
    )
    test_units = tsc_trailmark.find_test_function_ids(
        graph, project_root / "tests"
    )
    directly_tested, details, resolution, maybe_direct = (
        tsc_trailmark.find_direct_test_calls(
            engine, test_units, source_by_id, project_root
        )
    )
    tested_names = {source_by_id[fid]["name"] for fid in directly_tested}
    assert "alpha" in tested_names
    assert "beta" not in tested_names
    assert "compose" not in tested_names
    maybe_names = {source_by_id[fid]["name"] for fid in maybe_direct}
    assert maybe_names == {"compose"}
    assert resolution["resolved_direct_calls"] >= 1
    assert resolution["ambiguous_proxy_calls"] >= 1
    assert details


def test_find_direct_test_calls_credits_unique_name_proxy(
    tmp_path: Path,
) -> None:
    """find_direct_test_calls credits a unique dotted call by name."""
    _write(
        tmp_path / SOURCE / "server.py",
        "class FormtuistServer:\n"
        "    def _make_app(self) -> None:\n"
        '        """Build the web app."""\n'
        "        return None\n",
    )
    _write(
        tmp_path / "tests" / "test_server.py",
        "import formtuist.server as server\n"
        "\n"
        "\n"
        "def test_make_app() -> None:\n"
        "    obj = server.FormtuistServer()\n"
        "    obj._make_app()\n",
    )
    graph, engine = _parse(tmp_path)
    source_by_id = tsc_trailmark.find_source_functions(
        graph, tmp_path / SOURCE, tmp_path
    )
    test_units = tsc_trailmark.find_test_function_ids(
        graph, tmp_path / "tests"
    )
    directly_tested, details, resolution, _ = (
        tsc_trailmark.find_direct_test_calls(
            engine, test_units, source_by_id, tmp_path
        )
    )
    tested_names = {source_by_id[fid]["name"] for fid in directly_tested}
    assert "_make_app" in tested_names
    assert resolution["unique_name_matches"] >= 1
    assert details


def test_build_call_graph_records_resolved_internal_calls(
    tmp_path: Path,
) -> None:
    """build_call_graph connects alpha to beta via a resolved edge."""
    project_root = _build_project(tmp_path)
    graph, engine = _parse(project_root)
    source_by_id = tsc_trailmark.find_source_functions(
        graph, project_root / SOURCE, project_root
    )
    call_graph = tsc_trailmark.build_call_graph(engine, source_by_id)
    alpha_id = next(
        fid for fid, info in source_by_id.items() if info["name"] == "alpha"
    )
    beta_id = next(
        fid for fid, info in source_by_id.items() if info["name"] == "beta"
    )
    assert beta_id in call_graph[alpha_id]
    for func_id, callees in call_graph.items():
        assert func_id not in callees


def test_compute_coverage_status_classifies_direct_indirect_none() -> None:
    """compute_coverage_status labels every function correctly."""
    source_ids = {"a", "b", "c", "d"}
    directly_tested = {"a"}
    call_graph = {"a": {"b"}, "b": {"c"}}
    status = tsc_trailmark.compute_coverage_status(
        source_ids, directly_tested, call_graph, set()
    )
    assert status["a"] == "direct"
    assert status["b"] == "indirect"
    assert status["c"] == "indirect"
    assert status["d"] == "none"


def test_compute_coverage_status_marks_unresolved() -> None:
    """compute_coverage_status labels maybe functions as unresolved."""
    source_ids = {"a", "b", "c"}
    directly_tested = {"a"}
    call_graph = {"a": {"b"}}
    maybe_direct = {"b", "c"}
    status = tsc_trailmark.compute_coverage_status(
        source_ids, directly_tested, call_graph, maybe_direct
    )
    assert status["a"] == "direct"
    assert status["b"] == "indirect"
    assert status["c"] == "unresolved"


def test_compute_direct_percentage_excludes_unresolved() -> None:
    """compute_direct_percentage drops unresolved from the denominator."""
    summary = {
        "total": 10,
        "directly_tested": 3,
        "indirectly_tested": 2,
        "untested": 5,
        "unresolved": 5,
    }
    assert tsc_trailmark.compute_direct_percentage(summary) == SIXTY_PERCENT
    assert tsc_trailmark.compute_direct_percentage({}) == FULL_PERCENT


def test_classify_and_report_builds_consistent_summary(tmp_path: Path) -> None:
    """classify_and_report produces a report with matching counts."""
    project_root = _build_project(tmp_path)
    graph, engine = _parse(project_root)
    source_by_id = tsc_trailmark.find_source_functions(
        graph, project_root / SOURCE, project_root
    )
    test_units = tsc_trailmark.find_test_function_ids(
        graph, project_root / "tests"
    )
    directly_tested, details, _, maybe_direct = (
        tsc_trailmark.find_direct_test_calls(
            engine, test_units, source_by_id, project_root
        )
    )
    call_graph = tsc_trailmark.build_call_graph(engine, source_by_id)
    report = tsc_trailmark.classify_and_report(
        source_by_id, directly_tested, call_graph, details, maybe_direct
    )
    s = report["summary"]
    assert s["total"] == len(source_by_id)
    assert s["total"] == len(report["functions"])
    assert s["directly_tested"] == len(report["directly_tested_list"])
    assert s["indirectly_tested"] == len(report["indirectly_tested_list"])
    assert s["untested"] == len(report["untested_list"])
    assert s["unresolved"] == len(report["unresolved_list"])
    total = (
        s["directly_tested"]
        + s["indirectly_tested"]
        + s["untested"]
        + s["unresolved"]
    )
    assert total == s["total"]
    assert s["unresolved"] == UNRESOLVED_COUNT


def test_report_uses_shared_function_ids(tmp_path: Path) -> None:
    """Report ids use the shared file:name:line scheme."""
    project_root = _build_project(tmp_path)
    graph, engine = _parse(project_root)
    source_by_id = tsc_trailmark.find_source_functions(
        graph, project_root / SOURCE, project_root
    )
    test_units = tsc_trailmark.find_test_function_ids(
        graph, project_root / "tests"
    )
    directly_tested, details, _, maybe_direct = (
        tsc_trailmark.find_direct_test_calls(
            engine, test_units, source_by_id, project_root
        )
    )
    call_graph = tsc_trailmark.build_call_graph(engine, source_by_id)
    report = tsc_trailmark.classify_and_report(
        source_by_id, directly_tested, call_graph, details, maybe_direct
    )
    ids = set(report["functions"])
    assert "src/formtuist/mod.py:alpha:1" in ids
    assert "src/formtuist/mod.py:compose:12" in ids
    assert "src/formtuist/mod.py:compose:17" in ids
