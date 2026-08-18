"""Tests for the JSON form parser and image path resolution."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from formtuist.parser import parse_form
from formtuist.schema import CODE_DIR_CONTEXT_KEY, CodeBlock

ALL_QUESTION_TYPES_COUNT = 8


def _write_form(tmp_path: Path, data: dict) -> Path:
    """Write a form dict as JSON to a temp file and return the path."""
    path = tmp_path / "form.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestParseFormBasic:
    """Tests for basic parse_form functionality."""

    def test_parse_valid_minimal(self, tmp_path: Path) -> None:
        """parse_form returns a FormDefinition for valid minimal JSON."""
        data = {
            "name": "Test",
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        assert form.name == "Test"
        assert len(form.questions) == 1

    def test_parse_valid_all_types(self, tmp_path: Path) -> None:
        """parse_form handles all 8 question types."""
        data = {
            "name": "All",
            "questions": [
                {"id": "s", "text": "S?", "type": "short_text"},
                {"id": "p", "text": "P?", "type": "paragraph"},
                {
                    "id": "m",
                    "text": "M?",
                    "type": "multiple_choice",
                    "choices": ["A", "B"],
                },
                {
                    "id": "c",
                    "text": "C?",
                    "type": "checkbox",
                    "choices": ["X", "Y"],
                },
                {"id": "n", "text": "N?", "type": "numeric"},
                {
                    "id": "r",
                    "text": "R?",
                    "type": "rating",
                    "min": 1,
                    "max": 3,
                    "labels": ["A", "B", "C"],
                },
                {"id": "d", "text": "D?", "type": "date"},
                {"id": "y", "text": "Y?", "type": "yes_no"},
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        assert len(form.questions) == ALL_QUESTION_TYPES_COUNT

    def test_parse_invalid_json_raises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """parse_form raises ValidationError for invalid form JSON."""
        data = {
            "name": "Bad",
            "questions": [
                {"id": "q", "text": "?", "type": "unknown_type"},
            ],
        }
        path = _write_form(tmp_path, data)
        with pytest.raises(ValidationError):
            parse_form(path)
        capsys.readouterr()

    def test_parse_missing_name_raises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """parse_form raises for JSON missing required name field."""
        data = {
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path, data)
        with pytest.raises(ValidationError):
            parse_form(path)
        capsys.readouterr()


class TestImagePathResolution:
    """Tests for relative image_path resolution."""

    def test_relative_path_resolved(self, tmp_path: Path) -> None:
        """A relative image_path is resolved against the form file's parent."""
        data = {
            "name": "With Image",
            "questions": [
                {
                    "id": "q",
                    "text": "See image?",
                    "type": "short_text",
                    "image_path": "./diagram.png",
                },
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        resolved = question.image_path
        assert resolved is not None
        expected = (tmp_path / "diagram.png").resolve()
        assert Path(resolved) == expected

    def test_absolute_path_unchanged(self, tmp_path: Path) -> None:
        """An already absolute image_path is not modified."""
        # /etc/hosts is not absolute on Windows, so anchor to the platform root
        absolute = str(Path(Path.cwd().anchor) / "etc" / "hosts")
        data = {
            "name": "Absolute",
            "questions": [
                {
                    "id": "q",
                    "text": "See?",
                    "type": "short_text",
                    "image_path": absolute,
                },
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        assert question.image_path == absolute

    def test_no_image_path_none(self, tmp_path: Path) -> None:
        """A question without image_path keeps it as None."""
        data = {
            "name": "No Image",
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        assert question.image_path is None


class TestCodeFileReferences:
    """Tests for loading code blocks from referenced files."""

    def test_code_file_loaded(self, tmp_path: Path) -> None:
        """A code block referencing a file loads its content."""
        answers = tmp_path / "answers"
        answers.mkdir()
        (answers / "snippet.py").write_text("x = 1\n", encoding="utf-8")
        data = {
            "name": "T",
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "code": {
                        "language": "python",
                        "file": "answers/snippet.py",
                    },
                },
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        assert question.code is not None
        assert question.code.content == "x = 1\n"

    def test_correct_answer_files_loaded(self, tmp_path: Path) -> None:
        """Answer segments referencing files load their content."""
        answers = tmp_path / "answers"
        answers.mkdir()
        (answers / "a.py").write_text("lambda x: x * x\n", encoding="utf-8")
        (answers / "b.py").write_text("lambda x: x ** 2\n", encoding="utf-8")
        data = {
            "name": "T",
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "correct_answer": [
                        {"language": "python", "file": "answers/a.py"},
                        {"language": "python", "file": "answers/b.py"},
                    ],
                },
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        answer = getattr(question, "correct_answer", None)
        assert isinstance(answer, list)
        contents = [(block.content or "").strip() for block in answer]
        assert contents == ["lambda x: x * x", "lambda x: x ** 2"]

    def test_code_dir_override(self, tmp_path: Path) -> None:
        """parse_form resolves file references against code_dir."""
        shared = tmp_path / "shared"
        shared.mkdir()
        (shared / "snippet.py").write_text("y = 2\n", encoding="utf-8")
        data = {
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
        path = _write_form(tmp_path, data)
        form = parse_form(path, code_dir=shared)
        question = form.questions[0]
        assert question.code is not None
        assert question.code.content == "y = 2\n"

    def test_absolute_code_file(self, tmp_path: Path) -> None:
        """An absolute file reference loads regardless of code_dir."""
        snippet = tmp_path / "snippet.py"
        snippet.write_text("z = 3\n", encoding="utf-8")
        data = {
            "name": "T",
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "code": {
                        "language": "python",
                        "file": str(snippet),
                    },
                },
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        assert question.code is not None
        assert question.code.content == "z = 3\n"

    def test_missing_code_file_raises(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A missing code file raises ValidationError."""
        data = {
            "name": "T",
            "questions": [
                {
                    "id": "q",
                    "text": "Q?",
                    "type": "short_text",
                    "code": {"language": "python", "file": "missing.py"},
                },
            ],
        }
        path = _write_form(tmp_path, data)
        with pytest.raises(ValidationError):
            parse_form(path)
        capsys.readouterr()

    def test_context_loading_direct_validation(self, tmp_path: Path) -> None:
        """A code block resolves through the pydantic context directly."""
        snippet = tmp_path / "snippet.py"
        snippet.write_text("x = 1\n", encoding="utf-8")
        block = CodeBlock.model_validate(
            {"language": "python", "file": "snippet.py"},
            context={CODE_DIR_CONTEXT_KEY: tmp_path},
        )
        assert block.content == "x = 1\n"
