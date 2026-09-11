"""Main Textual application class for formtuist."""

import os
import uuid
from pathlib import Path
from typing import ClassVar

from textual.app import App
from textual.binding import Binding

from formtuist.database import ATTEMPT_ID_ENV_NAME
from formtuist.parser import parse_form, read_form_source


class FormtuistApp(App):
    """Textual application that runs the form-filling workflow."""

    TITLE = "formtuist"
    CSS_PATH = "styles.tcss"

    # the command palette lives on ctrl+o so ctrl+n/ctrl+p can stay
    # reserved for next/previous question consistently across screens
    COMMAND_PALETTE_BINDING = "ctrl+o"
    COMMAND_PALETTE_DISPLAY = "^O"

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        form_path: Path,
        db_path: Path,
        code_dir: Path | None = None,
    ) -> None:
        """Initialise the app with form and database paths."""
        self.form_path = form_path
        self.form_source_path = form_path.resolve()
        self.db_path = db_path
        self.form_contents, self.form_hash = read_form_source(form_path)
        self.form = parse_form(form_path, code_dir)
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

        self.push_screen(
            FormScreen(
                self.form,
                self.db_path,
                form_version=self.form.version,
                form_hash=self.form_hash,
                form_source_path=self.form_source_path,
                form_contents=self.form_contents,
            )
        )


class ProvenanceApp(App):
    """Textual application for read-only form provenance inspection."""

    TITLE = "formtuist provenance"
    CSS_PATH = "styles.tcss"
    COMMAND_PALETTE_BINDING = "ctrl+o"
    COMMAND_PALETTE_DISPLAY = "^O"

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        db_path: Path,
        initial_view: str = "list",
        response_id: int | None = None,
    ) -> None:
        """Store the database path and initial provenance view."""
        self.db_path = db_path
        self.initial_view = initial_view
        self.response_id = response_id
        super().__init__()
        self.theme = "ansi-dark"

    def on_mount(self) -> None:
        """Push the provenance screen on startup."""
        from formtuist.tui.provenance import ProvenanceScreen  # noqa: PLC0415

        self.push_screen(
            ProvenanceScreen(
                self.db_path,
                initial_view=self.initial_view,
                response_id=self.response_id,
            )
        )


class ReviewApp(App):
    """Textual application for question-first manual review."""

    TITLE = "formtuist review"
    CSS_PATH = "styles.tcss"

    # keep the command palette on ctrl+o so ctrl+n/ctrl+p are next/previous
    # question and ctrl+b is the sidebar, matching the form screens
    COMMAND_PALETTE_BINDING = "ctrl+o"
    COMMAND_PALETTE_DISPLAY = "^O"

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(  # noqa: PLR0913, PLR0917
        self,
        form_path: Path,
        db_path: Path,
        review_type: str = "required",
        question_filter: str | None = None,
        reviewer: str | None = None,
        show_student_name: bool = True,
        code_dir: Path | None = None,
    ) -> None:
        """Store review filters and load the form definition."""
        self.form_path = form_path
        self.db_path = db_path
        self.review_type = review_type
        self.question_filter = question_filter
        self.reviewer = reviewer
        self.show_student_name = show_student_name
        self.code_dir = code_dir
        self.form = parse_form(form_path, code_dir)
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
                show_student_name=self.show_student_name,
            )
        )
