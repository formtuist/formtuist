"""Main Textual application class for formtuist."""

import os
import uuid
from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding

from formtuist.database import ATTEMPT_ID_ENV_NAME
from formtuist.parser import parse_form


class FormtuistApp(App):
    """Textual application that runs the form-filling workflow."""

    TITLE = "formtuist"
    CSS_PATH = "styles.tcss"

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self, form_path: Path, db_path: Path) -> None:
        """Initialise the app with paths to a form JSON and a SQLite database."""
        self.form_path = form_path
        self.db_path = db_path
        self.form = parse_form(form_path)
        # one shared attempt id for this run; the serve command injects it
        # so every client of the run lands in the same fairness domain
        self.attempt_id = os.environ.get(ATTEMPT_ID_ENV_NAME) or str(
            uuid.uuid4()
        )
        super().__init__()
        self.theme = "ansi-dark"

    def on_mount(self) -> None:
        """Push the form screen directly on startup, skipping the welcome screen."""
        from formtuist.tui.screens import FormScreen  # noqa: PLC0415

        self.push_screen(FormScreen(self.form, self.db_path))


class ReviewApp(App):
    """Textual application for question-first manual review."""

    TITLE = "formtuist review"
    CSS_PATH = "styles.tcss"

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        form_path: Path,
        db_path: Path,
        review_type: str = "required",
        question_filter: str | None = None,
        reviewer: str | None = None,
    ) -> None:
        """Store review filters and load the form definition."""
        self.form_path = form_path
        self.db_path = db_path
        self.review_type = review_type
        self.question_filter = question_filter
        self.reviewer = reviewer
        self.form = parse_form(form_path)
        super().__init__()
        self.theme = "ansi-dark"

    def on_mount(self) -> None:
        """Push the reviewer screen on startup."""
        from formtuist.tui.review import ReviewScreen  # noqa: PLC0415

        self.push_screen(
            ReviewScreen(
                self.form,
                self.db_path,
                review_type=self.review_type,
                question_filter=self.question_filter,
                reviewer=self.reviewer,
            )
        )
