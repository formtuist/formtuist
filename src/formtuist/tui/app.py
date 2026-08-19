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
