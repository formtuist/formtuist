"""Screen definitions for the formtuitous TUI workflow."""

import asyncio
from pathlib import Path
from typing import Any, ClassVar

from textual._context import NoActiveAppError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Header, Input, Label, Static

from formtuitous.auth import GitHubIdentity, fetch_github_identity
from formtuitous.database import init_db, save_response
from formtuitous.schema import FormDefinition
from formtuitous.tui.widgets import (
    CODE_THEME_AUTO,
    FormtuitousFooter,
    get_widget_value,
    is_widget_empty,
    is_widget_valid,
    make_code_widget,
    make_input_widget,
    resolve_code_theme,
)

# maximum characters for a sidebar question title before truncation
SIDEBAR_TITLE_MAX = 25


class WelcomeScreen(Screen):
    """Display the form name, description, and a Start button."""

    def __init__(self, form: FormDefinition, db_path: Path) -> None:
        """Store the form definition and database path."""
        self.form = form
        self.db_path = db_path
        super().__init__()

    def compose(self) -> ComposeResult:
        """Render the welcome screen with form info and a start button."""
        yield Header(show_clock=True)
        yield Static(f"[bold]{self.form.name}[/bold]", id="form-title")
        if self.form.description:
            yield Static(self.form.description, id="form-desc")
        yield Static(f"Questions: {len(self.form.questions)}", id="form-count")
        yield Button("Start", id="start", variant="primary")
        yield FormtuitousFooter()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Transition to the form screen on start."""
        if event.button.id == "start":
            self.app.push_screen(FormScreen(self.form, self.db_path))


class FormScreen(Screen):
    """Scrolling form with input widgets for each question."""

    BINDINGS: ClassVar[  # type: ignore[assignment]
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        ("ctrl+s", "submit", "Submit"),
        ("ctrl+f", "focus_first_input", "Focus Input"),
        ("ctrl+b", "toggle_sidebar", "Sidebar"),
        Binding("ctrl+j", "focus_next", "Next Q", priority=True),
        Binding("ctrl+k", "focus_previous", "Prev Q", priority=True),
    ]

    def __init__(
        self,
        form: FormDefinition,
        db_path: Path,
        code_theme: str = CODE_THEME_AUTO,
    ) -> None:
        """Store the form definition, database path, and initialise input map."""
        self.form = form
        self.db_path = db_path
        self.code_theme = code_theme
        self.inputs: dict[str, Widget] = {}
        self.code_widgets: dict[str, Static] = {}
        self.sidebar_items: list[Static] = []
        self.current_index = 0
        self.auth_input: Input | None = None
        super().__init__()

    def compose(self) -> ComposeResult:
        """Render the sidebar, scrolling form, and footer."""
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("[bold]Questions[/bold]", id="sidebar-title")
                for question in self.form.questions:
                    truncated = self._truncate(question.text)
                    item = Static(truncated, classes="sidebar-item")
                    self.sidebar_items.append(item)
                    yield item
            with VerticalScroll(id="question-scroll"):
                yield Static(
                    f"[bold]{self.form.name}[/bold]", id="form-header"
                )
                if self.form.config.auth == "github":
                    yield Label(
                        "GitHub token (run gh auth token to get one):",
                        id="auth-label",
                    )
                    auth_input = Input(
                        placeholder="Paste your GitHub token...",
                        password=True,
                    )
                    auth_input.id = "auth-input"
                    self.auth_input = auth_input
                    yield auth_input
                for question in self.form.questions:
                    required = " *" if question.required else ""
                    yield Label(f"{question.text}{required}")
                    code_widget = make_code_widget(question, self.code_theme)
                    if code_widget is not None:
                        self.code_widgets[question.id] = code_widget
                        yield code_widget
                    # optional url
                    if question.url is not None:
                        yield Static(f"URL: {question.url}")
                    # input widget appropriate for the question type
                    input_widget = make_input_widget(question)
                    input_widget.id = f"input-{question.id}"
                    self.inputs[question.id] = input_widget
                    yield input_widget
                yield Static(id="question-counter")
                yield Button("Submit", id="submit", variant="primary")
        yield FormtuitousFooter()

    def on_mount(self) -> None:
        """Focus the first input and hide scrollbars after mounting."""
        self.action_focus_first_input()
        self._hide_scrollbars()
        self._sync_code_theme()
        try:
            app = self.app
        except NoActiveAppError:
            return
        if self.code_theme == CODE_THEME_AUTO:
            self.watch(app, "theme", self._on_app_theme_change)

    def _sync_code_theme(self) -> None:
        """Resolve and apply the current app theme to all code widgets."""
        if self.code_theme != CODE_THEME_AUTO:
            return
        try:
            app = self.app
        except NoActiveAppError:
            return
        self._update_code_widgets(resolve_code_theme(app))

    def _on_app_theme_change(self, _old_theme: str, _new_theme: str) -> None:
        """Refresh code highlighting when the app theme changes."""
        self._sync_code_theme()

    def _update_code_widgets(self, theme_name: str) -> None:
        """Recreate the Syntax renderables for all code widgets."""
        for question in self.form.questions:
            if question.code is None:
                continue
            widget = self.code_widgets.get(question.id)
            if widget is None:
                continue
            from rich.syntax import Syntax  # noqa: PLC0415

            widget.update(
                Syntax(
                    question.code.content,
                    question.code.language,
                    theme=theme_name,
                    line_numbers=True,
                )
            )

    def _hide_scrollbars(self) -> None:
        """Set scrollbar size to zero on scrollable containers.

        Only works when the widget tree is mounted (i.e. during live TUI
        use), so failures are silently caught.
        """
        try:
            question_scroll = self.query_one("#question-scroll")
            question_scroll.styles.scrollbar_size_horizontal = 0
            question_scroll.styles.scrollbar_size_vertical = 0
            sidebar = self.query_one("#sidebar")
            sidebar.styles.scrollbar_size_horizontal = 0
            sidebar.styles.scrollbar_size_vertical = 0
        except Exception:
            pass

    def watch_focused(
        self, old_val: Widget | None, new_val: Widget | None
    ) -> None:
        """Update the sidebar highlight and counter when focus changes.

        Textual calls this automatically whenever the focused widget
        changes -- no polling needed.
        """
        if new_val is None or new_val.id is None:
            return
        for i, question in enumerate(self.form.questions):
            if new_val.id == f"input-{question.id}":
                self.current_index = i
                self._update_sidebar_and_counter()
                return

    def _truncate(self, text: str) -> str:
        """Shorten a question title to fit the sidebar."""
        if len(text) > SIDEBAR_TITLE_MAX:
            return text[: SIDEBAR_TITLE_MAX - 3] + "..."
        return text

    def _update_sidebar_and_counter(self) -> None:
        """Refresh the sidebar highlight and the question counter label."""
        counter = self.query_one("#question-counter", Static)
        counter.update(
            f"Question {self.current_index + 1} / {len(self.form.questions)}"
        )
        for i, item in enumerate(self.sidebar_items):
            item.set_class(i == self.current_index, "current")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Validate required fields and submit."""
        if event.button.id == "submit":
            await self.action_submit()

    async def action_submit(self) -> None:
        """Collect answers, validate auth, save to DB, show confirmation."""
        answers: dict[str, Any] = {}
        valid = True
        identity: GitHubIdentity | None = None
        if self.form.config.auth == "github":
            if self.auth_input is None:
                self.notify(
                    "Authentication is required but no token field exists.",
                    severity="error",
                )
                return
            token = self.auth_input.value.strip()
            if not token:
                self.notify(
                    "Please enter your GitHub token.", severity="error"
                )
                return
            identity = await asyncio.to_thread(fetch_github_identity, token)
            if identity is None:
                self.notify(
                    "Invalid GitHub token. Please try again.",
                    severity="error",
                )
                return
        for question in self.form.questions:
            widget = self.inputs[question.id]
            value = get_widget_value(widget)
            if question.required and is_widget_empty(widget):
                self.notify(
                    f"Please answer question: {question.text}",
                    severity="error",
                )
                valid = False
            elif not is_widget_empty(widget) and not is_widget_valid(widget):
                self.notify(
                    f"Invalid value for: {question.text}",
                    severity="error",
                )
                valid = False
            answers[question.id] = value
        if not valid:
            return
        conn = init_db(self.db_path)
        save_response(
            conn,
            self.form.name,
            answers,
            identity.username if identity is not None else None,
            identity.profile_url if identity is not None else None,
        )
        conn.close()
        self.app.push_screen(SubmitScreen(self.form, self.db_path, identity))

    def action_focus_first_input(self) -> None:
        """Focus the auth token field or the first question input."""
        if self.auth_input is not None:
            self.set_focus(self.auth_input)
            return
        for question in self.form.questions:
            input_widget = self.inputs.get(question.id)
            if input_widget is not None:
                self.set_focus(input_widget)
                return

    def action_focus_next(self) -> None:
        """Focus the next question input, wrapping around at the end."""
        next_index = (self.current_index + 1) % len(self.form.questions)
        question = self.form.questions[next_index]
        input_widget = self.inputs.get(question.id)
        if input_widget is not None:
            self.set_focus(input_widget)

    def action_focus_previous(self) -> None:
        """Focus the previous question input, wrapping around at the start."""
        prev_index = (self.current_index - 1) % len(self.form.questions)
        question = self.form.questions[prev_index]
        input_widget = self.inputs.get(question.id)
        if input_widget is not None:
            self.set_focus(input_widget)

    def action_toggle_sidebar(self) -> None:
        """Show or hide the sidebar."""
        sidebar = self.query_one("#sidebar")
        sidebar.toggle_class("hidden")


