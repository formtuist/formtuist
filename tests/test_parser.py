"""Tests for the JSON form parser and image path resolution."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from formtuitous.parser import parse_form

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
        data = {
            "name": "Absolute",
            "questions": [
                {
                    "id": "q",
                    "text": "See?",
                    "type": "short_text",
                    "image_path": "/etc/hosts",
                },
            ],
        }
        path = _write_form(tmp_path, data)
        form = parse_form(path)
        question = form.questions[0]
        assert question.image_path == "/etc/hosts"

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
