"""Screen definitions for the formtuist TUI workflow."""

import asyncio
import random
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, cast

from rich.syntax import Syntax
from textual._context import NoActiveAppError
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Header, Input, Label, Static

from formtuist.auth import GitHubIdentity, fetch_github_identity
from formtuist.database import (
    FORM_CONTENTS_COLUMN,
    FORM_HASH_COLUMN,
    FORM_PATH_COLUMN,
    FORM_VERSION_COLUMN,
    ensure_single_submission_index,
    has_submission,
    init_db,
    save_response,
)
from formtuist.grader import (
    BREAKDOWN_ANSWER_KEY,
    BREAKDOWN_CORRECT_ANSWER_KEY,
    BREAKDOWN_CORRECT_KEY,
    BREAKDOWN_KEY,
    BREAKDOWN_LANGUAGE_KEY,
    BREAKDOWN_TEXT_KEY,
    MAX_KEY,
    PERCENTAGE_KEY,
    TOTAL_KEY,
    grade_report_to_json,
    grade_response,
    has_gradeable_questions,
)
from formtuist.schema import (
    AuthProvider,
    CodeBlock,
    FormDefinition,
    NumericRange,
    Question,
)

if TYPE_CHECKING:
    from formtuist.tui.app import FormtuistApp
from formtuist.tui.widgets import (
    CODE_THEME_AUTO,
    CODE_THEME_FALLBACK_DARK,
    FormtuistFooter,
    get_widget_value,
    is_widget_empty,
    is_widget_valid,
    make_code_widget,
    make_input_widget,
    resolve_code_theme,
)

# maximum characters for a sidebar question title before truncation
SIDEBAR_TITLE_MAX = 25

NEWLINE = "\n"

# labels for the post-submission grade review
GRADE_SCORE_PREFIX = "Score: "
GRADE_PERCENT_SUFFIX = "%"
GRADE_REVIEW_TITLE = "Incorrect answers"
GRADE_ALL_CORRECT = "All answers correct!"
GRADE_NO_GRADED = "This form has no auto-graded questions."
GRADE_YOUR_ANSWER = "Your answer: "
GRADE_CORRECT_ANSWER = "Correct answer: "
GRADE_CORRECT_ANSWERS = "Correct answers: "
GRADE_NO_ANSWER = "(no answer)"
GRADE_LIST_SEPARATOR = ", "
GRADE_RANGE_BETWEEN = "between "
GRADE_RANGE_AND = " and "

# css class used to style the submit screen's own scrollbars
SUBMIT_SCREEN_CLASS = "submit-screen"

# messages for the enforced single-submission flow
ALREADY_SUBMITTED_MESSAGE = (
    "You have already submitted this form. Each person may submit once."
)
SINGLE_SUBMISSION_NOTE = "This form accepts a single submission."


# default seed for the pseudo-random number generator used when shuffling
DEFAULT_SEED = None


def shuffle_questions(
    questions: Sequence[Question],
    seed: int | None = DEFAULT_SEED,
) -> list[Question]:
    """Return a copy with pinned questions kept at their file positions."""
    movable = [question for question in questions if question.randomize]
    random.Random(seed).shuffle(movable)
    movable_iter = iter(movable)
    return [
        question if not question.randomize else next(movable_iter)
        for question in questions
    ]


def _format_answer(value: Any) -> str:
    """Render an answer value for display in the grade review."""
    if value is None:
        return GRADE_NO_ANSWER
    if isinstance(value, CodeBlock):
        return value.content or ""
    if isinstance(value, NumericRange):
        return (
            f"{GRADE_RANGE_BETWEEN}{value.min:g}{GRADE_RANGE_AND}{value.max:g}"
        )
    if isinstance(value, list):
        return GRADE_LIST_SEPARATOR.join(str(item) for item in value)
    return str(value)


