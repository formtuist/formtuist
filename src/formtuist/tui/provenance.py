"""Read-only TUI for inspecting response form provenance."""

import sqlite3
from pathlib import Path
from typing import Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Header, Static

from formtuist.database import (
    FORM_CONTENTS_COLUMN,
    FORM_HASH_COLUMN,
    FORM_NAME_COLUMN,
    FORM_PATH_COLUMN,
    FORM_VERSION_COLUMN,
    GITHUB_USERNAME_COLUMN,
    ID_COLUMN,
    SUBMITTED_AT_COLUMN,
    get_responses,
    init_db,
)
from formtuist.tui.widgets import FormtuistFooter

PROVENANCE_LIST_TITLE = "Submissions"
PROVENANCE_DETAIL_TITLE = "Form provenance"
PROVENANCE_NO_RESPONSES = "No responses found."
PROVENANCE_SELECT_HINT = "Select a response and press Enter for details."
PROVENANCE_UNKNOWN = "unavailable"
PROVENANCE_LEGACY = "unavailable (legacy response)"
PROVENANCE_HASH_LENGTH = 12
PROVENANCE_TIMESTAMP_LENGTH = 16
PROVENANCE_SEPARATOR = "\n" + ("─" * 40) + "\n"


class ProvenanceScreen(Screen):
    """Display stored form provenance without modifying the database."""

    BINDINGS: ClassVar[
        list[Binding | tuple[str, str] | tuple[str, str, str]]
    ] = [
        Binding("enter", "open_detail", "Details"),
        Binding("escape", "back_to_list", "Back"),
        Binding("b", "back_to_list", "Back"),
        Binding("ctrl+n", "next_response", "Next"),
        Binding("ctrl+p", "prev_response", "Previous"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(
        self,
        db_path: Path,
        initial_view: str = "list",
        response_id: int | None = None,
    ) -> None:
        """Load responses and store the initial provenance view."""
        self.db_path = db_path
        self.initial_view = initial_view
        self.conn: sqlite3.Connection = init_db(db_path)
        self.responses = get_responses(self.conn)
        self.current_index = self._initial_index(response_id)
        self.detail_mode = initial_view in {"latest", "response"}
        self.list_items: list[Static] = []
        super().__init__()

    def _initial_index(self, response_id: int | None) -> int:
        """Return the initial response index for the requested view."""
        if response_id is not None:
            for index, response in enumerate(self.responses):
                if response.get(ID_COLUMN) == response_id:
                    return index
        if self.initial_view == "latest" and self.responses:
            return len(self.responses) - 1
        return 0

    def compose(self) -> ComposeResult:
        """Render the submission list and provenance detail panes."""
        yield Header(show_clock=True)
        with Horizontal(id="provenance-layout"):
            with Vertical(id="provenance-list-pane"):
                yield Static(PROVENANCE_LIST_TITLE, id="provenance-list-title")
                if not self.responses:
                    yield Static(PROVENANCE_NO_RESPONSES)
                else:
                    for response in self.responses:
                        item = Static(
                            self._response_label(response),
                            classes="provenance-item",
                        )
                        self.list_items.append(item)
                        yield item
            with VerticalScroll(id="provenance-detail"):
                yield Static(
                    PROVENANCE_SELECT_HINT,
                    id="provenance-detail-content",
                    markup=False,
                )
        yield FormtuistFooter()

    def on_mount(self) -> None:
        """Render the initial selection and detail state."""
        self._refresh_view()

    def on_unmount(self) -> None:
        """Close the read-only database connection."""
        self.conn.close()

    def _response_label(self, response: dict[str, Any]) -> str:
        """Return a compact list label for one response."""
        response_id = response.get(ID_COLUMN, PROVENANCE_UNKNOWN)
        form_name = response.get(FORM_NAME_COLUMN, PROVENANCE_UNKNOWN)
        version = response.get(FORM_VERSION_COLUMN) or "-"
        submitted = str(response.get(SUBMITTED_AT_COLUMN, ""))
        submitted = submitted[:PROVENANCE_TIMESTAMP_LENGTH]
        student = response.get(GITHUB_USERNAME_COLUMN) or "anonymous"
        form_hash = response.get(FORM_HASH_COLUMN)
        short_hash = (
            str(form_hash)[:PROVENANCE_HASH_LENGTH] if form_hash else "-"
        )
        return (
            f"#{response_id}  {form_name}  v{version}  {student}  "
            f"{submitted}  {short_hash}"
        )

    def _current_response(self) -> dict[str, Any] | None:
        """Return the currently selected response, if one exists."""
        if not self.responses:
            return None
        return self.responses[self.current_index]

    def _detail_text(self, response: dict[str, Any]) -> str:
        """Return all stored provenance details for one response."""
        source_path = response.get(FORM_PATH_COLUMN)
        source_available = bool(
            source_path and Path(str(source_path)).is_file()
        )
        form_hash = response.get(FORM_HASH_COLUMN)
        form_contents = response.get(FORM_CONTENTS_COLUMN)
        version = response.get(FORM_VERSION_COLUMN) or "-"
        student = response.get(GITHUB_USERNAME_COLUMN) or "anonymous"
        contents = form_contents or PROVENANCE_LEGACY
        return (
            f"{PROVENANCE_DETAIL_TITLE}\n"
            f"Response ID: {response.get(ID_COLUMN, PROVENANCE_UNKNOWN)}\n"
            f"Form: {response.get(FORM_NAME_COLUMN, PROVENANCE_UNKNOWN)}\n"
            f"Version: {version}\n"
            f"SHA-256: {form_hash or PROVENANCE_LEGACY}\n"
            f"Path: {source_path or PROVENANCE_LEGACY}\n"
            f"Source available: {'yes' if source_available else 'no'}\n"
            f"Submitted: {response.get(SUBMITTED_AT_COLUMN, '-')}\n"
            f"Student: {student}"
            f"{PROVENANCE_SEPARATOR}Exact form JSON\n{contents}"
        )

    def _refresh_view(self) -> None:
        """Refresh selection highlighting and the detail pane."""
        for index, item in enumerate(self.list_items):
            item.set_class(index == self.current_index, "current")
        detail = self.query_one("#provenance-detail-content", Static)
        response = self._current_response()
        if response is None:
            detail.update(PROVENANCE_NO_RESPONSES)
        elif self.detail_mode:
            detail.update(self._detail_text(response))
        else:
            detail.update(PROVENANCE_SELECT_HINT)

    def action_next_response(self) -> None:
        """Select the next response, wrapping at the end."""
        if self.responses:
            self.current_index = (self.current_index + 1) % len(self.responses)
            self._refresh_view()

    def action_prev_response(self) -> None:
        """Select the previous response, wrapping at the beginning."""
        if self.responses:
            self.current_index = (self.current_index - 1) % len(self.responses)
            self._refresh_view()

    def action_open_detail(self) -> None:
        """Open details for the selected response."""
        if self.responses:
            self.detail_mode = True
            self._refresh_view()

    def action_back_to_list(self) -> None:
        """Return to the submission-list view."""
        self.detail_mode = False
        self._refresh_view()
