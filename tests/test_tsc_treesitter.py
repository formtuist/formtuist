"""Tests for the tree-sitter direct-test coverage checker in scripts.tsc_treesitter."""

from pathlib import Path

from scripts import tsc_treesitter

UTF8 = "utf-8"
SOURCE = "src/formtuitous"
FUNCTION_COUNT = 4
ALPHA_END_LINE = 3
TEST_ALPHA_START_LINE = 4
TEST_ALPHA_END_LINE = 5
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
    "from formtuitous.mod import alpha\n"
    "\n"
    "\n"
    "def test_alpha() -> None:\n"
    "    alpha()\n"
    "\n"
    "\n"
    "def test_compose_via_screen() -> None:\n"
    "    screen = FirstScreen()\n"
    "    screen.compose()\n"
    "\n"
    "\n"
    "def helper() -> None:\n"
    "    beta()\n"
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


def test_find_function_definitions_finds_functions_and_locations(
    tmp_path: Path,
) -> None:
    """find_function_definitions records names, files, and line ranges."""
    project_root = _build_project(tmp_path)
    functions = tsc_treesitter.find_function_definitions(
        project_root / SOURCE, project_root
    )
    assert len(functions) == FUNCTION_COUNT
    assert "src/formtuitous/mod.py:alpha:1" in functions
    assert "src/formtuitous/mod.py:beta:6" in functions
    alpha = functions["src/formtuitous/mod.py:alpha:1"]
    assert alpha["name"] == "alpha"
    assert alpha["file"] == "src/formtuitous/mod.py"
    assert alpha["line"] == 1
    assert alpha["end_line"] == ALPHA_END_LINE
    assert alpha["id"] == "src/formtuitous/mod.py:alpha:1"


def test_find_function_definitions_keeps_duplicate_names_distinct(
    tmp_path: Path,
) -> None:
    """find_function_definitions keys duplicate names by their line."""
    project_root = _build_project(tmp_path)
    functions = tsc_treesitter.find_function_definitions(
        project_root / SOURCE, project_root
    )
    assert "src/formtuitous/mod.py:compose:12" in functions
    assert "src/formtuitous/mod.py:compose:17" in functions


def test_find_function_definitions_skips_dunder_methods(
    tmp_path: Path,
) -> None:
    """find_function_definitions excludes dunder-named methods."""
    _write(
        tmp_path / SOURCE / "widget.py",
        "class Widget:\n"
        "    def __init__(self) -> None:\n"
        "        self.value = 1\n"
        "\n"
        "    def render(self) -> None:\n"
        "        return None\n",
    )
    functions = tsc_treesitter.find_function_definitions(
        tmp_path / SOURCE, tmp_path
    )
    names = {info["name"] for info in functions.values()}
    assert names == {"render"}


def test_find_function_definitions_skips_init_files(tmp_path: Path) -> None:
    """find_function_definitions ignores functions inside __init__.py."""
    _write(
        tmp_path / SOURCE / "__init__.py",
        'def main() -> None:\n    """Entry point."""\n    return None\n',
    )
    functions = tsc_treesitter.find_function_definitions(
        tmp_path / SOURCE, tmp_path
    )
    assert functions == {}


def test_find_direct_test_calls_finds_bare_and_dotted_calls(
    tmp_path: Path,
) -> None:
    """find_direct_test_calls detects bare and dotted direct calls."""
    project_root = _build_project(tmp_path)
    all_functions = tsc_treesitter.find_function_definitions(
        project_root / SOURCE, project_root
    )
    target_funcs = {info["name"] for info in all_functions.values()}
    directly_called, details = tsc_treesitter.find_direct_test_calls(
        project_root / "tests", target_funcs, project_root
    )
    assert "alpha" in directly_called
    assert "compose" in directly_called
    assert "beta" not in directly_called
    alpha_details = details["alpha"]
    assert alpha_details[0]["test_name"] == "test_alpha"
    assert alpha_details[0]["test_file"] == "tests/test_mod.py"
    assert alpha_details[0]["test_start_line"] == TEST_ALPHA_START_LINE
    assert alpha_details[0]["test_end_line"] == TEST_ALPHA_END_LINE


