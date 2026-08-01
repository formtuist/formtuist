"""Widget factory for creating the appropriate input per question type."""

# ruff: noqa: PLR0911

from collections import defaultdict
from itertools import groupby
from typing import Any, ClassVar

from pygments.styles import ClassNotFound, get_style_by_name
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.validation import Integer, Regex
from textual.widget import Widget
from textual.widgets import (
    Footer,
    Input,
    RadioSet,
    SelectionList,
    Static,
    Switch,
    TextArea,
)
from textual.widgets._footer import FooterKey, FooterLabel, KeyGroup

from formtuitous.schema import (
    QUESTION_TYPE_CHECKBOX,
    QUESTION_TYPE_DATE,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_NUMERIC,
    QUESTION_TYPE_PARAGRAPH,
    QUESTION_TYPE_RATING,
    QUESTION_TYPE_SHORT_TEXT,
    QUESTION_TYPE_YES_NO,
    CheckboxQuestion,
    DateQuestion,
    MultipleChoiceQuestion,
    NumericQuestion,
    ParagraphQuestion,
    Question,
    RatingQuestion,
    ShortTextQuestion,
    YesNoQuestion,
)

# all question type identifiers accepted by the widget factory
KNOWN_QUESTION_TYPES: frozenset[str] = frozenset(
    {
        QUESTION_TYPE_SHORT_TEXT,
        QUESTION_TYPE_PARAGRAPH,
        QUESTION_TYPE_MULTIPLE_CHOICE,
        QUESTION_TYPE_CHECKBOX,
        QUESTION_TYPE_NUMERIC,
        QUESTION_TYPE_RATING,
        QUESTION_TYPE_DATE,
        QUESTION_TYPE_YES_NO,
    }
)

# regex pattern for ISO 8601 date (YYYY-MM-DD)
DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"

# sentinel value telling FormScreen to derive the syntax theme from the app
CODE_THEME_AUTO = "auto"

# Pygments fallback theme for dark Textual themes
CODE_THEME_FALLBACK_DARK = "ansi_dark"

# Pygments fallback theme for light Textual themes
CODE_THEME_FALLBACK_LIGHT = "ansi_light"

# map Textual theme names to the closest Pygments syntax-highlighting theme
TEXTUAL_TO_PYGMENTS_THEME: dict[str, str] = {
    "ansi-dark": "ansi_dark",
    "ansi-light": "ansi_light",
    "atom-one-dark": "github-dark",
    "atom-one-light": "default",
    "catppuccin-frappe": "nord",
    "catppuccin-latte": "default",
    "catppuccin-macchiato": "nord-darker",
    "catppuccin-mocha": "nord-darker",
    "dracula": "dracula",
    "flexoki": "monokai",
    "gruvbox": "gruvbox-dark",
    "monokai": "monokai",
    "nord": "nord",
    "rose-pine": "monokai",
    "rose-pine-dawn": "default",
    "rose-pine-moon": "monokai",
    "solarized-dark": "solarized-dark",
    "solarized-light": "solarized-light",
    "textual-dark": "ansi_dark",
    "textual-light": "ansi_light",
    "tokyo-night": "github-dark",
}


def resolve_code_theme(app: App) -> str:
    """Return a Pygments theme name matching the current Textual app theme."""
    textual_theme = app.theme
    if textual_theme in TEXTUAL_TO_PYGMENTS_THEME:
        return TEXTUAL_TO_PYGMENTS_THEME[textual_theme]
    try:
        get_style_by_name(textual_theme)
        return textual_theme
    except ClassNotFound:
        pass
    return (
        CODE_THEME_FALLBACK_DARK
        if app.current_theme.dark
        else CODE_THEME_FALLBACK_LIGHT
    )


