"""Main Textual application class for formtuitous."""

from pathlib import Path

from textual.app import App

from formtuitous.parser import parse_form
from formtuitous.tui.screens import WelcomeScreen


class FormtuitousApp(App):
    """Textual application that runs the form-filling workflow."""

    TITLE = "formtuitous"

    def __init__(self, form_path: Path, db_path: Path) -> None:
        """Initialise the app with paths to a form JSON and a SQLite database."""
        self.form_path = form_path
        self.db_path = db_path
        self.form = parse_form(form_path)
        super().__init__()

    def on_mount(self) -> None:
        """Push the welcome screen on startup."""
        self.push_screen(WelcomeScreen(self.form, self.db_path))