class SubmitScreen(Screen):
    """Confirmation screen shown after a successful submission."""

    BINDINGS: ClassVar[  # type: ignore[assignment]
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+r", "restart", "Restart"),
    ]

    def __init__(
        self,
        form: FormDefinition,
        db_path: Path,
        identity: GitHubIdentity | None = None,
    ) -> None:
        """Store the form definition, database path, and optional identity."""
        self.form = form
        self.db_path = db_path
        self.identity = identity
        super().__init__()

    def compose(self) -> ComposeResult:
        """Render the confirmation message with actions."""
        yield Header(show_clock=True)
        yield Static("[bold]Response saved![/bold]", id="confirm-title")
        yield Static("Your answers have been recorded.", id="confirm-msg")
        if self.identity is not None:
            yield Static(
                f"Authenticated as [bold]{self.identity.username}[/bold]"
                f" ({self.identity.profile_url})",
                id="confirm-identity",
            )
        yield Static(
            f"Results saved to: [italic]{self.db_path}[/italic]",
            id="confirm-db-path",
        )
        yield Static(
            "[dim]Tip: Press Ctrl+P for the command palette.[/dim]",
            id="confirm-tip",
        )
        yield Button("Restart", id="restart", variant="primary")
        yield Button("Quit", id="quit", variant="default")
        yield FormtuitousFooter()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle restart or quit."""
        if event.button.id == "restart":
            self.action_restart()
        elif event.button.id == "quit":
            self.app.exit()

    def action_restart(self) -> None:
        """Push a new form screen to fill out the form again."""
        self.app.push_screen(FormScreen(self.form, self.db_path))