def make_input_widget(question: Question) -> Widget:
    """Return the appropriate input widget for a question type."""
    if question.type not in KNOWN_QUESTION_TYPES:
        raise ValueError(f"Unknown question type: {question.type}")
    if isinstance(question, ShortTextQuestion):
        return Input(placeholder="Type your answer...")
    if isinstance(question, ParagraphQuestion):
        return TextArea()
    if isinstance(question, MultipleChoiceQuestion):
        return RadioSet(*question.choices)
    if isinstance(question, CheckboxQuestion):
        return SelectionList(*[(c, c, False) for c in question.choices])
    if isinstance(question, NumericQuestion):
        return Input(
            placeholder="Type a number...",
            validators=[Integer()],
        )
    if isinstance(question, RatingQuestion):
        return RadioSet(*question.labels)
    if isinstance(question, DateQuestion):
        return Input(
            placeholder="YYYY-MM-DD",
            validators=[Regex(DATE_PATTERN)],
        )
    if isinstance(question, YesNoQuestion):
        return Switch()
    raise ValueError(f"Unknown question type: {question.type}")


def make_code_widget(
    question: Question,
    theme: str = CODE_THEME_AUTO,
) -> Static | None:
    """Return a Static widget with syntax-highlighted code, or None.

    The *theme* is a Pygments theme name or CODE_THEME_AUTO to derive it
    from the app theme later. Defaults to CODE_THEME_AUTO.
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


class FormtuitousFooter(Footer):
    """Footer that groups form navigation bindings together.

    Textual renders footer keys in the order that bindings are registered.
    Because the Input widget binds ctrl+k internally (kill line), our
    priority binding for ctrl+k keeps the input's early position, which
    splits the navigation keys apart.  This footer re-sorts the bindings
    so that the navigation keys (ctrl+j / ctrl+k) are displayed together.
    """

    # sort priority for known form actions (lower is displayed first)
    _ACTION_ORDER: ClassVar[dict[str, int]] = {
        "focus_next": 0,
        "focus_previous": 1,
        "submit": 2,
        "focus_first_input": 3,
        "toggle_sidebar": 4,
    }

    def compose(self) -> ComposeResult:
        """Render the footer keys in a sensible order."""
        if not self._bindings_ready:
            return
        active_bindings = self.screen.active_bindings
        bindings = [
            (binding, enabled, tooltip)
            for (_, binding, enabled, tooltip) in active_bindings.values()
            if binding.show
        ]
        bindings.sort(
            key=lambda item: self._ACTION_ORDER.get(item[0].action, 100)
        )
        action_to_bindings: defaultdict[str, list[tuple[Binding, bool, str]]]
        action_to_bindings = defaultdict(list)
        for binding, enabled, tooltip in bindings:
            action_to_bindings[binding.action].append(
                (binding, enabled, tooltip)
            )

        self.styles.grid_size_columns = len(action_to_bindings)

        for group, multi_bindings_iterable in groupby(  # type: ignore[var-annotated]
            action_to_bindings.values(),
            lambda multi_bindings_: multi_bindings_[0][0].group,
        ):
            multi_bindings = list(multi_bindings_iterable)
            if group is not None and len(multi_bindings) > 1:
                with KeyGroup(classes="-compact" if group.compact else ""):
                    for binding_group in multi_bindings:
                        binding, enabled, tooltip = binding_group[0]
                        yield FooterKey(
                            binding.key,
                            self.app.get_key_display(binding),
                            "",
                            binding.action,
                            disabled=not enabled,
                            tooltip=tooltip or binding.description,
                            classes="-grouped",
                        ).data_bind(compact=Footer.compact)
                yield FooterLabel(group.description)
            else:
                for binding_group in multi_bindings:
                    binding, enabled, tooltip = binding_group[0]
                    yield FooterKey(
                        binding.key,
                        self.app.get_key_display(binding),
                        binding.description,
                        binding.action,
                        disabled=not enabled,
                        tooltip=tooltip,
                    ).data_bind(compact=Footer.compact)
        if self.show_command_palette and self.app.ENABLE_COMMAND_PALETTE:
            try:
                _node, binding, enabled, tooltip = active_bindings[
                    self.app.COMMAND_PALETTE_BINDING
                ]
            except KeyError:
                pass
            else:
                yield FooterKey(
                    binding.key,
                    self.app.get_key_display(binding),
                    binding.description,
                    binding.action,
                    classes="-command-palette",
                    disabled=not enabled,
                    tooltip=binding.tooltip or binding.description,
                )
