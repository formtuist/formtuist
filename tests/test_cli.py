"""Tests for the formtuist CLI commands."""

import csv
import json
import os
import re
import sqlite3
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner, Result

from formtuist.cli import _display_db_dir, _package_version, app, main
from formtuist.database import (
    ATTEMPT_ID_ENV_NAME,
    get_responses,
    init_db,
    save_response,
)
from formtuist.version import FORMTUIST_VERSION

# regex to strip ANSI SGR escape sequences that Rich embeds in captured output
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


runner = CliRunner()

# expected scores shared by the grade command tests
EXPECTED_MC_POINTS = 10
EXPECTED_TEXT_POINTS = 10
EXPECTED_GRADE_TOTAL_PARTIAL = 10
EXPECTED_GRADE_TOTAL_FULL = 20
EXPECTED_GRADE_MAX = 20
EXPECTED_GRADE_PERCENT_PARTIAL = 50.0
EXPECTED_GRADE_PERCENT_FULL = 100.0
USAGE_ERROR_EXIT_CODE = 2


def _plain(result: Result) -> str:
    """Return captured stdout with Rich markup and ANSI codes removed."""
    return ANSI_ESCAPE_PATTERN.sub("", result.stdout)


def _plain_stderr(result: Result) -> str:
    """Return captured stderr with Rich markup and ANSI codes removed."""
    return ANSI_ESCAPE_PATTERN.sub("", result.stderr)