def _code_static(block: CodeBlock, theme: str) -> Static:
    """Return a syntax-highlighted Static for a code block."""
    syntax = Syntax(
        (block.content or "").rstrip(),
        block.language,
        theme=theme,
        line_numbers=True,
    )
    return Static(syntax)


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
        yield FormtuistFooter()

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
        Binding("ctrl+n", "focus_next", "Next Q", priority=True),
        Binding("ctrl+p", "focus_previous", "Prev Q", priority=True),
    ]

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        form: FormDefinition,
        db_path: Path,
        code_theme: str = CODE_THEME_AUTO,
        seed: int | None = DEFAULT_SEED,
        form_version: str | None = None,
        form_hash: str | None = None,
        form_source_path: Path | None = None,
        form_contents: str | None = None,
    ) -> None:
        """Store the form definition, database path, and initialise input map."""
        self.form = form
        self.db_path = db_path
        self.code_theme = code_theme
        self.form_version = form_version
        self.form_hash = form_hash
        self.form_source_path = form_source_path
        self.form_contents = form_contents
        self.inputs: dict[str, Widget] = {}
        self.code_widgets: dict[str, Static] = {}
        self.sidebar_items: list[Static] = []
        self.current_index = 0
        self.auth_input: Input | None = None
        if form.config.randomize_questions:
            self.ordered_questions = shuffle_questions(form.questions, seed)
        else:
            self.ordered_questions = list(form.questions)
        super().__init__()

    def _form_provenance(self) -> dict[str, str | None]:
        """Return provenance fields when the source form is available."""
        if self.form_source_path is None:
            return {}
        return {
            FORM_VERSION_COLUMN: self.form_version,
            FORM_HASH_COLUMN: self.form_hash,
            FORM_PATH_COLUMN: str(self.form_source_path),
            FORM_CONTENTS_COLUMN: self.form_contents,
        }

    def compose(self) -> ComposeResult:
        """Render the sidebar, scrolling form, and footer."""
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("[bold]Questions[/bold]", id="sidebar-title")
                for question in self.ordered_questions:
                    truncated = self._truncate(question.text)
                    item = Static(truncated, classes="sidebar-item")
                    self.sidebar_items.append(item)
                    yield item
            with VerticalScroll(id="question-scroll"):
                yield Static(
                    f"[bold]{self.form.name}[/bold]", id="form-header"
                )
                if self.form.config.auth == AuthProvider.GITHUB:
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
                for question in self.ordered_questions:
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
        yield FormtuistFooter()

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
        for question in self.ordered_questions:
            if question.code is None:
                continue
            widget = self.code_widgets.get(question.id)
            if widget is None:
                continue
            from rich.syntax import Syntax  # noqa: PLC0415

            widget.update(
                Syntax(
                    (question.code.content or "").rstrip(),
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
        for i, question in enumerate(self.ordered_questions):
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
            f"Question {self.current_index + 1} / {len(self.ordered_questions)}"
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
        if self.form.config.auth == AuthProvider.GITHUB:
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
        for question in self.ordered_questions:
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
        grade_report = None
        grade_json = None
        if has_gradeable_questions(self.form):
            grade_report = grade_response(self.form, answers)
            grade_json = grade_report_to_json(grade_report)
        conn = init_db(self.db_path)
        attempt_id = cast("FormtuistApp", self.app).attempt_id
        if not self.form.config.allow_multiple_submissions:
            ensure_single_submission_index(conn, self.form.name, attempt_id)
            if identity is not None and has_submission(
                conn, self.form.name, attempt_id, identity.username
            ):
                conn.close()
                self.notify(ALREADY_SUBMITTED_MESSAGE, severity="error")
                return
        try:
            save_response(
                conn,
                self.form.name,
                answers,
                identity.username if identity is not None else None,
                identity.profile_url if identity is not None else None,
                grade=grade_json,
                attempt_id=attempt_id,
                **self._form_provenance(),
            )
        except sqlite3.IntegrityError:
            conn.close()
            self.notify(ALREADY_SUBMITTED_MESSAGE, severity="error")
            return
        conn.close()
        submit_report = grade_report if self.form.config.auto_grade else None
        self.app.push_screen(
            SubmitScreen(self.form, self.db_path, identity, submit_report)
        )

    def action_focus_first_input(self) -> None:
        """Focus the auth token field or the first question input."""
        if self.auth_input is not None:
            self.set_focus(self.auth_input)
            return
        for question in self.ordered_questions:
            input_widget = self.inputs.get(question.id)
            if input_widget is not None:
                self.set_focus(input_widget)
                return

    def action_focus_next(self) -> None:
        """Focus the next question input, wrapping around at the end."""
        next_index = (self.current_index + 1) % len(self.ordered_questions)
        question = self.ordered_questions[next_index]
        input_widget = self.inputs.get(question.id)
        if input_widget is not None:
            self.set_focus(input_widget)

    def action_focus_previous(self) -> None:
        """Focus the previous question input, wrapping around at the start."""
        prev_index = (self.current_index - 1) % len(self.ordered_questions)
        question = self.ordered_questions[prev_index]
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
        grade_report: dict[str, Any] | None = None,
    ) -> None:
        """Store the form, database path, identity, and grade report."""
        self.form = form
        self.db_path = db_path
        self.identity = identity
        self.grade_report = grade_report
        super().__init__()
        self.add_class(SUBMIT_SCREEN_CLASS)

    def compose(self) -> ComposeResult:
        """Render the confirmation message with actions."""
        yield Header(show_clock=True)
        yield Static("[bold]Response saved![/bold]", id="confirm-title")
        yield Static(
            f"{NEWLINE}Results saved to: [italic]{self.db_path}[/italic]",
            id="confirm-db-path",
        )
        if self.identity is not None:
            yield Static(
                f"Authenticated as [bold]{self.identity.username}[/bold]"
                f" ({self.identity.profile_url})",
                id="confirm-identity",
            )
        if self.grade_report is not None:
            yield from self._compose_grade_review()
        yield Static(
            "[dim]Tip: Press Ctrl+O for the command palette.[/dim]",
            id="confirm-tip",
        )
        if self.form.config.allow_multiple_submissions:
            yield Button("Restart", id="restart", variant="primary")
        else:
            yield Static(SINGLE_SUBMISSION_NOTE, id="confirm-single")
        yield Button("Quit", id="quit", variant="default")
        yield FormtuistFooter()

    def _compose_grade_review(self) -> ComposeResult:
        """Yield the score summary and the incorrect-answer review."""
        assert self.grade_report is not None
        total = self.grade_report[TOTAL_KEY]
        max_total = self.grade_report[MAX_KEY]
        percentage = self.grade_report[PERCENTAGE_KEY]
        breakdown = self.grade_report[BREAKDOWN_KEY]
        yield Static(
            f"{GRADE_SCORE_PREFIX}{total} / {max_total}"
            f" ({percentage:g}{GRADE_PERCENT_SUFFIX})",
            id="grade-score",
        )
        incorrect = [
            entry for entry in breakdown if not entry[BREAKDOWN_CORRECT_KEY]
        ]
        theme = self._code_theme()
        with VerticalScroll(id="grade-review"):
            if not breakdown:
                yield Static(GRADE_NO_GRADED)
            elif not incorrect:
                yield Static(GRADE_ALL_CORRECT)
            else:
                yield Static(f"[bold]{GRADE_REVIEW_TITLE}[/bold]")
                for entry in incorrect:
                    yield Static(f"[bold]{entry[BREAKDOWN_TEXT_KEY]}[/bold]")
                    language = entry.get(BREAKDOWN_LANGUAGE_KEY)
                    given = entry[BREAKDOWN_ANSWER_KEY]
                    if language is not None and isinstance(given, str):
                        yield Static(GRADE_YOUR_ANSWER)
                        yield _code_static(
                            CodeBlock(language=language, content=given),
                            theme,
                        )
                    else:
                        yield Static(
                            f"{GRADE_YOUR_ANSWER}{_format_answer(given)}"
                        )
                    answer = entry[BREAKDOWN_CORRECT_ANSWER_KEY]
                    if isinstance(answer, CodeBlock):
                        yield Static(GRADE_CORRECT_ANSWER)
                        yield _code_static(answer, theme)
                    elif isinstance(answer, list) and all(
                        isinstance(item, CodeBlock) for item in answer
                    ):
                        yield Static(GRADE_CORRECT_ANSWERS)
                        for block in answer:
                            yield _code_static(block, theme)
                    elif language is not None and isinstance(answer, str):
                        yield Static(GRADE_CORRECT_ANSWER)
                        yield _code_static(
                            CodeBlock(language=language, content=answer),
                            theme,
                        )
                    else:
                        yield Static(
                            f"{GRADE_CORRECT_ANSWER}{_format_answer(answer)}"
                        )

    def _code_theme(self) -> str:
        """Return a Pygments theme matching the app when one is active."""
        try:
            return resolve_code_theme(self.app)
        except NoActiveAppError:
            return CODE_THEME_FALLBACK_DARK

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle restart or quit."""
        if event.button.id == "restart":
            self.action_restart()
        elif event.button.id == "quit":
            self.app.exit()

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> bool | None:
        """Hide the restart action when resubmission is not allowed."""
        if (
            action == "restart"
            and not self.form.config.allow_multiple_submissions
        ):
            return False
        return super().check_action(action, parameters)

    def action_restart(self) -> None:
        """Push a new form screen, or refuse when resubmission is forbidden."""
        if not self.form.config.allow_multiple_submissions:
            self.notify(SINGLE_SUBMISSION_NOTE, severity="warning")
            return
        self.app.push_screen(FormScreen(self.form, self.db_path))
