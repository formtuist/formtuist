"""JSON validation and parsing for form definition files."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from rich.console import Console
from rich.rule import Rule

from formtuitous.schema import FormDefinition

# rich console directed to stderr so error reports stay separate from regular output
console = Console(stderr=True)
INDENT = "  "


def _format_error_path(loc: tuple[Any, ...]) -> str:
    """Format a Pydantic error location tuple into a readable path string."""
    parts: list[str] = []
    for segment in loc:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        elif isinstance(segment, str):
            if parts:
                parts.append(f".{segment}")
            else:
                parts.append(segment)
        else:
            parts.append(str(segment))
    return "".join(parts)


def _pretty_print_errors(err: ValidationError) -> None:
    """Print a formatted error report to stderr with JSON path references."""
    console.print(Rule(style="dim"))
    console.print("[bold]Form definition contains errors:[/bold]")
    for error in err.errors():
        # each error carries a location tuple, a human-readable message, and a type code
        path = _format_error_path(error["loc"])
        message = error["msg"]
        error_type = error.get("type", "unknown")
        console.print(f"{INDENT}at {path}: {message} (type={error_type})")
    console.print(Rule(style="dim"))


def _resolve_image_paths(definition: FormDefinition, form_dir: Path) -> None:
    """Resolve relative image_path values to absolute paths in-place."""
    for question in definition.questions:
        image_path = getattr(question, "image_path", None)
        if image_path is not None:
            # convert a relative path to absolute against the form file's parent directory
            candidate = Path(image_path)
            if not candidate.is_absolute():
                candidate = (form_dir / candidate).resolve()
                question.image_path = str(candidate)


def parse_form(path: Path) -> FormDefinition:
    """Load, validate, and return a FormDefinition from a JSON file.

    Args:
        path: Path to the JSON form definition file.

    Returns:
        A validated FormDefinition instance.

    Raises:
        ValidationError: If the JSON content is invalid.

    """
    raw = path.read_text(encoding="utf-8")
    try:
        definition = FormDefinition.model_validate_json(raw)
    except ValidationError as err:
        _pretty_print_errors(err)
        raise
    _resolve_image_paths(definition, path.parent)
    return definition
