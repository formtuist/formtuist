"""Tests for the formtuitous CLI commands."""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner, Result

from formtuitous.cli import app, main

# regex to strip ANSI SGR escape sequences that Rich embeds in captured output
ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")


runner = CliRunner()


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
    """Tests for the `formtuitous check` subcommand."""

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
        """Serve command executes its stub body."""
        form = _write_form(
            tmp_path / "form.json", {"name": "T", "questions": []}
        )
        result = runner.invoke(app, ["serve", str(form)])
        assert result.exit_code == 0

    def test_export_with_file(self, tmp_path: Path) -> None:
        """Export command executes its stub body."""
        db = _write_form(tmp_path / "resp.db", {"dummy": True})
        result = runner.invoke(app, ["export", str(db)])
        assert result.exit_code == 0

    def test_view_with_file(self, tmp_path: Path) -> None:
        """View command executes its stub body."""
        db = _write_form(tmp_path / "resp.db", {"dummy": True})
        result = runner.invoke(app, ["view", str(db)])
        assert result.exit_code == 0

    def test_grade_with_files(self, tmp_path: Path) -> None:
        """Grade command executes its stub body."""
        form = _write_form(
            tmp_path / "form.json", {"name": "T", "questions": []}
        )
        db = _write_form(tmp_path / "resp.db", {"dummy": True})
        result = runner.invoke(app, ["grade", str(form), str(db)])
        assert result.exit_code == 0


class TestExampleFormsCLI:
    """Integration tests: formtuitous check against all example files."""

    EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

    @pytest.mark.parametrize(
        "filename",
        [
            "all_types.json",
            "anonymous_poll.json",
            "attendance.json",
            "minimal.json",
            "quiz.json",
            "survey.json",
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
        """Running formtuitous --help shows usage."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "formtuitous" in _plain(result)

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
        assert "View responses" in _plain(result)

    def test_grade_help(self) -> None:
        """Grade command accepts --help."""
        result = runner.invoke(app, ["grade", "--help"])
        assert result.exit_code == 0
        assert "Grade responses" in _plain(result)


class TestDisplayCommand:
    """Tests for the display command body using mocking."""

    def test_display_valid_form_mocks_run(self, tmp_path: Path) -> None:
        """Display validates form and calls FormtuitousApp.run."""
        form = _write_form(
            tmp_path / "form.json",
            {"name": "T", "description": "d", "questions": []},
        )
        with patch("formtuitous.tui.app.FormtuitousApp") as mock_app_cls:
            mock_instance = mock_app_cls.return_value
            result = runner.invoke(app, ["display", str(form)])
            assert result.exit_code == 0
            mock_app_cls.assert_called_once_with(form, Path("responses.db"))
            mock_instance.run.assert_called_once()

    def test_display_invalid_form_exits(self, tmp_path: Path) -> None:
        """Display exits 1 for an invalid form."""
        path = _write_form(tmp_path / "bad.json", {"bad": "data"})
        with patch("formtuitous.tui.app.FormtuitousApp") as mock_app_cls:
            result = runner.invoke(app, ["display", str(path)])
            assert result.exit_code == 1
            mock_app_cls.assert_not_called()

    def test_main_calls_app(self) -> None:
        """main() invokes the typer app."""
        with patch("formtuitous.cli.app") as mock_app:
            main()
            mock_app.assert_called_once()
