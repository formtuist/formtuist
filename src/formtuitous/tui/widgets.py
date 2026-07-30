"""Widget factory for creating the appropriate input per question type."""

# ruff: noqa: PLR0911

from typing import Any

from rich.syntax import Syntax
from textual.validation import Integer, Regex
from textual.widget import Widget
from textual.widgets import (
    Input,
    RadioSet,
    SelectionList,
    Static,
    Switch,
    TextArea,
)

from formtuitous.schema import Question

# regex pattern for ISO 8601 date (YYYY-MM-DD)
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def make_input_widget(question: Question) -> Widget:
    """Return the appropriate input widget for a question type."""
    if question.type == "short_text":
        return Input(placeholder="Type your answer...")
    if question.type == "paragraph":
        return TextArea()
    if question.type == "multiple_choice":
        return RadioSet(*question.choices)
    if question.type == "checkbox":
        return SelectionList(*[(c, c, False) for c in question.choices])
    if question.type == "numeric":
        return Input(
            placeholder="Type a number...",
            validators=[Integer()],
        )
    if question.type == "rating":
        return RadioSet(*question.labels)
    if question.type == "date":
        return Input(
            placeholder="YYYY-MM-DD",
            validators=[Regex(DATE_PATTERN)],
        )
    if question.type == "yes_no":
        return Switch()
    raise ValueError(f"Unknown question type: {question.type}")


def make_code_widget(
    question: Question,
    theme: str = "ansi-dark",
) -> Static | None:
    """Return a Static widget with syntax-highlighted code, or None.

    The *theme* is a Pygments theme name.  Defaults to ``"ansi-dark"``.
    """
    if question.code is None:
        return None
    syntax = Syntax(
        question.code.content,
        question.code.language,
        theme=theme,
        line_numbers=True,
    )
    return Static(syntax)


def get_widget_value(widget: Widget) -> Any:
    """Extract the answer value from a question widget."""
    if isinstance(widget, Input):
        return widget.value
    if isinstance(widget, TextArea):
        return widget.text
    if isinstance(widget, RadioSet):
        if widget.pressed_button is not None:
            return str(widget.pressed_button.label)
        return None
    if isinstance(widget, SelectionList):
        return [str(v) for v in widget.selected]
    if isinstance(widget, Switch):
        return widget.value
    return None


def is_widget_empty(widget: Widget) -> bool:
    """Check whether a question widget has an empty value."""
    if isinstance(widget, Input):
        return not widget.value.strip()
    if isinstance(widget, TextArea):
        return not widget.text.strip()
    if isinstance(widget, RadioSet):
        return widget.pressed_button is None
    if isinstance(widget, SelectionList):
        return len(widget.selected) == 0
    if isinstance(widget, Switch):
        return False
    return True


def is_widget_valid(widget: Widget) -> bool:
    """Check whether an Input widget passes its validators."""
    if isinstance(widget, Input):
        return widget.is_valid
    return True
