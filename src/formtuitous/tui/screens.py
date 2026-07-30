"""Screen definitions for the formtuitous TUI workflow."""

from pathlib import Path
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static

from formtuitous.database import init_db, save_response
from formtuitous.schema import FormDefinition


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
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Transition to the form screen on start."""
        if event.button.id == "start":
            self.app.push_screen(FormScreen(self.form, self.db_path))


class FormScreen(Screen):
    """Scrolling form with input widgets for each question."""

    BINDINGS: ClassVar[list[tuple[str, str] | tuple[str, str, str]]] = [  # type: ignore[assignment]
        ("ctrl+s", "submit", "Submit"),
        ("ctrl+f", "focus_first_input", "Focus Input"),
    ]

    def __init__(self, form: FormDefinition, db_path: Path) -> None:
        """Store the form definition, database path, and initialise input map."""
        self.form = form
        self.db_path = db_path
        self.inputs: dict[str, Input] = {}
        super().__init__()

    def compose(self) -> ComposeResult:
        """Render the scrolling form with input widgets for each question."""
        yield Header(show_clock=True)
        with VerticalScroll(id="question-scroll"):
            yield Static(f"[bold]{self.form.name}[/bold]", id="form-header")
            for question in self.form.questions:
                required = " *" if question.required else ""
                yield Label(f"{question.text}{required}")
                input_widget = Input(placeholder="Type your answer...")
                input_widget.id = f"input-{question.id}"
                self.inputs[question.id] = input_widget
                yield input_widget
            yield Button("Submit", id="submit", variant="primary")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Validate required fields and submit."""
        if event.button.id == "submit":
            self.action_submit()

    def action_submit(self) -> None:
        """Collect answers, validate, save to DB, show confirmation."""
        answers: dict[str, Any] = {}
        valid = True
        for question in self.form.questions:
            value = self.inputs[question.id].value
            if question.required and not value.strip():
                self.inputs[question.id].border_title = "required"
                valid = False
            answers[question.id] = value.strip() if value else ""
        if not valid:
            self.notify(
                "Please fill in all required fields.", severity="error"
            )
            return
        conn = init_db(self.db_path)
        save_response(conn, self.form.name, answers)
        conn.close()
        self.app.push_screen(SubmitScreen(self.db_path))

    def action_focus_first_input(self) -> None:
        """Focus the first input widget on the form."""
        for question in self.form.questions:
            input_widget = self.inputs.get(question.id)
            if input_widget is not None:
                self.set_focus(input_widget)
                return


class SubmitScreen(Screen):
    """Confirmation screen shown after a successful submission."""

    def __init__(self, db_path: Path) -> None:
        """Store the database path for display."""
        self.db_path = db_path
        super().__init__()

    def compose(self) -> ComposeResult:
        """Render the confirmation message and database location."""
        yield Header(show_clock=True)
        yield Static("[bold]Response saved![/bold]", id="confirm-title")
        yield Static("Your answers have been recorded.", id="confirm-msg")
        yield Static(
            f"Results saved to: [italic]{self.db_path}[/italic]",
            id="confirm-db-path",
        )
        yield Footer()
