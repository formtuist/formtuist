"""Widget factory for creating the appropriate input per question type."""

# ruff: noqa: PLR0911

from typing import Any

from textual.validation import Integer
from textual.widget import Widget
from textual.widgets import Input, RadioSet, SelectionList, Switch, TextArea

from formtuitous.schema import Question


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
        return Input(placeholder="Type a number...", validators=[Integer()])
    if question.type == "rating":
        return RadioSet(*question.labels)
    if question.type == "date":
        return Input(placeholder="YYYY-MM-DD")
    if question.type == "yes_no":
        return Switch()
    raise ValueError(f"Unknown question type: {question.type}")


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
