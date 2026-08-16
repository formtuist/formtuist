"""JSON validation and parsing for form definition files."""

from pathlib import Path
from typing import Any

from pydantic import ValidationError
from rich.console import Console
from rich.rule import Rule

from formtuist.schema import CODE_DIR_CONTEXT_KEY, FormDefinition

# rich console directed to stderr so error reports stay separate from regular output
console = Console(stderr=True)
INDENT = "  "
RULE_STYLE = "dim"
ERROR_HEADER = "[bold]Form definition contains errors:[/bold]"
ERROR_LINE_PREFIX = "at "
ERROR_LINE_SUFFIX = " (type="
ERROR_LINE_CLOSE = ")"
ERROR_TYPE_DEFAULT = "unknown"
ENCODING = "utf-8"


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
    console.print(Rule(style=RULE_STYLE))
    console.print(ERROR_HEADER)
    for error in err.errors():
        # each error carries a location tuple, a human-readable message, and a type code
        path = _format_error_path(error["loc"])
        message = error["msg"]
        error_type = error.get("type", ERROR_TYPE_DEFAULT)
        console.print(
            f"{INDENT}{ERROR_LINE_PREFIX}{path}: {message}"
            f"{ERROR_LINE_SUFFIX}{error_type}{ERROR_LINE_CLOSE}"
        )
    console.print(Rule(style=RULE_STYLE))


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


def parse_form(
    path: Path,
    code_dir: Path | None = None,
) -> FormDefinition:
    """Load, validate, and return a FormDefinition from a JSON file.

    Args:
        path: Path to the JSON form definition file.
        code_dir: Directory that code file references are relative to.
            Defaults to the form file's own directory when not given.

    Returns:
        A validated FormDefinition instance.

    Raises:
        ValidationError: If the JSON content is invalid.

    """
    raw = path.read_text(encoding=ENCODING)
    base_dir = code_dir if code_dir is not None else path.parent
    try:
        definition = FormDefinition.model_validate_json(
            raw, context={CODE_DIR_CONTEXT_KEY: base_dir}
        )
    except ValidationError as err:
        _pretty_print_errors(err)
        raise
    _resolve_image_paths(definition, path.parent)
    return definition