def _write_form(path: Path, data: dict) -> Path:
    """Write a form dict as JSON to a file and return the path."""
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestCheckCommand:
    """Tests for the `formtuist check` subcommand."""

    def test_check_valid_minimal(self, tmp_path: Path) -> None:
        """Check exits 0 and prints summary for a valid form."""
        form = {
            "name": "Test Form",
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Form: Test Form" in _plain(result)
        assert "Status: valid" in _plain(result)

    def test_check_shows_required_count(self, tmp_path: Path) -> None:
        """Check reports correct required and optional counts."""
        form = {
            "name": "Count Test",
            "questions": [
                {
                    "id": "a",
                    "text": "A?",
                    "type": "short_text",
                    "required": True,
                },
                {"id": "b", "text": "B?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Questions: 2 (1 required, 1 optional)" in _plain(result)

    def test_check_rejects_authoring_trap(self, tmp_path: Path) -> None:
        """Check exits 1 for a form with an authoring trap."""
        form = {
            "name": "Trap",
            "config": {"auto_grade": True},
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 1
        assert "auto_grade is enabled" in _plain_stderr(result)

    def test_check_clean_form_has_no_warnings(self, tmp_path: Path) -> None:
        """Check prints no warnings section for a clean form."""
        form = {
            "name": "Clean",
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Warnings:" not in _plain(result)

    def test_check_shows_graded(self, tmp_path: Path) -> None:
        """Check reports graded questions and auto-grade status."""
        form = {
            "name": "Graded Quiz",
            "config": {"auto_grade": True},
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "correct_answer": "yes",
                    "points": 5,
                },
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Graded: 1 question(s)" in _plain(result)
        assert "auto-grade is on" in _plain(result)

    def test_check_shows_no_grading(self, tmp_path: Path) -> None:
        """Check reports none when no questions have correct_answer."""
        form = {
            "name": "No Grade",
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Graded: none" in _plain(result)

    def test_check_invalid_form_exits_nonzero(self, tmp_path: Path) -> None:
        """Check exits non-zero with errors for invalid form JSON."""
        form = {
            "name": "Bad",
            "questions": [
                {"id": "q", "text": "?", "type": "slider"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 1
        assert "Form definition contains errors" in _plain_stderr(result)

    def test_check_missing_file(self) -> None:
        """Check exits non-zero for a nonexistent file."""
        result = runner.invoke(app, ["check", "/nonexistent/form.json"])
        assert result.exit_code != 0

    def test_check_shows_description(self, tmp_path: Path) -> None:
        """Check includes the form description when present."""
        form = {
            "name": "Described",
            "description": "A form with a description.",
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Description: A form with a description." in _plain(result)


class TestStubCommands:
    """Tests that stub commands exist and execute their bodies."""

    def test_display_help(self) -> None:
        """Display command accepts --help."""
        result = runner.invoke(app, ["display", "--help"])
        assert result.exit_code == 0
        assert "Display a form" in _plain(result)

    def test_serve_with_file(self, tmp_path: Path) -> None:
        """Serve command launches textual-serve."""
        form = _write_form(
            tmp_path / "form.json", {"name": "T", "questions": []}
        )
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            mock_instance = mock_server_cls.return_value
            result = runner.invoke(app, ["serve", str(form)])
            assert result.exit_code == 0
            mock_server_cls.assert_called_once()
            mock_instance.serve.assert_called_once()

    def test_publish_with_file(self, tmp_path: Path) -> None:
        """Publish validates a form and starts the bitbang publisher."""
        form = _write_form(
            tmp_path / "form.json", {"name": "Published", "questions": []}
        )
        with patch("formtuist.publisher.publish_form") as mock_publish:
            result = runner.invoke(
                app,
                [
                    "publish",
                    str(form),
                    "--host",
                    "localhost",
                    "--port",
                    "8123",
                    "--signaling",
                    "signal.example",
                    "--pin",
                    "1234",
                    "--ephemeral",
                ],
            )
        assert result.exit_code == 0
        mock_publish.assert_called_once_with(
            form,
            "localhost",
            8123,
            "signal.example",
            "1234",
            True,
            None,
            None,
            None,
        )

    def test_publish_rejects_invalid_form(self, tmp_path: Path) -> None:
        """Publish does not start bitbang for an invalid form."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "Invalid", "questions": [{"type": "unknown"}]},
        )
        with patch("formtuist.publisher.publish_form") as mock_publish:
            result = runner.invoke(app, ["publish", str(form)])
        assert result.exit_code == 1
        mock_publish.assert_not_called()

    def test_view_with_file(self, tmp_path: Path) -> None:
        """View launches datasette with the open flag from the venv."""
        db = _write_form(tmp_path / "resp.db", {"dummy": True})
        with patch("subprocess.run") as mock_run:
            result = runner.invoke(app, ["view", str(db)])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert args[0] == sys.executable
            assert args[1:3] == ["-m", "datasette"]
            assert "--open" in args
            assert "--open-browser" not in args

    def test_view_missing_datasette(self, tmp_path: Path) -> None:
        """View explains when datasette is not installed."""
        db = _write_form(tmp_path / "resp.db", {"dummy": True})
        with patch("importlib.util.find_spec", return_value=None) as mock_find:
            result = runner.invoke(app, ["view", str(db)])
        assert result.exit_code == 1
        assert "uv add datasette" in _plain(result)
        mock_find.assert_called_once_with("datasette")


class TestGradeCommand:
    """Tests for the `formtuist grade` subcommand."""

    def _quiz_form(self, tmp_path: Path) -> Path:
        """Write a small graded quiz form to a temp file."""
        return _write_form(
            tmp_path / "quiz.json",
            {
                "name": "Quiz",
                "questions": [
                    {
                        "id": "mc",
                        "text": "Pick?",
                        "type": "multiple_choice",
                        "choices": ["a", "b"],
                        "correct_answer": "a",
                        "points": 10,
                        "grading_type": "exact",
                    },
                    {
                        "id": "text",
                        "text": "Type?",
                        "type": "short_text",
                        "correct_answer": "def",
                        "points": 10,
                        "grading_type": "exact",
                    },
                ],
            },
        )

    def _responses_db(self, tmp_path: Path) -> Path:
        """Create a database with one saved response for the Quiz form."""
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        save_response(
            conn,
            "Quiz",
            {"mc": "a", "text": "wrong"},
            github_username="alice",
        )
        conn.close()
        return db_path

    def test_grade_shows_score_table(self, tmp_path: Path) -> None:
        """Grade prints a table with per-question and total scores."""
        form = self._quiz_form(tmp_path)
        db = self._responses_db(tmp_path)
        result = runner.invoke(app, ["grade", str(form), str(db)])
        assert result.exit_code == 0
        output = _plain(result)
        assert "Grades for Quiz" in output
        assert "Q1" in output
        assert "Q2" in output
        assert "alice" in output
        assert "Total" in output

    def test_grade_no_responses(self, tmp_path: Path) -> None:
        """Grade reports when the database has no responses."""
        form = self._quiz_form(tmp_path)
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        conn.close()
        result = runner.invoke(app, ["grade", str(form), str(db_path)])
        assert result.exit_code == 0
        assert "No responses for Quiz." in _plain(result)

    def test_grade_closes_connection_without_responses(
        self, tmp_path: Path
    ) -> None:
        """Grade closes the connection on the empty path too."""
        form = self._quiz_form(tmp_path)
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        conn.close()
        with patch("formtuist.cli.init_db") as mock_init:
            mock_conn = MagicMock()
            mock_init.return_value = mock_conn
            result = runner.invoke(app, ["grade", str(form), str(db_path)])
        assert result.exit_code == 0
        mock_conn.close.assert_called_once()

    def test_grade_filters_responses_by_form_name(
        self, tmp_path: Path
    ) -> None:
        """Grade only scores responses for the matching form."""
        form = self._quiz_form(tmp_path)
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        save_response(conn, "Other Form", {"mc": "a", "text": "def"})
        conn.close()
        result = runner.invoke(app, ["grade", str(form), str(db_path)])
        assert result.exit_code == 0
        assert "No responses for Quiz." in _plain(result)

    def test_grade_invalid_form(self, tmp_path: Path) -> None:
        """Grade exits 1 when the form is invalid."""
        form = _write_form(tmp_path / "bad.json", {"bad": "data"})
        db = self._responses_db(tmp_path)
        result = runner.invoke(app, ["grade", str(form), str(db)])
        assert result.exit_code == 1

    def test_grade_uses_stored_snapshot(self, tmp_path: Path) -> None:
        """Grade reports the stored snapshot instead of re-grading."""
        form = self._quiz_form(tmp_path)
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        stored = {
            "total": 20,
            "max": 20,
            "percentage": 100.0,
            "breakdown": [
                {
                    "id": "mc",
                    "text": "Pick?",
                    "answer": "a",
                    "correct_answer": "a",
                    "score": 10,
                    "max": 10,
                    "correct": True,
                    "language": None,
                },
                {
                    "id": "text",
                    "text": "Type?",
                    "answer": "wrong",
                    "correct_answer": "wrong",
                    "score": 10,
                    "max": 10,
                    "correct": True,
                    "language": None,
                },
            ],
            "graded_at": "2026-08-01T00:00:00+00:00",
        }
        save_response(
            conn,
            "Quiz",
            {"mc": "a", "text": "wrong"},
            github_username="alice",
            grade=stored,
        )
        conn.close()
        result = runner.invoke(app, ["grade", str(form), str(db_path)])
        assert result.exit_code == 0
        # the stored percentage 100 must appear, never a recomputed 50
        assert "100" in _plain(result)

    def test_grade_computes_without_writing(self, tmp_path: Path) -> None:
        """Grade computes missing snapshots but leaves the row unchanged."""
        form = self._quiz_form(tmp_path)
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        save_response(
            conn,
            "Quiz",
            {"mc": "a", "text": "wrong"},
            github_username="alice",
        )
        conn.close()
        result = runner.invoke(app, ["grade", str(form), str(db_path)])
        assert result.exit_code == 0
        assert "50" in _plain(result)
        conn = init_db(db_path)
        row = get_responses(conn)[0]
        conn.close()
        assert row["grade_json"] is None

    def test_grade_recompute_writes_snapshot(self, tmp_path: Path) -> None:
        """Grade --recompute re-grades and persists fresh snapshots."""
        form = self._quiz_form(tmp_path)
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        save_response(
            conn,
            "Quiz",
            {"mc": "a", "text": "wrong"},
            github_username="alice",
        )
        conn.close()
        result = runner.invoke(
            app, ["grade", str(form), str(db_path), "--recompute"]
        )
        assert result.exit_code == 0
        conn = init_db(db_path)
        row = get_responses(conn)[0]
        conn.close()
        assert row["grade_json"] is not None
        assert row["grade_json"]["total"] == EXPECTED_GRADE_TOTAL_PARTIAL
        assert row["grade_json"]["max"] == EXPECTED_GRADE_MAX
        assert (
            row["grade_json"]["percentage"] == EXPECTED_GRADE_PERCENT_PARTIAL
        )

    def test_check_with_code_dir(self, tmp_path: Path) -> None:
        """Check resolves code files against --code-dir."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "snippet.py").write_text("x = 1\n", encoding="utf-8")
        form = {
            "name": "T",
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "code": {"language": "python", "file": "snippet.py"},
                },
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(
            app, ["check", str(path), "--code-dir", str(code_dir)]
        )
        assert result.exit_code == 0
        assert "Status: valid" in _plain(result)

    def test_check_fails_without_code_dir(self, tmp_path: Path) -> None:
        """Check fails when code files are not next to the form."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        (code_dir / "snippet.py").write_text("x = 1\n", encoding="utf-8")
        form = {
            "name": "T",
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "code": {"language": "python", "file": "snippet.py"},
                },
            ],
        }
        path = _write_form(tmp_path / "form.json", form)
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 1

    def test_serve_with_code_dir(self, tmp_path: Path) -> None:
        """Serve passes --code-dir to the display subprocess."""
        code_dir = tmp_path / "code"
        code_dir.mkdir()
        form = _write_form(
            tmp_path / "form.json", {"name": "T", "questions": []}
        )
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            result = runner.invoke(
                app,
                ["serve", str(form), "--code-dir", str(code_dir)],
            )
            assert result.exit_code == 0
            cmd_arg = mock_server_cls.call_args[0][0]
            assert f"--code-dir {code_dir}" in cmd_arg


class TestExportCommand:
    """Tests for the `formtuist export` subcommand."""

    def _responses_db(self, tmp_path: Path) -> Path:
        """Create a database with one graded response."""
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        grade: dict[str, Any] = {
            "total": EXPECTED_GRADE_TOTAL_FULL,
            "max": EXPECTED_GRADE_MAX,
            "percentage": EXPECTED_GRADE_PERCENT_FULL,
            "breakdown": [],
            "graded_at": "2026-08-01T00:00:00+00:00",
        }
        save_response(
            conn,
            "Quiz",
            {"q1": "a", "q2": 3},
            github_username="alice",
            grade=grade,
        )
        conn.close()
        return db_path

    def test_export_csv_writes_file(self, tmp_path: Path) -> None:
        """Export --format csv writes a CSV file and confirms."""
        db = self._responses_db(tmp_path)
        out = tmp_path / "out.csv"
        result = runner.invoke(
            app, ["export", str(db), "--format", "csv", "--output", str(out)]
        )
        assert result.exit_code == 0
        assert "Exported 1 response(s) to" in _plain(result)
        with out.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        assert rows[0]["form_name"] == "Quiz"
        assert rows[0]["q1"] == "a"
        assert rows[0]["total"] == str(EXPECTED_GRADE_TOTAL_FULL)

    def test_export_json_writes_array(self, tmp_path: Path) -> None:
        """Export --format json writes a JSON array."""
        db = self._responses_db(tmp_path)
        out = tmp_path / "out.json"
        result = runner.invoke(
            app, ["export", str(db), "--format", "json", "--output", str(out)]
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["q1"] == "a"
        assert data[0]["github_username"] == "alice"
        assert data[0]["total"] == EXPECTED_GRADE_TOTAL_FULL

    def test_export_jsonl_writes_lines(self, tmp_path: Path) -> None:
        """Export --format jsonl writes one object per line."""
        db = self._responses_db(tmp_path)
        out = tmp_path / "out.jsonl"
        result = runner.invoke(
            app, ["export", str(db), "--format", "jsonl", "--output", str(out)]
        )
        assert result.exit_code == 0
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0])["q1"] == "a"

    def test_export_sqlite_writes_flat_table(self, tmp_path: Path) -> None:
        """Export --format sqlite writes a browsable flat table."""
        db = self._responses_db(tmp_path)
        out = tmp_path / "out.db"
        result = runner.invoke(
            app,
            ["export", str(db), "--format", "sqlite", "--output", str(out)],
        )
        assert result.exit_code == 0
        conn = sqlite3.connect(str(out))
        try:
            rows = conn.execute(
                "SELECT form_name, q1 FROM responses_flat"
            ).fetchall()
        finally:
            conn.close()
        assert rows[0] == ("Quiz", "a")

    def test_export_form_name_filters(self, tmp_path: Path) -> None:
        """Export --form-name only includes matching responses."""
        db = self._responses_db(tmp_path)
        conn = init_db(db)
        save_response(conn, "Other", {"q1": "z"})
        conn.close()
        out = tmp_path / "out.json"
        result = runner.invoke(
            app,
            [
                "export",
                str(db),
                "--format",
                "json",
                "--output",
                str(out),
                "--form-name",
                "Quiz",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["form_name"] == "Quiz"

    def test_export_no_responses(self, tmp_path: Path) -> None:
        """Export reports when there are no responses to export."""
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        conn.close()
        out = tmp_path / "out.json"
        result = runner.invoke(
            app,
            ["export", str(db_path), "--format", "json", "--output", str(out)],
        )
        assert result.exit_code == 0
        assert "No responses to export." in _plain(result)
        assert not out.exists()

    def test_export_requires_output(self, tmp_path: Path) -> None:
        """Export without --output is a usage error."""
        db = self._responses_db(tmp_path)
        result = runner.invoke(app, ["export", str(db), "--format", "csv"])
        assert result.exit_code == USAGE_ERROR_EXIT_CODE

    def test_export_rejects_unknown_format(self, tmp_path: Path) -> None:
        """Export rejects an unknown --format value."""
        db = self._responses_db(tmp_path)
        out = tmp_path / "out.csv"
        result = runner.invoke(
            app, ["export", str(db), "--format", "xml", "--output", str(out)]
        )
        assert result.exit_code == USAGE_ERROR_EXIT_CODE


class TestExampleFormsCLI:
    """Integration tests: formtuist check against all example files."""

    EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

    @pytest.mark.parametrize(
        "filename",
        [
            "all_types.json",
            "anonymous_poll.json",
            "attendance.json",
            "authenticated.json",
            "minimal.json",
            "minimal_auth.json",
            "method_invocation_quiz.json",
            "quiz.json",
            "survey.json",
            "yes_no_quiz.json",
        ],
    )
    def test_valid_example_exits_zero(self, filename: str) -> None:
        """Check exits 0 for each valid example form."""
        path = self.EXAMPLES_DIR / filename
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 0
        assert "Status: valid" in _plain(result)

    @pytest.mark.parametrize(
        "filename",
        [
            "invalid_checkbox_no_choices.json",
            "invalid_duplicate_ids.json",
            "invalid_multiple_choice_one_choice.json",
            "invalid_rating_max_less_than_min.json",
            "invalid_single_submission_no_auth.json",
            "invalid_unknown_question_type.json",
        ],
    )
    def test_invalid_example_exits_nonzero(self, filename: str) -> None:
        """Check exits 1 for each invalid example form."""
        path = self.EXAMPLES_DIR / filename
        result = runner.invoke(app, ["check", str(path)])
        assert result.exit_code == 1
        assert "Form definition contains errors" in _plain_stderr(result)


class TestMainFunction:
    """Tests for the main entry point."""

    def test_app_help(self) -> None:
        """Running formtuist --help shows usage."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "formtuist" in _plain(result)

    def test_version_flag(self) -> None:
        """Running formtuist --version shows version info and exits."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert f"formtuist {FORMTUIST_VERSION}" in _plain(result)
        assert "Component" in _plain(result)
        assert "Version" in _plain(result)
        assert "textual" in _plain(result)
        assert "pydantic" in _plain(result)
        assert "rich" in _plain(result)

    def test_version_flag_sorted(self) -> None:
        """Dependency names are listed in alphabetical order."""
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        lines = [
            line.strip()
            for line in _plain(result).splitlines()
            if "│" in line and line.strip().startswith("│")
        ]
        names = [
            line.split("│")[1].strip()
            for line in lines
            if len(line.split("│")) >= 3  # noqa: PLR2004
        ]
        assert names == sorted(names)

    def test_version_flag_help(self) -> None:
        """The --help output mentions the --version flag."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "--version" in _plain(result)

    def test_package_version_unknown(self) -> None:
        """_package_version returns unknown for missing packages."""
        with patch(
            "formtuist.cli.version",
            side_effect=PackageNotFoundError("missing"),
        ):
            assert _package_version("not-a-real-package") == "unknown"

    def test_display_db_dir_outside_home(self) -> None:
        """_display_db_dir falls back to the full path outside home."""
        outside = Path("/opt/formtuist-data")
        with patch(
            "formtuist.cli.get_default_db_dir",
            return_value=outside,
        ):
            result = _display_db_dir()
        # compare against str(Path(...)) so the test is platform-agnostic
        # (Windows renders the path with backslashes)
        assert result == str(outside)
        assert "formtuist-data" in result

    def test_serve_help(self) -> None:
        """Serve command accepts --help."""
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "Serve a form" in _plain(result)

    def test_export_help(self) -> None:
        """Export command accepts --help."""
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0
        assert "Export responses" in _plain(result)

    def test_view_help(self) -> None:
        """View command accepts --help."""
        result = runner.invoke(app, ["view", "--help"])
        assert result.exit_code == 0
        assert "Browse responses" in _plain(result)

    def test_grade_help(self) -> None:
        """Grade command accepts --help."""
        result = runner.invoke(app, ["grade", "--help"])
        assert result.exit_code == 0
        assert "Grade responses" in _plain(result)


class TestDisplayCommand:
    """Tests for the display command body using mocking."""

    def test_display_valid_form_mocks_run(self, tmp_path: Path) -> None:
        """Display validates form and calls FormtuistApp.run."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "T", "description": "d", "questions": []},
        )
        db_dir = tmp_path / "db_out"
        with patch("formtuist.tui.app.FormtuistApp") as mock_app_cls:
            mock_instance = mock_app_cls.return_value
            result = runner.invoke(
                app, ["display", str(form), "--db-dir", str(db_dir)]
            )
            assert result.exit_code == 0
            expected_db_path = db_dir / "responses.db"
            mock_app_cls.assert_called_once_with(form, expected_db_path)
            mock_instance.run.assert_called_once()

    def test_display_invalid_form_exits(self, tmp_path: Path) -> None:
        """Display exits 1 for an invalid form."""
        path = _write_form(tmp_path / "bad.json", {"bad": "data"})
        with patch("formtuist.tui.app.FormtuistApp") as mock_app_cls:
            result = runner.invoke(app, ["display", str(path)])
            assert result.exit_code == 1
            mock_app_cls.assert_not_called()

    def test_main_calls_app(self) -> None:
        """main() invokes the typer app."""
        with patch("formtuist.cli.app") as mock_app:
            main()
            mock_app.assert_called_once()

    def test_display_has_no_serve_flag(self, tmp_path: Path) -> None:
        """Display command no longer accepts --serve."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "T", "questions": []},
        )
        with patch("formtuist.tui.app.FormtuistApp") as mock_app_cls:
            result = runner.invoke(app, ["display", str(form), "--serve"])
            assert result.exit_code != 0
            mock_app_cls.assert_not_called()


class TestServeCommand:
    """Tests for the serve command."""

    def test_serve_mocks_server(self, tmp_path: Path) -> None:
        """Serve parses the form and starts textual-serve."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "ServedForm", "questions": []},
        )
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            mock_instance = mock_server_cls.return_value
            result = runner.invoke(app, ["serve", str(form)])
            assert result.exit_code == 0
            mock_server_cls.assert_called_once()
            mock_instance.serve.assert_called_once()

    def test_serve_with_db_dir(self, tmp_path: Path) -> None:
        """Serve --db-dir passes the directory to the subprocess."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "ServedForm", "questions": []},
        )
        db_dir = tmp_path / "custom_db"
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            result = runner.invoke(
                app,
                ["serve", str(form), "--db-dir", str(db_dir)],
            )
            assert result.exit_code == 0
            mock_server_cls.assert_called_once()
            cmd_arg = mock_server_cls.call_args[0][0]
            assert str(db_dir) in cmd_arg

    def test_serve_with_database_name(self, tmp_path: Path) -> None:
        """Serve --database-name passes the name to the subprocess."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "ServedForm", "questions": []},
        )
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            result = runner.invoke(
                app,
                [
                    "serve",
                    str(form),
                    "--database-name",
                    "quiz.db",
                ],
            )
            assert result.exit_code == 0
            mock_server_cls.assert_called_once()
            cmd_arg = mock_server_cls.call_args[0][0]
            assert "quiz.db" in cmd_arg

    def test_serve_with_host_and_port(self, tmp_path: Path) -> None:
        """Serve passes host and port to textual-serve."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "ServedForm", "questions": []},
        )
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            mock_instance = mock_server_cls.return_value
            result = runner.invoke(
                app,
                [
                    "serve",
                    str(form),
                    "--host",
                    "100.64.1.1",
                    "--port",
                    "9000",
                ],
            )
            assert result.exit_code == 0
            kwargs = mock_server_cls.call_args.kwargs
            assert kwargs["host"] == "100.64.1.1"
            assert kwargs["port"] == 9000  # noqa: PLR2004
            mock_instance.serve.assert_called_once()

    def test_serve_sets_attempt_id_env(self, tmp_path: Path) -> None:
        """Serve injects one shared attempt id for its spawned displays."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "ServedForm", "questions": []},
        )
        previous = os.environ.get(ATTEMPT_ID_ENV_NAME)
        try:
            with patch("formtuist.server.FormtuistServer"):
                result = runner.invoke(app, ["serve", str(form)])
            assert result.exit_code == 0
            assert os.environ.get(ATTEMPT_ID_ENV_NAME)
        finally:
            if previous is None:
                os.environ.pop(ATTEMPT_ID_ENV_NAME, None)
            else:
                os.environ[ATTEMPT_ID_ENV_NAME] = previous


class TestSchemaCommand:
    """Tests for the schema command."""

    def test_schema_prints_json(self) -> None:
        """Schema command prints JSON schema output."""
        result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert '"$defs"' in _plain(result)
        assert "questions" in _plain(result)

    def test_schema_contains_question_types(self) -> None:
        """Schema includes the question type definitions."""
        result = runner.invoke(app, ["schema"])
        assert result.exit_code == 0
        assert "ShortTextQuestion" in _plain(result)
        assert "MultipleChoiceQuestion" in _plain(result)
        assert "RatingQuestion" in _plain(result)

    def test_schema_output_to_file(self, tmp_path: Path) -> None:
        """Schema --output saves the schema to a JSON file."""
        out_path = tmp_path / "schema.json"
        result = runner.invoke(app, ["schema", "--output", str(out_path)])
        assert result.exit_code == 0
        assert out_path.exists()
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "properties" in data

    def test_schema_help(self) -> None:
        """Schema command accepts --help."""
        result = runner.invoke(app, ["schema", "--help"])
        assert result.exit_code == 0
        assert "schema" in _plain(result)

    def test_schema_with_theme(self) -> None:
        """Schema --theme accepts a Pygments theme name."""
        result = runner.invoke(app, ["schema", "--theme", "ansi_light"])
        assert result.exit_code == 0
        assert '"$defs"' in _plain(result)

    def test_schema_help_shows_theme_option(self) -> None:
        """Schema --help mentions the --theme flag."""
        result = runner.invoke(app, ["schema", "--help"])
        assert result.exit_code == 0
        assert "--theme" in _plain(result)

    def test_serve_invalid_form_exits(self, tmp_path: Path) -> None:
        """Serve exits 1 for an invalid form."""
        path = _write_form(tmp_path / "bad.json", {"bad": "data"})
        with patch("formtuist.server.FormtuistServer") as mock_server_cls:
            result = runner.invoke(app, ["serve", str(path)])
            assert result.exit_code == 1
            mock_server_cls.assert_not_called()

    def test_display_with_database_name(self, tmp_path: Path) -> None:
        """Display --database-name resolves to a custom db file."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "T", "questions": []},
        )
        db_dir = tmp_path / "db_out"
        with patch("formtuist.tui.app.FormtuistApp") as mock_app_cls:
            mock_instance = mock_app_cls.return_value
            result = runner.invoke(
                app,
                [
                    "display",
                    str(form),
                    "--db-dir",
                    str(db_dir),
                    "--database-name",
                    "attendance.db",
                ],
            )
            assert result.exit_code == 0
            expected_db_path = db_dir / "attendance.db"
            mock_app_cls.assert_called_once_with(form, expected_db_path)
            mock_instance.run.assert_called_once()
