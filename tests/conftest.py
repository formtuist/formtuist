"""Shared fixtures and configuration for the test suite."""

import json
from pathlib import Path

import pytest

from formtuist.schema import FormDefinition, ShortTextQuestion


@pytest.fixture()
def minimal_form() -> FormDefinition:
    """Return a FormDefinition with one short_text question."""
    return FormDefinition(
        name="Minimal",
        description="A minimal form for testing.",
        questions=[
            ShortTextQuestion(
                id="q1",
                text="What is your name?",
                required=True,
                type="short_text",
            ),
        ],
    )


@pytest.fixture()
def minimal_form_path(tmp_path: Path) -> Path:
    """Write a minimal form JSON to a temp file and return the path."""
    data = {
        "name": "Minimal",
        "description": "A minimal form for testing.",
        "questions": [
            {
                "id": "q1",
                "text": "What is your name?",
                "type": "short_text",
                "required": True,
            }
        ],
    }
    path = tmp_path / "minimal.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path