def test_find_direct_test_calls_ignores_helper_and_conftest(
    tmp_path: Path,
) -> None:
    """find_direct_test_calls ignores calls outside test_* functions."""
    _write(tmp_path / "tests" / "test_mod.py", TEST_CODE)
    _write(
        tmp_path / "tests" / "conftest.py",
        "def fixture_alpha() -> None:\n    alpha()\n",
    )
    target_funcs = {"alpha", "beta", "compose"}
    directly_called, _ = tsc_treesitter.find_direct_test_calls(
        tmp_path / "tests", target_funcs, tmp_path
    )
    assert "alpha" in directly_called
    assert "beta" not in directly_called


def test_build_call_graph_records_internal_calls(tmp_path: Path) -> None:
    """build_call_graph connects alpha to beta and skips self calls."""
    project_root = _build_project(tmp_path)
    target_funcs = {"alpha", "beta", "compose"}
    call_graph = tsc_treesitter.build_call_graph(
        project_root / SOURCE, target_funcs
    )
    assert call_graph["alpha"] == {"beta"}
    assert call_graph["beta"] == set()
    for caller, callees in call_graph.items():
        assert caller not in callees


def test_compute_coverage_status_classifies_direct_indirect_none() -> None:
    """compute_coverage_status labels every function correctly."""
    all_functions = {
        "m:a:1": {"name": "a"},
        "m:b:2": {"name": "b"},
        "m:c:3": {"name": "c"},
        "m:d:4": {"name": "d"},
    }
    directly_tested = {"a"}
    call_graph = {"a": {"b"}, "b": {"c"}}
    status = tsc_treesitter.compute_coverage_status(
        all_functions, directly_tested, call_graph
    )
    assert status["m:a:1"] == "direct"
    assert status["m:b:2"] == "indirect"
    assert status["m:c:3"] == "indirect"
    assert status["m:d:4"] == "none"


def test_compute_indirect_paths_records_full_chain() -> None:
    """compute_indirect_paths records the chain from test to function."""
    all_functions = {
        "m:a:1": {"name": "a", "file": "f.py", "line": 1, "end_line": 2},
        "m:b:2": {"name": "b", "file": "f.py", "line": 4, "end_line": 5},
        "m:c:3": {"name": "c", "file": "f.py", "line": 7, "end_line": 8},
    }
    call_graph = {"a": {"b"}, "b": {"c"}}
    directly_tested = {"a"}
    details = {
        "a": [
            {
                "test_name": "test_a",
                "test_file": "tests/test_f.py",
                "test_start_line": 10,
                "test_end_line": 11,
            }
        ]
    }
    paths = tsc_treesitter.compute_indirect_paths(
        call_graph, directly_tested, details, all_functions
    )
    assert "c" in paths
    chain = paths["c"][0]["chain"]
    assert [step["name"] for step in chain] == ["a", "b", "c"]
    assert paths["c"][0]["test"]["name"] == "test_a"


def test_classify_and_report_builds_consistent_summary(tmp_path: Path) -> None:
    """classify_and_report produces a report with matching counts."""
    project_root = _build_project(tmp_path)
    all_functions = tsc_treesitter.find_function_definitions(
        project_root / SOURCE, project_root
    )
    target_funcs = {info["name"] for info in all_functions.values()}
    directly_tested, details = tsc_treesitter.find_direct_test_calls(
        project_root / "tests", target_funcs, project_root
    )
    call_graph = tsc_treesitter.build_call_graph(
        project_root / SOURCE, target_funcs
    )
    report = tsc_treesitter.classify_and_report(
        all_functions, directly_tested, call_graph, details
    )
    s = report["summary"]
    assert s["total"] == len(all_functions)
    assert s["total"] == len(report["functions"])
    assert s["directly_tested"] == len(report["directly_tested_list"])
    assert s["indirectly_tested"] == len(report["indirectly_tested_list"])
    assert s["untested"] == len(report["untested_list"])
    total = s["directly_tested"] + s["indirectly_tested"] + s["untested"]
    assert total == s["total"]
