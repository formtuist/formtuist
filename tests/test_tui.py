"""Smoke tests for TUI screens and application construction."""

import asyncio
import hashlib
import json
import sqlite3
from math import factorial
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pygments.styles import ClassNotFound
from rich.syntax import Syntax
from textual._context import NoActiveAppError
from textual.app import App
from textual.containers import VerticalScroll
from textual.widgets import (
    Footer,
    Input,
    Label,
    RadioButton,
    RadioSet,
    SelectionList,
    Static,
    Switch,
    TextArea,
)
from textual_timepiece.pickers import DatePicker
from whenever import Date

from formtuist.auth import GitHubIdentity
from formtuist.database import (
    FORM_CONTENTS_COLUMN,
    FORM_HASH_COLUMN,
    FORM_PATH_COLUMN,
    FORM_VERSION_COLUMN,
    init_db,
    save_response,
)
from formtuist.grader import TOTAL_KEY, grade_response
from formtuist.schema import (
    AuthProvider,
    CheckboxQuestion,
    CodeBlock,
    DateQuestion,
    FormConfig,
    FormDefinition,
    MultipleChoiceQuestion,
    NumericQuestion,
    NumericRange,
    ParagraphQuestion,
    Question,
    RatingQuestion,
    ShortTextQuestion,
    YesNoQuestion,
)
from formtuist.tui.app import FormtuistApp, ProvenanceApp
from formtuist.tui.provenance import (
    PROVENANCE_SCROLL_LINES,
    ProvenanceScreen,
)
from formtuist.tui.screens import (
    ALREADY_SUBMITTED_MESSAGE,
    SINGLE_SUBMISSION_NOTE,
    FormScreen,
    SubmitScreen,
    WelcomeScreen,
    shuffle_questions,
)
from formtuist.tui.widgets import (
    DatePickerField,
    get_widget_value,
    is_widget_empty,
    is_widget_valid,
    make_code_widget,
    make_input_widget,
    resolve_code_theme,
)

MIN_WELCOME_CHILDREN = 3
MIN_SUBMIT_CHILDREN = 3
PROVENANCE_RESPONSE_COUNT = 2
PROVENANCE_RESPONSE_ID = 3

# project stylesheet needed to verify text-wrapping behavior
STYLESHEET_PATH = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "formtuist"
    / "tui"
    / "styles.tcss"
)

# seed and question count used for deterministic shuffle tests
SHUFFLE_SEED = 42
SHUFFLE_QUESTION_COUNT = 8

# points and total for the auto-grading submit tests
GRADE_POINTS = 10
GRADE_TOTAL = 10

# small list and seed range for the permutation-reachability check
SMALL_SHUFFLE_COUNT = 3
SHUFFLE_SEED_RANGE = 150


def _build_questions_from_ids(ids: list[str]) -> list[Question]:
    """Build short_text questions from a list of unique ids."""
    return [
        ShortTextQuestion(
            id=id_,
            text=f"Question {id_}?",
            type="short_text",
        )
        for id_ in ids
    ]


def _build_questions(count: int) -> list[Question]:
    """Build a list of short_text questions with sequential ids."""
    return _build_questions_from_ids([f"q{index}" for index in range(count)])


class TestWelcomeScreen:
    """Tests for the welcome screen construction."""

    def test_construct_with_description(
        self, minimal_form: FormDefinition
    ) -> None:
        """WelcomeScreen stores form reference and db path."""
        screen = WelcomeScreen(minimal_form, Path(":memory:"))
        assert screen.form is minimal_form

    def test_compose_yields_widgets(
        self, minimal_form: FormDefinition
    ) -> None:
        """WelcomeScreen compose produces at least 3 children."""
        screen = WelcomeScreen(minimal_form, Path(":memory:"))
        children = list(screen.compose())
        assert len(children) >= MIN_WELCOME_CHILDREN

    def test_construct_without_description(self) -> None:
        """WelcomeScreen works for a form with no description."""
        form = FormDefinition(name="NoDesc", questions=[])
        screen = WelcomeScreen(form, Path("test.db"))
        assert screen.form.description == ""

    def test_compose_without_description(self) -> None:
        """WelcomeScreen compose works for a form with no description."""
        form = FormDefinition(name="NoDesc", questions=[])
        screen = WelcomeScreen(form, Path("test.db"))
        children = list(screen.compose())
        assert len(children) >= MIN_WELCOME_CHILDREN

    def test_on_button_pressed_start(
        self, minimal_form: FormDefinition
    ) -> None:
        """Pressing start pushes the form screen."""
        screen = WelcomeScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        with patch.object(
            WelcomeScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            button = MagicMock()
            button.id = "start"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_app.push_screen.assert_called_once()

    def test_on_button_pressed_other(
        self, minimal_form: FormDefinition
    ) -> None:
        """Pressing a non-start button does nothing."""
        screen = WelcomeScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        with patch.object(
            WelcomeScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            button = MagicMock()
            button.id = "other"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_app.push_screen.assert_not_called()


class TestFormScreen:
    """Tests for the form screen construction."""

    def test_construct(self, minimal_form: FormDefinition) -> None:
        """FormScreen stores form and db path."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        assert screen.form is minimal_form

    def test_has_compose_method(self, minimal_form: FormDefinition) -> None:
        """FormScreen has a compose method bound to the instance."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        assert callable(screen.compose)

    def test_inputs_initialised_empty(
        self, minimal_form: FormDefinition
    ) -> None:
        """FormScreen starts with an empty inputs dict."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        assert screen.inputs == {}

    def test_on_button_pressed_submit(
        self, minimal_form: FormDefinition
    ) -> None:
        """Pressing submit triggers action_submit."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        with patch.object(
            FormScreen, "action_submit", new=AsyncMock()
        ) as mock_action:
            button = MagicMock()
            button.id = "submit"
            event = MagicMock()
            event.button = button
            asyncio.run(screen.on_button_pressed(event))
        mock_action.assert_awaited_once()

    def test_on_button_pressed_other(
        self, minimal_form: FormDefinition
    ) -> None:
        """Pressing a non-submit button does nothing."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        with patch.object(
            FormScreen, "action_submit", new=AsyncMock()
        ) as mock_action:
            button = MagicMock()
            button.id = "other"
            event = MagicMock()
            event.button = button
            asyncio.run(screen.on_button_pressed(event))
        mock_action.assert_not_awaited()

    def test_action_submit_valid(self, minimal_form: FormDefinition) -> None:
        """action_submit saves valid answers and pushes submit screen."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "Alice"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as mock_init:
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        mock_init.assert_called_once()
        mock_save.assert_called_once_with(
            mock_init.return_value,
            "Minimal",
            {"q1": "Alice"},
            None,
            None,
            grade=None,
            attempt_id=mock_app.attempt_id,
        )
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()

    def test_action_submit_saves_provenance(self, tmp_path: Path) -> None:
        """FormScreen passes source provenance to save_response."""
        raw = b'{"name":"Saved","version":"v2","questions":[]}\n'
        source_path = tmp_path / "saved.json"
        source_path.write_bytes(raw)
        form = FormDefinition(
            name="Saved",
            version="v2",
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text")
            ],
        )
        screen = FormScreen(
            form,
            Path(":memory:"),
            form_version=form.version,
            form_hash=hashlib.sha256(raw).hexdigest(),
            form_source_path=source_path.resolve(),
            form_contents=raw.decode("utf-8"),
        )
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify"):
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        assert mock_save.call_args.kwargs[FORM_VERSION_COLUMN] == "v2"
        assert mock_save.call_args.kwargs[FORM_HASH_COLUMN] == (
            hashlib.sha256(raw).hexdigest()
        )
        assert mock_save.call_args.kwargs[FORM_PATH_COLUMN] == str(
            source_path.resolve()
        )
        assert mock_save.call_args.kwargs[FORM_CONTENTS_COLUMN] == raw.decode(
            "utf-8"
        )

    def test_action_submit_stores_iso_date_from_picker(self) -> None:
        """action_submit saves the ISO date string from the DatePicker."""
        form = FormDefinition(
            name="When",
            questions=[DateQuestion(id="d", text="Date?", type="date")],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        picker = DatePicker(Date(2024, 12, 25))
        screen.inputs["d"] = picker
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        saved = mock_save.call_args.args[2]
        assert saved == {"d": "2024-12-25"}
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()

    def test_action_submit_blocks_empty_required_date(self) -> None:
        """action_submit notifies when a required DatePicker is empty."""
        form = FormDefinition(
            name="When",
            questions=[
                DateQuestion(id="d", text="Date?", type="date", required=True),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        picker = DatePicker()
        screen.inputs["d"] = picker
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    asyncio.run(screen.action_submit())
        mock_notify.assert_called_once()
        mock_app.push_screen.assert_not_called()

    def test_action_submit_missing_required(
        self, minimal_form: FormDefinition
    ) -> None:
        """action_submit notifies when required fields are empty."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = ""
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as mock_init:
                    asyncio.run(screen.action_submit())
        mock_init.assert_not_called()
        mock_notify.assert_called_once()
        mock_app.push_screen.assert_not_called()

    def test_action_submit_with_optional_empty(self) -> None:
        """action_submit handles optional questions with empty values."""
        form = FormDefinition(
            name="Test",
            questions=[
                ShortTextQuestion(
                    id="q1",
                    text="Optional?",
                    required=False,
                    type="short_text",
                ),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = ""
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as mock_init:
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        mock_init.assert_called_once()
        mock_save.assert_called_once_with(
            mock_init.return_value,
            "Test",
            {"q1": ""},
            None,
            None,
            grade=None,
            attempt_id=mock_app.attempt_id,
        )
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()

    def test_action_submit_skips_grading_when_disabled(
        self, minimal_form: FormDefinition
    ) -> None:
        """action_submit sends no report when auto-grading is off."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "Alice"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        mock_app.push_screen.assert_called_once()
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, SubmitScreen)
        assert pushed.grade_report is None
        mock_notify.assert_not_called()

    def test_action_submit_auto_grades(self) -> None:
        """action_submit passes a grade report when auto-grading is on."""
        form = FormDefinition(
            name="Auto",
            config=FormConfig(auto_grade=True),
            questions=[
                ShortTextQuestion(
                    id="q1",
                    text="Capital?",
                    type="short_text",
                    correct_answer="Paris",
                    points=GRADE_POINTS,
                    grading_type="exact",
                ),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "Paris"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        mock_app.push_screen.assert_called_once()
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, SubmitScreen)
        assert pushed.grade_report is not None
        assert pushed.grade_report[TOTAL_KEY] == GRADE_TOTAL
        mock_notify.assert_not_called()

    def test_action_submit_auto_grades_yes_no(self) -> None:
        """action_submit grades a yes_no answer from a Switch widget."""
        form = FormDefinition(
            name="TrueFalse",
            config=FormConfig(auto_grade=True),
            questions=[
                YesNoQuestion(
                    id="tf",
                    text="Sky is blue?",
                    type="yes_no",
                    correct_answer=True,
                    points=GRADE_POINTS,
                    grading_type="exact",
                ),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_switch = MagicMock(spec=Switch)
        mock_switch.value = True
        screen.inputs["tf"] = mock_switch
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        mock_app.push_screen.assert_called_once()
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, SubmitScreen)
        assert pushed.grade_report is not None
        assert pushed.grade_report[TOTAL_KEY] == GRADE_POINTS
        assert pushed.grade_report["breakdown"][0]["correct"] is True
        assert pushed.grade_report["breakdown"][0]["answer"] is True
        mock_notify.assert_not_called()

    def test_action_submit_persists_grade_snapshot(self) -> None:
        """action_submit stores a JSON-safe grade snapshot when auto-grading."""
        form = FormDefinition(
            name="Auto",
            config=FormConfig(auto_grade=True),
            questions=[
                ShortTextQuestion(
                    id="q1",
                    text="Capital?",
                    type="short_text",
                    correct_answer="Paris",
                    points=GRADE_POINTS,
                    grading_type="exact",
                ),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "Paris"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        saved_grade = mock_save.call_args.kwargs["grade"]
        assert saved_grade is not None
        assert saved_grade[TOTAL_KEY] == GRADE_TOTAL
        assert len(saved_grade["breakdown"]) == 1
        assert saved_grade["breakdown"][0]["correct"] is True
        assert saved_grade["breakdown"][0]["answer"] == "Paris"
        assert "graded_at" in saved_grade
        json.dumps(saved_grade)
        mock_notify.assert_not_called()

    def test_action_submit_stores_grade_when_not_auto(self) -> None:
        """A gradeable form stores a grade even when auto_grade is off."""
        form = FormDefinition(
            name="Hidden",
            config=FormConfig(auto_grade=False),
            questions=[
                ShortTextQuestion(
                    id="q1",
                    text="Capital?",
                    type="short_text",
                    correct_answer="Paris",
                    points=GRADE_POINTS,
                    grading_type="exact",
                ),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "Paris"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        saved_grade = mock_save.call_args.kwargs["grade"]
        assert saved_grade is not None
        assert saved_grade[TOTAL_KEY] == GRADE_TOTAL
        pushed = mock_app.push_screen.call_args[0][0]
        assert isinstance(pushed, SubmitScreen)
        assert pushed.grade_report is None
        mock_notify.assert_not_called()

    def test_action_submit_does_not_store_grade_for_poll(self) -> None:
        """A form without correct answers stores no grade."""
        form = FormDefinition(
            name="Poll",
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "ok"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db"):
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        asyncio.run(screen.action_submit())
        assert mock_save.call_args.kwargs["grade"] is None
        mock_notify.assert_not_called()

    def test_action_submit_with_github_auth(self) -> None:
        """action_submit validates the token and stores the identity."""
        form = FormDefinition(
            name="Auth",
            config=FormConfig(auth=AuthProvider.GITHUB),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = "ghp_valid_token"
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as mock_init:
                    with patch(
                        "formtuist.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        with patch(
                            "formtuist.tui.screens.fetch_github_identity",
                            return_value=GitHubIdentity(
                                username="octocat",
                                profile_url="https://github.com/octocat",
                            ),
                        ):
                            asyncio.run(screen.action_submit())
        mock_init.assert_called_once()
        mock_save.assert_called_once_with(
            mock_init.return_value,
            "Auth",
            {"q1": "answer"},
            "octocat",
            "https://github.com/octocat",
            grade=None,
            attempt_id=mock_app.attempt_id,
        )
        mock_app.push_screen.assert_called_once()
        pushed_screen = mock_app.push_screen.call_args[0][0]
        assert pushed_screen.identity is not None
        assert pushed_screen.identity.username == "octocat"
        assert pushed_screen.identity.profile_url == (
            "https://github.com/octocat"
        )
        mock_notify.assert_not_called()

    def test_action_submit_blocks_empty_token(self) -> None:
        """action_submit blocks submission when the token is empty."""
        form = FormDefinition(
            name="Auth",
            config=FormConfig(auth=AuthProvider.GITHUB),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = ""
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as mock_init:
                    asyncio.run(screen.action_submit())
        mock_init.assert_not_called()
        mock_notify.assert_called_once()
        mock_app.push_screen.assert_not_called()

    def test_action_submit_blocks_invalid_token(self) -> None:
        """action_submit blocks submission when the token is invalid."""
        form = FormDefinition(
            name="Auth",
            config=FormConfig(auth=AuthProvider.GITHUB),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = "ghp_bad_token"
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as mock_init:
                    with patch(
                        "formtuist.tui.screens.fetch_github_identity",
                        return_value=None,
                    ):
                        asyncio.run(screen.action_submit())
        mock_init.assert_not_called()
        mock_notify.assert_called_once()
        mock_app.push_screen.assert_not_called()

    def test_action_submit_blocks_duplicate_single_submission(
        self,
    ) -> None:
        """action_submit blocks a second submission by the same identity."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = "ghp_valid_token"
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as _mock_init:
                    with patch(
                        "formtuist.tui.screens.ensure_single_submission_index",
                        return_value=True,
                    ):
                        with patch(
                            "formtuist.tui.screens.has_submission",
                            return_value=True,
                        ):
                            with patch(
                                "formtuist.tui.screens.save_response"
                            ) as mock_save:
                                with patch(
                                    "formtuist.tui.screens.fetch_github_identity",
                                    return_value=GitHubIdentity(
                                        username="octocat",
                                        profile_url="https://github.com/octocat",
                                    ),
                                ):
                                    asyncio.run(screen.action_submit())
        mock_save.assert_not_called()
        mock_app.push_screen.assert_not_called()
        mock_notify.assert_called_once_with(
            ALREADY_SUBMITTED_MESSAGE, severity="error"
        )

    def test_action_submit_allows_first_single_submission(self) -> None:
        """action_submit saves when the identity has not yet submitted."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = "ghp_valid_token"
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as _mock_init:
                    with patch(
                        "formtuist.tui.screens.ensure_single_submission_index",
                        return_value=True,
                    ):
                        with patch(
                            "formtuist.tui.screens.has_submission",
                            return_value=False,
                        ):
                            with patch(
                                "formtuist.tui.screens.save_response"
                            ) as mock_save:
                                mock_save.return_value = 1
                                with patch(
                                    "formtuist.tui.screens.fetch_github_identity",
                                    return_value=GitHubIdentity(
                                        username="octocat",
                                        profile_url="https://github.com/octocat",
                                    ),
                                ):
                                    asyncio.run(screen.action_submit())
        mock_save.assert_called_once()
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()

    def test_action_submit_ignores_prior_when_multiple(self) -> None:
        """A prior submission does not block when resubmission is allowed."""
        form = FormDefinition(
            name="Poll",
            config=FormConfig(auth=AuthProvider.GITHUB),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = "ghp_valid_token"
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as _mock_init:
                    with patch(
                        "formtuist.tui.screens.has_submission",
                        return_value=True,
                    ) as mock_check:
                        with patch(
                            "formtuist.tui.screens.save_response"
                        ) as mock_save:
                            mock_save.return_value = 1
                            with patch(
                                "formtuist.tui.screens.fetch_github_identity",
                                return_value=GitHubIdentity(
                                    username="octocat",
                                    profile_url="https://github.com/octocat",
                                ),
                            ):
                                asyncio.run(screen.action_submit())
        mock_save.assert_called_once()
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()
        mock_check.assert_not_called()

    def test_action_submit_catches_integrity_error(self) -> None:
        """A raced duplicate save shows the already-submitted message."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[
                ShortTextQuestion(id="q1", text="Q?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock(spec=Input)
        mock_input.value = "answer"
        mock_input.is_valid = True
        screen.inputs["q1"] = mock_input
        mock_auth_input = MagicMock(spec=Input)
        mock_auth_input.value = "ghp_valid_token"
        screen.auth_input = mock_auth_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuist.tui.screens.init_db") as _mock_init:
                    with patch(
                        "formtuist.tui.screens.ensure_single_submission_index",
                        return_value=True,
                    ):
                        with patch(
                            "formtuist.tui.screens.has_submission",
                            return_value=False,
                        ):
                            with patch(
                                "formtuist.tui.screens.save_response",
                                side_effect=sqlite3.IntegrityError,
                            ):
                                with patch(
                                    "formtuist.tui.screens.fetch_github_identity",
                                    return_value=GitHubIdentity(
                                        username="octocat",
                                        profile_url="https://github.com/octocat",
                                    ),
                                ):
                                    asyncio.run(screen.action_submit())
        mock_app.push_screen.assert_not_called()
        mock_notify.assert_called_once_with(
            ALREADY_SUBMITTED_MESSAGE, severity="error"
        )

    def test_action_focus_first_input(
        self, minimal_form: FormDefinition
    ) -> None:
        """action_focus_first_input sets focus on the first input."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_input = MagicMock()
        mock_input.id = "input-q1"
        screen.inputs["q1"] = mock_input
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_first_input()
        mock_set_focus.assert_called_once_with(mock_input)

    def test_truncate_short_text(self) -> None:
        """_truncate returns short text unchanged."""
        screen = FormScreen(
            FormDefinition(name="T", questions=[]), Path(":memory:")
        )
        assert screen._truncate("Short") == "Short"

    def test_truncate_long_text(self) -> None:
        """_truncate shortens long text with an ellipsis."""
        screen = FormScreen(
            FormDefinition(name="T", questions=[]), Path(":memory:")
        )
        long = "A" * 50
        result = screen._truncate(long)
        assert len(result) <= 25  # noqa: PLR2004
        assert result.endswith("...")

    def test_update_sidebar_and_counter(self) -> None:
        """_update_sidebar_and_counter refreshes the label and highlights."""
        screen = FormScreen(
            FormDefinition(
                name="F",
                questions=[
                    ShortTextQuestion(id="a", text="A?", type="short_text"),
                    ShortTextQuestion(id="b", text="B?", type="short_text"),
                ],
            ),
            Path(":memory:"),
        )
        mock_static = MagicMock()
        mock_static.update = MagicMock()
        mock_item0 = MagicMock()
        mock_item1 = MagicMock()
        screen.sidebar_items = [mock_item0, mock_item1]
        with patch.object(FormScreen, "query_one") as mock_query:
            mock_query.return_value = mock_static
            screen.current_index = 0
            screen._update_sidebar_and_counter()
        mock_static.update.assert_called_once_with("Question 1 / 2")
        mock_item0.set_class.assert_called_once_with(True, "current")
        mock_item1.set_class.assert_called_once_with(False, "current")

    def test_watch_focused_matches_input(
        self, minimal_form: FormDefinition
    ) -> None:
        """watch_focused updates counter and sidebar for a matching input."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_widget = MagicMock()
        mock_widget.id = "input-q1"
        with patch.object(
            FormScreen, "_update_sidebar_and_counter"
        ) as mock_update:
            screen.watch_focused(None, mock_widget)
        assert screen.current_index == 0
        mock_update.assert_called_once()

    def test_watch_focused_no_match(
        self, minimal_form: FormDefinition
    ) -> None:
        """watch_focused ignores focus on non-input widgets."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_widget = MagicMock()
        mock_widget.id = "some-other-widget"
        with patch.object(
            FormScreen, "_update_sidebar_and_counter"
        ) as mock_update:
            screen.current_index = 99
            screen.watch_focused(None, mock_widget)
        assert screen.current_index == 99  # noqa: PLR2004
        mock_update.assert_not_called()

    def test_watch_focused_none(self, minimal_form: FormDefinition) -> None:
        """watch_focused does nothing when new_val is None."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        with patch.object(
            FormScreen, "_update_sidebar_and_counter"
        ) as mock_update:
            screen.current_index = 99
            screen.watch_focused(None, None)
        assert screen.current_index == 99  # noqa: PLR2004
        mock_update.assert_not_called()

    def test_action_focus_next(self, minimal_form: FormDefinition) -> None:
        """action_focus_next focuses the next question input."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_q1 = MagicMock()
        mock_q1.id = "input-q1"
        screen.inputs["q1"] = mock_q1
        screen.current_index = 0
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_next()
        mock_set_focus.assert_called_once_with(mock_q1)

    def test_action_focus_next_wraparound(self) -> None:
        """action_focus_next wraps from last question to first."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
                ShortTextQuestion(id="b", text="B?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_a = MagicMock()
        mock_a.id = "input-a"
        mock_b = MagicMock()
        mock_b.id = "input-b"
        screen.inputs = {"a": mock_a, "b": mock_b}
        screen.current_index = 1
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_next()
        mock_set_focus.assert_called_once_with(mock_a)

    def test_action_focus_previous(self, minimal_form: FormDefinition) -> None:
        """action_focus_previous focuses the previous question input."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_q1 = MagicMock()
        mock_q1.id = "input-q1"
        screen.inputs["q1"] = mock_q1
        screen.current_index = 0
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_previous()
        mock_set_focus.assert_called_once_with(mock_q1)

    def test_action_focus_previous_wraparound(self) -> None:
        """action_focus_previous wraps from first question to last."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
                ShortTextQuestion(id="b", text="B?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_a = MagicMock()
        mock_a.id = "input-a"
        mock_b = MagicMock()
        mock_b.id = "input-b"
        screen.inputs = {"a": mock_a, "b": mock_b}
        screen.current_index = 0
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_previous()
        mock_set_focus.assert_called_once_with(mock_b)

    def test_action_toggle_sidebar(self, minimal_form: FormDefinition) -> None:
        """action_toggle_sidebar toggles the hidden class."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_sidebar = MagicMock()
        with patch.object(FormScreen, "query_one") as mock_query:
            mock_query.return_value = mock_sidebar
            screen.action_toggle_sidebar()
        mock_query.assert_called_once_with("#sidebar")
        mock_sidebar.toggle_class.assert_called_once_with("hidden")

    def test_on_mount_focuses_first_input(
        self, minimal_form: FormDefinition
    ) -> None:
        """on_mount calls action_focus_first_input."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        with patch.object(
            FormScreen, "action_focus_first_input"
        ) as mock_focus:
            screen.on_mount()
        mock_focus.assert_called_once()

    def test_focus_next_no_input_match(self) -> None:
        """action_focus_next handles missing input gracefully."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        screen.inputs = {}
        screen.current_index = 0
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_next()
        mock_set_focus.assert_not_called()

    def test_focus_previous_no_input_match(self) -> None:
        """action_focus_previous handles missing input gracefully."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        screen.inputs = {}
        screen.current_index = 0
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_previous()
        mock_set_focus.assert_not_called()

    def test_hide_scrollbars_sets_styles(
        self, minimal_form: FormDefinition
    ) -> None:
        """_hide_scrollbars sets scrollbar sizes to zero."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_scroll = MagicMock()
        mock_sidebar = MagicMock()
        mock_scroll.styles = MagicMock()
        mock_sidebar.styles = MagicMock()
        with patch.object(
            FormScreen,
            "query_one",
            side_effect=lambda id: (
                mock_scroll if "scroll" in id else mock_sidebar
            ),
        ):
            screen._hide_scrollbars()
        mock_scroll.styles.scrollbar_size_horizontal = 0
        mock_scroll.styles.scrollbar_size_vertical = 0
        mock_sidebar.styles.scrollbar_size_horizontal = 0
        mock_sidebar.styles.scrollbar_size_vertical = 0

    def test_update_code_widgets(self) -> None:
        """_update_code_widgets refreshes the Static renderable."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(
                    id="a",
                    text="A?",
                    type="short_text",
                    code=CodeBlock(language="python", content="x = 1"),
                ),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_static = MagicMock()
        screen.code_widgets["a"] = mock_static
        screen._update_code_widgets("monokai")
        mock_static.update.assert_called_once()

    def test_sync_code_theme_skips_when_fixed(self) -> None:
        """_sync_code_theme does nothing when a fixed theme is configured."""
        screen = FormScreen(
            FormDefinition(name="F", questions=[]),
            Path(":memory:"),
            code_theme="monokai",
        )
        mock_app = MagicMock()
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            screen._sync_code_theme()
        mock_app.assert_not_called()

    def test_sync_code_theme_handles_no_app(self) -> None:
        """_sync_code_theme is safe when there is no active app."""
        screen = FormScreen(
            FormDefinition(name="F", questions=[]),
            Path(":memory:"),
        )
        with patch.object(
            FormScreen,
            "app",
            new_callable=PropertyMock,
            side_effect=NoActiveAppError,
        ):
            screen._sync_code_theme()

    def test_on_app_theme_change_syncs(self) -> None:
        """_on_app_theme_change delegates to _sync_code_theme."""
        screen = FormScreen(
            FormDefinition(name="F", questions=[]),
            Path(":memory:"),
        )
        with patch.object(FormScreen, "_sync_code_theme") as mock_sync:
            screen._on_app_theme_change("old", "new")
        mock_sync.assert_called_once()

    def test_on_mount_watches_theme_when_app_present(self) -> None:
        """on_mount watches app.theme when auto theme is enabled."""
        screen = FormScreen(
            FormDefinition(name="F", questions=[]),
            Path(":memory:"),
        )
        mock_app = MagicMock()
        with patch.object(
            FormScreen, "action_focus_first_input"
        ) as mock_focus:
            with patch.object(FormScreen, "_hide_scrollbars") as mock_hide:
                with patch.object(
                    FormScreen, "app", new_callable=PropertyMock
                ) as mock_prop:
                    mock_prop.return_value = mock_app
                    with patch.object(
                        FormScreen, "_sync_code_theme"
                    ) as mock_sync:
                        with patch.object(FormScreen, "watch") as mock_watch:
                            screen.on_mount()
        mock_focus.assert_called_once()
        mock_hide.assert_called_once()
        mock_sync.assert_called_once()
        mock_watch.assert_called_once_with(
            mock_app, "theme", screen._on_app_theme_change
        )

    def test_compose_populates_code_widgets(self) -> None:
        """Compose stores code widgets when run inside a Textual app."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(
                    id="a",
                    text="A?",
                    type="short_text",
                    code=CodeBlock(language="python", content="x = 1"),
                ),
            ],
        )

        async def run() -> None:
            app: App = App()
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                assert "a" in screen.code_widgets

        asyncio.run(run())

    def test_compose_creates_auth_input_when_configured(self) -> None:
        """Compose creates the token field when auth is enabled."""
        form = FormDefinition(
            name="Auth",
            config=FormConfig(auth=AuthProvider.GITHUB),
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
            ],
        )

        async def run() -> None:
            app: App = App()
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                assert screen.auth_input is not None
                assert screen.auth_input.id == "auth-input"

        asyncio.run(run())

    def test_compose_creates_date_picker(self) -> None:
        """Compose stores a DatePicker widget for a date question."""
        form = FormDefinition(
            name="When",
            questions=[DateQuestion(id="d", text="Date?", type="date")],
        )

        async def run() -> None:
            app: App = App()
            async with app.run_test() as pilot:
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                picker = cast(DatePickerField, screen.inputs["d"])
                assert isinstance(picker, DatePickerField)
                assert picker.expanded is False
                await pilot.click(picker.query_one("#date-input"))
                await pilot.pause()
                assert picker.expanded is True

        asyncio.run(run())

    def test_date_picker_stays_open_after_toggle(self) -> None:
        """DatePickerField keeps the calendar open across frames."""
        form = FormDefinition(
            name="When",
            questions=[DateQuestion(id="d", text="Date?", type="date")],
        )

        async def run() -> None:
            app: App = App()
            async with app.run_test() as pilot:
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                picker = cast(DatePickerField, screen.inputs["d"])
                await pilot.click(picker.query_one("#toggle-button"))
                await pilot.pause()
                assert picker.expanded is True
                for _ in range(4):
                    await pilot.pause()
                    assert picker.expanded is True

        asyncio.run(run())

    def test_date_picker_closes_after_selection(self) -> None:
        """DatePickerField closes its calendar once a date is picked."""
        form = FormDefinition(
            name="When",
            questions=[DateQuestion(id="d", text="Date?", type="date")],
        )

        async def run() -> None:
            app: App = App()
            async with app.run_test() as pilot:
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                picker = cast(DatePickerField, screen.inputs["d"])
                await pilot.click(picker.query_one("#date-input"))
                await pilot.pause()
                assert bool(picker.expanded) is True
                picker.date = Date(2026, 8, 12)
                await pilot.pause()
                assert bool(picker.expanded) is False
                assert get_widget_value(picker) == "2026-08-12"

        asyncio.run(run())

    def test_compose_omits_auth_input_by_default(self) -> None:
        """Compose does not create the token field when auth is disabled."""
        form = FormDefinition(
            name="NoAuth",
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
            ],
        )

        async def run() -> None:
            app: App = App()
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                assert screen.auth_input is None

        asyncio.run(run())

    def test_focus_first_input_prefers_auth_field(self) -> None:
        """action_focus_first_input focuses the token field when present."""
        form = FormDefinition(
            name="Auth",
            config=FormConfig(auth=AuthProvider.GITHUB),
            questions=[
                ShortTextQuestion(id="a", text="A?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_auth = MagicMock(spec=Input)
        screen.auth_input = mock_auth
        with patch.object(FormScreen, "set_focus") as mock_set_focus:
            screen.action_focus_first_input()
        mock_set_focus.assert_called_once_with(mock_auth)

    def test_on_mount_syncs_code_theme(self) -> None:
        """on_mount resolves the code theme from the app theme."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(
                    id="a",
                    text="A?",
                    type="short_text",
                    code=CodeBlock(language="python", content="x = 1"),
                ),
            ],
        )

        async def run() -> None:
            app: App = App()
            app.theme = "dracula"
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                assert screen.code_theme == "auto"
                assert "a" in screen.code_widgets

        asyncio.run(run())

    def test_update_code_widgets_skips_missing_widgets(self) -> None:
        """_update_code_widgets ignores questions without a stored widget."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(
                    id="a",
                    text="A?",
                    type="short_text",
                    code=CodeBlock(language="python", content="x = 1"),
                ),
                ShortTextQuestion(id="b", text="B?", type="short_text"),
            ],
        )
        screen = FormScreen(form, Path(":memory:"))
        mock_static = MagicMock()
        screen.code_widgets["a"] = mock_static
        screen._update_code_widgets("monokai")
        mock_static.update.assert_called_once()

    def test_long_question_text_wraps(self) -> None:
        """Long question labels wrap instead of being clipped."""

        async def run() -> None:
            form = FormDefinition(
                name="Long",
                questions=[
                    ShortTextQuestion(
                        id="q1",
                        text=("A very long question " * 12).strip(),
                        type="short_text",
                    ),
                ],
            )
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test() as pilot:
                screen = FormScreen(form, Path(":memory:"))
                await app.push_screen(screen)
                await pilot.pause()
                scroll = screen.query_one("#question-scroll")
                label = next(
                    w
                    for w in screen.query(Label)
                    if "very long" in str(w.content)
                )
                assert label.size.width <= scroll.content_size.width
                assert label.size.height > 1

        asyncio.run(run())


class TestShuffleQuestions:
    """Tests for the question-order shuffling helper."""

    def test_preserves_all_questions(self) -> None:
        """Shuffling keeps every question exactly once."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert sorted(q.id for q in result) == sorted(q.id for q in questions)
        assert len(result) == len(questions)

    def test_deterministic_with_same_seed(self) -> None:
        """Shuffling with the same seed is reproducible."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        first = shuffle_questions(questions, SHUFFLE_SEED)
        second = shuffle_questions(questions, SHUFFLE_SEED)
        assert [q.id for q in first] == [q.id for q in second]

    def test_changes_order_with_seed(self) -> None:
        """Shuffling with a fixed seed reorders the questions."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert [q.id for q in result] != [q.id for q in questions]

    def test_empty_list(self) -> None:
        """Shuffling an empty list returns an empty list."""
        assert shuffle_questions([], SHUFFLE_SEED) == []

    def test_single_question_keeps_position(self) -> None:
        """A single question is the only possible ordering."""
        questions = _build_questions(1)
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert [q.id for q in result] == [q.id for q in questions]

    def test_input_list_not_mutated(self) -> None:
        """Shuffling copies the list and leaves the caller's order intact."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        original_ids = [q.id for q in questions]
        shuffle_questions(questions, SHUFFLE_SEED)
        assert [q.id for q in questions] == original_ids

    def test_all_permutations_reachable_across_seeds(self) -> None:
        """Small lists produce every possible ordering across seeds."""
        questions = _build_questions(SMALL_SHUFFLE_COUNT)
        orders = {
            tuple(q.id for q in shuffle_questions(questions, seed))
            for seed in range(SHUFFLE_SEED_RANGE)
        }
        assert len(orders) == factorial(SMALL_SHUFFLE_COUNT)

    @pytest.mark.propertybased
    @given(st.lists(st.text(min_size=1), min_size=0, max_size=20, unique=True))
    def test_size_and_membership_preserved(self, ids: list[str]) -> None:
        """Shuffling keeps the size and the set of questions unchanged."""
        questions = _build_questions_from_ids(ids)
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert len(result) == len(questions)
        assert sorted(q.id for q in result) == sorted(q.id for q in questions)

    @pytest.mark.propertybased
    @given(st.lists(st.text(min_size=1), min_size=1, max_size=20, unique=True))
    def test_unseeded_shuffle_is_permutation(self, ids: list[str]) -> None:
        """The production default seed still produces a permutation."""
        questions = _build_questions_from_ids(ids)
        result = shuffle_questions(questions)
        assert len(result) == len(questions)
        assert sorted(q.id for q in result) == sorted(q.id for q in questions)

    @pytest.mark.propertybased
    @given(st.integers(min_value=0, max_value=1_000_000))
    def test_any_seed_is_reproducible(self, seed: int) -> None:
        """A fixed seed always yields the same ordering."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        first = shuffle_questions(questions, seed)
        second = shuffle_questions(questions, seed)
        assert [q.id for q in first] == [q.id for q in second]

    def test_pinned_questions_keep_positions(self) -> None:
        """Questions opting out keep their exact file positions."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        questions[2].randomize = False
        questions[5].randomize = False
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert result[2] is questions[2]
        assert result[5] is questions[5]
        assert sorted(q.id for q in result) == sorted(q.id for q in questions)

    def test_all_pinned_keeps_file_order(self) -> None:
        """With every question pinned the order is unchanged."""
        questions = _build_questions(SHUFFLE_QUESTION_COUNT)
        for question in questions:
            question.randomize = False
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert [q.id for q in result] == [q.id for q in questions]

    @pytest.mark.propertybased
    @given(st.lists(st.booleans(), min_size=0, max_size=15))
    def test_anchored_shuffle_preserves_pins(self, flags: list[bool]) -> None:
        """Pinned questions keep positions and the result is a permutation."""
        questions = [
            ShortTextQuestion(
                id=f"q{index}",
                text=f"Question {index}?",
                type="short_text",
                randomize=flag,
            )
            for index, flag in enumerate(flags)
        ]
        result = shuffle_questions(questions, SHUFFLE_SEED)
        assert len(result) == len(questions)
        assert sorted(q.id for q in result) == sorted(q.id for q in questions)
        for index, question in enumerate(questions):
            if not question.randomize:
                assert result[index] is question


class TestRandomizedOrder:
    """Tests for randomized question ordering in FormScreen."""

    def test_file_order_when_disabled(self) -> None:
        """FormScreen keeps the file order when randomization is disabled."""
        form = FormDefinition(
            name="Fixed",
            questions=_build_questions(SHUFFLE_QUESTION_COUNT),
        )
        screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
        assert [q.id for q in screen.ordered_questions] == [
            q.id for q in form.questions
        ]

    def test_shuffled_order_when_enabled(self) -> None:
        """FormScreen shuffles the questions when randomization is enabled."""
        form = FormDefinition(
            name="Shuffled",
            config=FormConfig(randomize_questions=True),
            questions=_build_questions(SHUFFLE_QUESTION_COUNT),
        )
        screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
        shuffled_ids = [q.id for q in screen.ordered_questions]
        assert shuffled_ids != [q.id for q in form.questions]
        assert sorted(shuffled_ids) == sorted(q.id for q in form.questions)

    def test_choice_order_unchanged_by_default(self) -> None:
        """Choices keep file order unless the question opts in."""
        form = FormDefinition(
            name="Fixed",
            questions=[
                MultipleChoiceQuestion(
                    id="mc",
                    text="Pick?",
                    type="multiple_choice",
                    choices=["A", "B", "C"],
                    correct_answer="B",
                    points=1,
                )
            ],
        )
        screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
        assert "mc" not in screen.choice_orders

    def test_choice_order_shuffles_per_seed(self) -> None:
        """Opt-in questions shuffle choices deterministically per seed."""
        form = FormDefinition(
            name="ShuffledChoices",
            questions=[
                MultipleChoiceQuestion(
                    id="mc",
                    text="Pick?",
                    type="multiple_choice",
                    choices=["A", "B", "C", "D"],
                    correct_answer="B",
                    points=1,
                    randomize_choices=True,
                )
            ],
        )
        first = FormScreen(form, Path(":memory:"), seed=42)
        assert first.choice_orders["mc"] == ["C", "B", "D", "A"]
        again = FormScreen(form, Path(":memory:"), seed=42)
        assert again.choice_orders["mc"] == ["C", "B", "D", "A"]
        other = FormScreen(form, Path(":memory:"), seed=43)
        assert other.choice_orders["mc"] != first.choice_orders["mc"]
        assert set(first.choice_orders["mc"]) == {"A", "B", "C", "D"}

    def test_checkbox_choice_order_shuffles_per_seed(self) -> None:
        """Checkbox options shuffle when the question opts in."""
        form = FormDefinition(
            name="CheckboxShuffle",
            questions=[
                CheckboxQuestion(
                    id="cb",
                    text="Pick all",
                    type="checkbox",
                    choices=["A", "B", "C", "D"],
                    correct_answer=["A"],
                    points=1,
                    randomize_choices=True,
                )
            ],
        )
        screen = FormScreen(form, Path(":memory:"), seed=42)
        assert screen.choice_orders["cb"] == ["C", "B", "D", "A"]
        assert set(screen.choice_orders["cb"]) == {"A", "B", "C", "D"}

    def test_compose_renders_shuffled_choices(self) -> None:
        """The composed RadioSet shows the per-session choice order."""
        form = FormDefinition(
            name="ComposedShuffle",
            questions=[
                MultipleChoiceQuestion(
                    id="mc",
                    text="Pick?",
                    type="multiple_choice",
                    choices=["A", "B", "C", "D"],
                    correct_answer="B",
                    points=1,
                    randomize_choices=True,
                )
            ],
        )

        async def run() -> None:
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"), seed=42)
                await app.push_screen(screen)
                radioset = screen.query_one(RadioSet)
                labels = [
                    str(button.label) for button in radioset.query(RadioButton)
                ]
                assert labels == screen.choice_orders["mc"]

        asyncio.run(run())

    def test_inputs_follow_shuffled_order(self) -> None:
        """Compose renders the input widgets in the shuffled order."""

        async def run() -> None:
            form = FormDefinition(
                name="Shuffled",
                config=FormConfig(randomize_questions=True),
                questions=_build_questions(SHUFFLE_QUESTION_COUNT),
            )
            app: App = App()
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
                await app.push_screen(screen)
                rendered = [w.id for w in screen.query(Input)]
                expected = [f"input-{q.id}" for q in screen.ordered_questions]
                assert rendered == expected

        asyncio.run(run())

    def test_sidebar_follows_shuffled_order(self) -> None:
        """The sidebar items appear in the shuffled order."""

        async def run() -> None:
            form = FormDefinition(
                name="Shuffled",
                config=FormConfig(randomize_questions=True),
                questions=_build_questions(SHUFFLE_QUESTION_COUNT),
            )
            app: App = App()
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
                await app.push_screen(screen)
                expected = [
                    screen._truncate(q.text) for q in screen.ordered_questions
                ]
                actual = [str(item.content) for item in screen.sidebar_items]
                assert actual == expected

        asyncio.run(run())

    def test_instances_with_same_seed_match(self) -> None:
        """Two screens with the same seed display the same order."""
        form = FormDefinition(
            name="Shuffled",
            config=FormConfig(randomize_questions=True),
            questions=_build_questions(SHUFFLE_QUESTION_COUNT),
        )
        first = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
        second = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
        assert [q.id for q in first.ordered_questions] == [
            q.id for q in second.ordered_questions
        ]

    def test_instances_with_different_seeds_differ(self) -> None:
        """Two screens with different seeds display different orders."""
        form = FormDefinition(
            name="Shuffled",
            config=FormConfig(randomize_questions=True),
            questions=_build_questions(SHUFFLE_QUESTION_COUNT),
        )
        first = FormScreen(form, Path(":memory:"), seed=1)
        second = FormScreen(form, Path(":memory:"), seed=2)
        assert [q.id for q in first.ordered_questions] != [
            q.id for q in second.ordered_questions
        ]

    def test_pinned_question_keeps_file_position(self) -> None:
        """A pinned question appears at its file index when shuffled."""
        form = FormDefinition(
            name="Pinned",
            config=FormConfig(randomize_questions=True),
            questions=_build_questions(SHUFFLE_QUESTION_COUNT),
        )
        form.questions[-1].randomize = False
        screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
        assert screen.ordered_questions[-1] is form.questions[-1]
        assert sorted(q.id for q in screen.ordered_questions) == sorted(
            q.id for q in form.questions
        )

    def test_focus_navigation_follows_shuffled_order(self) -> None:
        """Ctrl+N moves focus to the next question in the shuffled order."""

        async def run() -> None:
            form = FormDefinition(
                name="Shuffled",
                config=FormConfig(randomize_questions=True),
                questions=_build_questions(SHUFFLE_QUESTION_COUNT),
            )
            app: App = App()
            async with app.run_test() as pilot:
                screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
                await app.push_screen(screen)
                await pilot.press("ctrl+n")
                assert screen.focused is not None
                expected = screen.ordered_questions[1].id
                assert screen.focused.id == f"input-{expected}"

        asyncio.run(run())

    def test_submit_collects_all_questions_in_shuffled_order(self) -> None:
        """Submit gathers every question once in the displayed order."""

        async def run() -> None:
            form = FormDefinition(
                name="Shuffled",
                config=FormConfig(randomize_questions=True),
                questions=_build_questions(SHUFFLE_QUESTION_COUNT),
            )
            app: App = App()
            setattr(app, "attempt_id", "attempt-shuffled")
            async with app.run_test():
                screen = FormScreen(form, Path(":memory:"), seed=SHUFFLE_SEED)
                await app.push_screen(screen)
                with patch.object(app, "push_screen"):
                    with patch("formtuist.tui.screens.init_db"):
                        with patch(
                            "formtuist.tui.screens.save_response"
                        ) as mock_save:
                            await screen.action_submit()
                answers = mock_save.call_args[0][2]
                assert sorted(answers) == sorted(q.id for q in form.questions)
                assert list(answers) == [
                    q.id for q in screen.ordered_questions
                ]

        asyncio.run(run())


class TestWidgetFactory:
    """Tests for the widget factory functions."""

    def test_make_short_text_input(self) -> None:
        """make_input_widget creates an Input for short_text."""
        q = ShortTextQuestion(id="t", text="T", type="short_text")
        widget = make_input_widget(q)
        assert isinstance(widget, Input)

    def test_make_paragraph_input(self) -> None:
        """make_input_widget creates a TextArea for paragraph."""
        q = ParagraphQuestion(id="t", text="T", type="paragraph")
        widget = make_input_widget(q)
        assert isinstance(widget, TextArea)

    def test_make_multiple_choice_input(self) -> None:
        """make_input_widget creates a RadioSet for multiple_choice."""
        q = MultipleChoiceQuestion(
            id="t", text="T", type="multiple_choice", choices=["A", "B"]
        )
        widget = make_input_widget(q)
        assert isinstance(widget, RadioSet)

    def test_make_multiple_choice_with_choice_order(self) -> None:
        """make_input_widget honors an explicit choice order."""
        q = MultipleChoiceQuestion(
            id="t", text="T", type="multiple_choice", choices=["A", "B"]
        )
        widget = make_input_widget(q, choices=["B", "A"])
        assert isinstance(widget, RadioSet)

    def test_make_checkbox_input(self) -> None:
        """make_input_widget creates a SelectionList for checkbox."""
        q = CheckboxQuestion(
            id="t", text="T", type="checkbox", choices=["A", "B"]
        )
        widget = make_input_widget(q)
        assert isinstance(widget, SelectionList)

    def test_make_numeric_input(self) -> None:
        """make_input_widget creates an Input for numeric."""
        q = NumericQuestion(id="t", text="T", type="numeric")
        widget = make_input_widget(q)
        assert isinstance(widget, Input)

    def test_make_rating_input(self) -> None:
        """make_input_widget creates a RadioSet for rating."""
        q = RatingQuestion(
            id="t",
            text="T",
            type="rating",
            min=1,
            max=5,
            labels=["Bad", "Good"],
        )
        widget = make_input_widget(q)
        assert isinstance(widget, RadioSet)

    def test_make_date_input(self) -> None:
        """make_input_widget creates a DatePicker for date."""
        q = DateQuestion(id="t", text="T", type="date")
        widget = make_input_widget(q)
        assert isinstance(widget, DatePickerField)
        assert isinstance(widget, DatePicker)

    def test_make_yes_no_input(self) -> None:
        """make_input_widget creates a Switch for yes_no."""
        q = YesNoQuestion(id="t", text="T", type="yes_no")
        widget = make_input_widget(q)
        assert isinstance(widget, Switch)

    def test_make_unknown_type_raises(self) -> None:
        """make_input_widget raises ValueError for unknown types."""
        q = ShortTextQuestion.model_construct(
            id="t",
            text="T",
            type="slider",  # type: ignore[arg-type]
        )
        with pytest.raises(ValueError, match="slider"):
            make_input_widget(q)

    def test_get_widget_value_input(self) -> None:
        """get_widget_value returns Input.value."""
        mock = MagicMock(spec=Input)
        mock.value = "hello"
        assert get_widget_value(mock) == "hello"

    def test_get_widget_value_text_area(self) -> None:
        """get_widget_value returns TextArea.text."""
        mock = MagicMock(spec=TextArea)
        mock.text = "paragraph"
        assert get_widget_value(mock) == "paragraph"

    def test_get_widget_value_radio_set(self) -> None:
        """get_widget_value returns RadioSet pressed label."""
        mock = MagicMock(spec=RadioSet)
        mock.pressed_button.label = "Option A"
        assert get_widget_value(mock) == "Option A"

    def test_get_widget_value_radio_set_none(self) -> None:
        """get_widget_value returns None when no button pressed."""
        mock = MagicMock(spec=RadioSet)
        mock.pressed_button = None
        assert get_widget_value(mock) is None

    def test_get_widget_value_selection_list(self) -> None:
        """get_widget_value returns list of selected values."""
        mock = MagicMock(spec=SelectionList)
        mock.selected = ["a", "b"]
        assert get_widget_value(mock) == ["a", "b"]

    def test_get_widget_value_switch(self) -> None:
        """get_widget_value returns Switch.value."""
        mock = MagicMock(spec=Switch)
        mock.value = True
        assert get_widget_value(mock) is True
        mock.value = False
        assert get_widget_value(mock) is False

    def test_get_widget_value_date_picker(self) -> None:
        """get_widget_value returns the ISO date from a DatePicker."""
        picker = DatePicker(Date(2023, 5, 1))
        assert get_widget_value(picker) == "2023-05-01"
        picker.value = Date(2024, 2, 29)
        assert get_widget_value(picker) == "2024-02-29"

    def test_get_widget_value_date_picker_empty(self) -> None:
        """get_widget_value returns None for an empty DatePicker."""
        picker = DatePicker()
        assert get_widget_value(picker) is None

    def test_get_widget_value_unknown(self) -> None:
        """get_widget_value returns None for unknown widget types."""
        mock = MagicMock()
        assert get_widget_value(mock) is None

    def test_is_widget_empty_input(self) -> None:
        """is_widget_empty checks for blank Input."""
        empty = MagicMock(spec=Input)
        empty.value = ""
        assert is_widget_empty(empty)
        filled = MagicMock(spec=Input)
        filled.value = "text"
        assert not is_widget_empty(filled)

    def test_is_widget_empty_text_area(self) -> None:
        """is_widget_empty checks for blank TextArea."""
        empty = MagicMock(spec=TextArea)
        empty.text = ""
        assert is_widget_empty(empty)

    def test_is_widget_empty_radio_set(self) -> None:
        """is_widget_empty checks for unpressed RadioSet."""
        empty = MagicMock(spec=RadioSet)
        empty.pressed_button = None
        assert is_widget_empty(empty)

    def test_is_widget_empty_selection_list(self) -> None:
        """is_widget_empty checks for empty SelectionList."""
        empty = MagicMock(spec=SelectionList)
        empty.selected = []
        assert is_widget_empty(empty)

    def test_is_widget_empty_switch(self) -> None:
        """is_widget_empty always returns False for Switch."""
        s = MagicMock(spec=Switch)
        assert not is_widget_empty(s)

    def test_is_widget_empty_date_picker(self) -> None:
        """is_widget_empty reports an unset DatePicker as empty."""
        empty = DatePicker()
        assert is_widget_empty(empty)
        filled = DatePicker(Date(2023, 5, 1))
        assert not is_widget_empty(filled)

    def test_is_widget_empty_unknown(self) -> None:
        """is_widget_empty returns True for unknown widget types."""
        assert is_widget_empty(MagicMock())

    def test_make_code_widget_with_code(self) -> None:
        """make_code_widget returns a Static for questions with code."""
        q = ShortTextQuestion(
            id="t",
            text="T",
            type="short_text",
            code=CodeBlock(language="python", content="x = 1"),
        )
        result = make_code_widget(q)
        assert isinstance(result, Static)

    def test_make_code_widget_without_code(self) -> None:
        """make_code_widget returns None for questions without code."""
        q = ShortTextQuestion(id="t", text="T", type="short_text")
        assert make_code_widget(q) is None

    def test_is_widget_valid_input_valid(self) -> None:
        """is_widget_valid returns True for valid Input."""
        mock = MagicMock(spec=Input)
        mock.is_valid = True
        assert is_widget_valid(mock) is True

    def test_is_widget_valid_input_invalid(self) -> None:
        """is_widget_valid returns False for invalid Input."""
        mock = MagicMock(spec=Input)
        mock.is_valid = False
        assert is_widget_valid(mock) is False

    def test_is_widget_valid_non_input(self) -> None:
        """is_widget_valid returns True for non-Input widgets."""
        mock = MagicMock(spec=Switch)
        assert is_widget_valid(mock) is True


class TestResolveCodeTheme:
    """Tests for resolving Textual app themes to Pygments syntax themes."""

    def test_resolve_mapped_dark_theme(self) -> None:
        """resolve_code_theme returns the mapped Pygments theme."""
        app = MagicMock()
        app.theme = "dracula"
        app.current_theme.dark = True
        assert resolve_code_theme(app) == "dracula"

    def test_resolve_mapped_light_theme(self) -> None:
        """resolve_code_theme returns the mapped light Pygments theme."""
        app = MagicMock()
        app.theme = "solarized-light"
        app.current_theme.dark = False
        assert resolve_code_theme(app) == "solarized-light"

    def test_resolve_unknown_direct_pygments_match(self) -> None:
        """resolve_code_theme uses the Textual name if it is a Pygments style."""
        app = MagicMock()
        app.theme = "github-dark"
        app.current_theme.dark = True
        assert resolve_code_theme(app) == "github-dark"

    def test_resolve_unknown_dark_fallback(self) -> None:
        """resolve_code_theme falls back to the dark theme."""
        app = MagicMock()
        app.theme = "no-such-theme"
        app.current_theme.dark = True
        assert resolve_code_theme(app) == "ansi_dark"

    def test_resolve_unknown_light_fallback(self) -> None:
        """resolve_code_theme falls back to the light theme."""
        app = MagicMock()
        app.theme = "no-such-theme"
        app.current_theme.dark = False
        assert resolve_code_theme(app) == "ansi_light"

    def test_resolve_class_not_found_fallback(self) -> None:
        """resolve_code_theme falls back when Pygments raises ClassNotFound."""
        app = MagicMock()
        app.theme = "custom-theme"
        app.current_theme.dark = True
        with patch(
            "formtuist.tui.widgets.get_style_by_name",
            side_effect=ClassNotFound("custom-theme"),
        ):
            assert resolve_code_theme(app) == "ansi_dark"


class TestSubmitScreen:
    """Tests for the submit screen construction."""

    def test_construct(self) -> None:
        """SubmitScreen can be constructed with a form and db path."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        assert screen.db_path == Path("/tmp/test.db")
        assert screen.form is form

    def test_compose_yields_widgets(self) -> None:
        """SubmitScreen compose produces at least 3 children."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        assert len(children) >= MIN_SUBMIT_CHILDREN

    def test_compose_shows_db_path(self) -> None:
        """SubmitScreen includes the database path in the output."""
        db_path = Path("/custom/path/responses.db")
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, db_path)
        children = list(screen.compose())
        texts = [str(c.content) for c in children if hasattr(c, "content")]
        # compare against str(db_path) because Windows renders backslashes
        assert any(str(db_path) in t for t in texts)

    def test_compose_shows_tip(self) -> None:
        """SubmitScreen includes the command palette tip."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        texts = [str(c.content) for c in children if hasattr(c, "content")]
        assert any("Ctrl+O" in t for t in texts)

    def test_compose_shows_identity(self) -> None:
        """SubmitScreen displays the authenticated identity when present."""
        form = FormDefinition(name="Test", questions=[])
        identity = GitHubIdentity(
            username="octocat",
            profile_url="https://github.com/octocat",
        )
        screen = SubmitScreen(form, Path("/tmp/test.db"), identity)
        children = list(screen.compose())
        texts = [str(c.content) for c in children if hasattr(c, "content")]
        assert any("octocat" in t for t in texts)
        assert any("github.com/octocat" in t for t in texts)

    def test_compose_omits_identity_when_none(self) -> None:
        """SubmitScreen does not show identity when auth is disabled."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        texts = [str(c.content) for c in children if hasattr(c, "content")]
        assert not any("Authenticated as" in t for t in texts)

    def test_on_button_pressed_restart(self) -> None:
        """Pressing restart pushes a new FormScreen."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        mock_app = MagicMock()
        with patch.object(
            SubmitScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            button = MagicMock()
            button.id = "restart"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_app.push_screen.assert_called_once()

    def test_on_button_pressed_quit(self) -> None:
        """Pressing quit exits the application."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        mock_app = MagicMock()
        with patch.object(
            SubmitScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            button = MagicMock()
            button.id = "quit"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_app.exit.assert_called_once()

    def test_on_button_pressed_other(self) -> None:
        """Pressing a non-action button does nothing."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        mock_app = MagicMock()
        with patch.object(
            SubmitScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            button = MagicMock()
            button.id = "other"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_app.push_screen.assert_not_called()
        mock_app.exit.assert_not_called()

    def test_action_restart(self) -> None:
        """action_restart pushes a new FormScreen."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        mock_app = MagicMock()
        with patch.object(
            SubmitScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            screen.action_restart()
        mock_app.push_screen.assert_called_once()

    def test_action_restart_blocked_when_single_submission(self) -> None:
        """action_restart refuses for single-submission forms."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[],
        )
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        mock_app = MagicMock()
        with patch.object(
            SubmitScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(SubmitScreen, "notify") as mock_notify:
                screen.action_restart()
        mock_app.push_screen.assert_not_called()
        mock_notify.assert_called_once()

    def test_compose_omits_restart_when_single_submission(self) -> None:
        """The Restart button is omitted for single-submission forms."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[],
        )
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        ids = [child.id for child in children if hasattr(child, "id")]
        assert "restart" not in ids

    def test_compose_shows_single_submission_note(self) -> None:
        """A note explains the single-submission policy."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[],
        )
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        texts = [str(c.content) for c in children if hasattr(c, "content")]
        assert any(SINGLE_SUBMISSION_NOTE in t for t in texts)

    def test_compose_includes_restart_when_multiple(self) -> None:
        """The Restart button is present when resubmission is allowed."""
        form = FormDefinition(name="Poll", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        ids = [child.id for child in children if hasattr(child, "id")]
        assert "restart" in ids

    def test_check_action_hides_restart_when_single(self) -> None:
        """The restart action is disabled for single-submission forms."""
        form = FormDefinition(
            name="Quiz",
            config=FormConfig(
                auth=AuthProvider.GITHUB,
                allow_multiple_submissions=False,
            ),
            questions=[],
        )
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        assert screen.check_action("restart", ()) is False

    def test_check_action_allows_restart_when_multiple(self) -> None:
        """The restart action is enabled when resubmission is allowed."""
        form = FormDefinition(name="Poll", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        assert screen.check_action("restart", ()) is not False

    def test_review_long_question_wraps(self) -> None:
        """The grade review wraps long question text."""

        async def run() -> None:
            form = FormDefinition(
                name="Q",
                questions=[
                    ShortTextQuestion(
                        id="a",
                        text=("A very long question " * 12).strip(),
                        type="short_text",
                        correct_answer="answer",
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                ],
            )
            report = grade_response(form, {"a": "wrong"})
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test() as pilot:
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                await pilot.pause()
                review = screen.query_one("#grade-review")
                review_static = next(
                    w
                    for w in screen.query(Static)
                    if "very long" in str(w.content)
                )
                assert review_static.size.width <= review.content_size.width
                assert review_static.size.height > 1

        asyncio.run(run())

    def test_compose_omits_review_without_report(self) -> None:
        """SubmitScreen shows no review when grading is disabled."""
        form = FormDefinition(name="Test", questions=[])
        screen = SubmitScreen(form, Path("/tmp/test.db"))
        children = list(screen.compose())
        texts = [str(c.content) for c in children if hasattr(c, "content")]
        assert not any("Incorrect answers" in t for t in texts)
        assert not any("Score:" in t for t in texts)

    def test_compose_shows_wrong_answers(self) -> None:
        """SubmitScreen lists wrong questions with correct answers."""

        async def run() -> None:
            form = FormDefinition(
                name="Quiz",
                questions=[
                    ShortTextQuestion(
                        id="a",
                        text="Capital of France?",
                        type="short_text",
                        correct_answer="Paris",
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                    ShortTextQuestion(
                        id="b",
                        text="Capital of Italy?",
                        type="short_text",
                        correct_answer="Rome",
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                ],
            )
            report = grade_response(form, {"a": "Paris", "b": "London"})
            app: App = App()
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                rendered = " ".join(
                    str(s.content) for s in screen.query(Static)
                )
                assert "Score: 10 / 20 (50%)" in rendered
                assert "Incorrect answers" in rendered
                assert "Capital of Italy?" in rendered
                assert "Your answer: London" in rendered
                assert "Correct answer: Rome" in rendered
                assert "Capital of France?" not in rendered

        asyncio.run(run())

    def test_compose_separates_pending_manual_review(self) -> None:
        """SubmitScreen shows pending questions and their point value."""

        async def run() -> None:
            form = FormDefinition(
                name="Quiz",
                questions=[
                    ShortTextQuestion(
                        id="wrong",
                        text="Automatically graded?",
                        type="short_text",
                        correct_answer="yes",
                        points=5,
                        grading_type="exact",
                    ),
                    ShortTextQuestion(
                        id="permitted",
                        text="Permitted review?",
                        type="short_text",
                        correct_answer="yes",
                        points=5,
                        grading_type="exact",
                        review="permitted",
                    ),
                    ParagraphQuestion(
                        id="manual_one",
                        text="Explain one.",
                        type="paragraph",
                        points=20,
                        review="required",
                    ),
                    ParagraphQuestion(
                        id="manual_two",
                        text="Explain two.",
                        type="paragraph",
                        points=20,
                        review="required",
                    ),
                ],
            )
            report = grade_response(
                form,
                {
                    "wrong": "no",
                    "permitted": "no",
                    "manual_one": "first response",
                    "manual_two": "second response",
                },
            )
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                rendered = " ".join(
                    str(s.content) for s in screen.query(Static)
                )
                assert "Preliminary score: 0 / 50" in rendered
                assert "Pending manual review" in rendered
                assert "2 questions (up to 40 points)" in rendered
                assert "Incorrect answers" in rendered
                assert "Automatically graded?" in rendered
                assert "Correct answer: yes" in rendered
                assert "Review mode: permitted" in rendered
                assert "Correct answer: (no answer)" not in rendered
                assert "Explain one." in rendered
                assert "Explain two." in rendered

        asyncio.run(run())

    def test_compose_shows_all_correct_message(self) -> None:
        """SubmitScreen celebrates when every answer is correct."""

        async def run() -> None:
            form = FormDefinition(
                name="Quiz",
                questions=[
                    ShortTextQuestion(
                        id="a",
                        text="Capital of France?",
                        type="short_text",
                        correct_answer="Paris",
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                ],
            )
            report = grade_response(form, {"a": "Paris"})
            app: App = App()
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                rendered = " ".join(
                    str(s.content) for s in screen.query(Static)
                )
                assert "All answers correct!" in rendered
                assert "Correct answer:" not in rendered

        asyncio.run(run())

    def test_review_uses_thin_scrollbar(self) -> None:
        """The grade review uses a thin vertical scrollbar."""

        async def run() -> None:
            form = FormDefinition(
                name="Q",
                questions=[
                    ShortTextQuestion(
                        id="a",
                        text="Capital of France?",
                        type="short_text",
                        correct_answer="Paris",
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                ],
            )
            report = grade_response(form, {"a": "London"})
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test() as pilot:
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                await pilot.pause()
                review = screen.query_one("#grade-review")
                assert review.styles.scrollbar_size_vertical == 1
                assert screen.styles.scrollbar_size_vertical == 1

        asyncio.run(run())

    def test_compose_highlights_code_answers(self) -> None:
        """Code-question answers render highlighted with no blank line."""

        async def run() -> None:
            form = FormDefinition(
                name="Q",
                questions=[
                    ShortTextQuestion(
                        id="a",
                        text="What is the output?",
                        type="short_text",
                        correct_answer="[0, 1]",
                        points=GRADE_POINTS,
                        grading_type="exact",
                        code=CodeBlock(
                            language="python", content="print([0, 1])\n"
                        ),
                    ),
                ],
            )
            report = grade_response(form, {"a": "wrong"})
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                syntaxes = [
                    s.content
                    for s in screen.query(Static)
                    if isinstance(s.content, Syntax)
                ]
                codes = [syntax.code for syntax in syntaxes]
                assert "[0, 1]" in codes
                assert "wrong" in codes
                assert all(not code.endswith("\n") for code in codes)

        asyncio.run(run())

    def test_compose_handles_no_graded_questions(self) -> None:
        """SubmitScreen notes when the form has no graded questions."""

        async def run() -> None:
            form = FormDefinition(
                name="Plain",
                questions=[
                    RatingQuestion(
                        id="r",
                        text="Rate?",
                        type="rating",
                        min=1,
                        max=5,
                        labels=["1", "2", "3", "4", "5"],
                    ),
                ],
            )
            report = grade_response(form, {"r": 3})
            app: App = App()
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                rendered = " ".join(
                    str(s.content) for s in screen.query(Static)
                )
                assert "no auto-graded questions" in rendered

        asyncio.run(run())

    def test_compose_shows_plain_list_answers(self) -> None:
        """Checkbox answers render as plain text, not code blocks."""

        async def run() -> None:
            form = FormDefinition(
                name="Q",
                questions=[
                    CheckboxQuestion(
                        id="a",
                        text="Immutable?",
                        type="checkbox",
                        choices=["list", "tuple", "str"],
                        correct_answer=["tuple", "str"],
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                ],
            )
            report = grade_response(form, {"a": ["list"]})
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                rendered = " ".join(
                    str(s.content) for s in screen.query(Static)
                )
                assert "Correct answer: tuple, str" in rendered
                assert "Correct answers:" not in rendered

        asyncio.run(run())

    def test_compose_shows_range_answer(self) -> None:
        """Numeric range answers render as a readable range."""

        async def run() -> None:
            form = FormDefinition(
                name="Q",
                questions=[
                    NumericQuestion(
                        id="a",
                        text="Depth?",
                        type="numeric",
                        correct_answer=NumericRange(min=990, max=1010),
                        points=GRADE_POINTS,
                        grading_type="exact",
                    ),
                ],
            )
            report = grade_response(form, {"a": "500"})
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                screen = SubmitScreen(
                    form, Path("/tmp/test.db"), grade_report=report
                )
                await app.push_screen(screen)
                rendered = " ".join(
                    str(s.content) for s in screen.query(Static)
                )
                assert "Correct answer: between 990 and 1010" in rendered

        asyncio.run(run())


class TestProvenanceScreen:
    """Tests for the read-only provenance screen."""

    def test_list_and_detail_views(self, tmp_path: Path) -> None:
        """The provenance screen lists and renders stored responses."""
        db_path = tmp_path / "responses.db"
        source_path = tmp_path / "quiz.json"
        contents = '{"name":"Quiz","version":"1.0.0"}\n'
        source_path.write_text(contents, encoding="utf-8")
        conn = init_db(db_path)
        first_id = save_response(
            conn,
            "Quiz",
            {"q1": "first"},
            form_version="1.0.0",
            form_hash="abcdef1234567890",
            form_path=str(source_path.resolve()),
            form_contents=contents,
        )
        save_response(conn, "Quiz", {"q1": "second"})
        conn.close()

        async def run() -> None:
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                screen = ProvenanceScreen(db_path)
                await app.push_screen(screen)
                assert len(screen.list_items) == PROVENANCE_RESPONSE_COUNT
                assert screen.current_index == 0
                screen.action_open_detail()
                detail = screen.query_one("#provenance-detail-content", Static)
                assert "Response ID: 1" in str(detail.render())
                assert "SHA-256: abcdef1234567890" in str(detail.render())
                assert contents in str(detail.render())
                screen.action_next_response()
                assert screen.current_index == 1
                screen.action_back_to_list()
                assert "Select a response" in str(detail.render())

        asyncio.run(run())
        assert first_id == 1

    def test_scroll_detail_with_ctrl_j_and_ctrl_k(
        self, tmp_path: Path
    ) -> None:
        """The provenance detail scrolls a fixed number of lines."""
        db_path = tmp_path / "responses.db"
        long_contents = "\n".join(
            f'{{"line": {index}}}' for index in range(80)
        )
        conn = init_db(db_path)
        save_response(
            conn,
            "Quiz",
            {"q1": "x"},
            form_version="1.0.0",
            form_hash="abcdef1234567890",
            form_path=str((tmp_path / "quiz.json").resolve()),
            form_contents=long_contents,
        )
        conn.close()

        async def run() -> None:
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test() as pilot:
                screen = ProvenanceScreen(db_path)
                await app.push_screen(screen)
                screen.action_open_detail()
                await pilot.pause()
                detail = screen.query_one("#provenance-detail", VerticalScroll)
                assert detail.scroll_offset.y == 0
                await pilot.press("ctrl+j")
                await pilot.pause()
                assert detail.scroll_offset.y == PROVENANCE_SCROLL_LINES
                await pilot.press("ctrl+k")
                await pilot.pause()
                assert detail.scroll_offset.y == 0
                await pilot.press("ctrl+j")
                await pilot.pause()
                assert detail.scroll_offset.y == PROVENANCE_SCROLL_LINES
                screen.action_next_response()
                await pilot.pause()
                assert detail.scroll_offset.y == 0

        asyncio.run(run())

    def test_latest_and_direct_response_views(self, tmp_path: Path) -> None:
        """Latest and direct views select the intended response."""
        db_path = tmp_path / "responses.db"
        conn = init_db(db_path)
        save_response(conn, "Quiz", {"q1": "first"})
        second_id = save_response(conn, "Quiz", {"q1": "second"})
        conn.close()

        async def run() -> None:
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                latest = ProvenanceScreen(db_path, initial_view="latest")
                await app.push_screen(latest)
                assert latest.current_index == 1
                assert latest.detail_mode is True
                assert "Response ID: 2" in str(
                    latest.query_one(
                        "#provenance-detail-content", Static
                    ).render()
                )
                await app.pop_screen()
                direct = ProvenanceScreen(
                    db_path, initial_view="response", response_id=second_id
                )
                await app.push_screen(direct)
                assert direct.current_index == 1
                assert direct.detail_mode is True

        asyncio.run(run())

    def test_legacy_and_empty_views(self, tmp_path: Path) -> None:
        """Legacy and empty databases render clear provenance states."""
        empty_db = tmp_path / "empty.db"
        init_db(empty_db).close()
        legacy_db = tmp_path / "legacy.db"
        conn = init_db(legacy_db)
        save_response(conn, "Old", {"q": "answer"})
        conn.close()

        async def run() -> None:
            app: App = App(css_path=STYLESHEET_PATH)
            async with app.run_test():
                empty = ProvenanceScreen(empty_db)
                await app.push_screen(empty)
                assert "No responses" in str(
                    empty.query_one(
                        "#provenance-detail-content", Static
                    ).render()
                )
                await app.pop_screen()
                legacy = ProvenanceScreen(
                    legacy_db, initial_view="response", response_id=1
                )
                await app.push_screen(legacy)
                rendered = str(
                    legacy.query_one(
                        "#provenance-detail-content", Static
                    ).render()
                )
                assert "legacy response" in rendered
                assert "Source available: no" in rendered
                await app.pop_screen()

        asyncio.run(run())

    def test_provenance_app_starts(self, tmp_path: Path) -> None:
        """ProvenanceApp stores its initial view and response selection."""
        db_path = tmp_path / "responses.db"
        init_db(db_path).close()
        app = ProvenanceApp(
            db_path,
            initial_view="latest",
            response_id=PROVENANCE_RESPONSE_ID,
        )
        assert app.db_path == db_path
        assert app.initial_view == "latest"
        assert app.response_id == PROVENANCE_RESPONSE_ID

    def test_provenance_app_mounts_screen(self, tmp_path: Path) -> None:
        """ProvenanceApp pushes its screen with the selected response."""
        db_path = tmp_path / "responses.db"
        init_db(db_path).close()
        app = ProvenanceApp(
            db_path,
            initial_view="response",
            response_id=PROVENANCE_RESPONSE_ID,
        )
        with patch.object(app, "push_screen") as mock_push_screen:
            app.on_mount()
        screen = mock_push_screen.call_args.args[0]
        assert isinstance(screen, ProvenanceScreen)
        assert screen.initial_view == "response"
        assert screen.current_index == 0
        screen.on_unmount()


class TestFormtuistApp:
    """Tests for the main application class."""

    def test_construct(self, minimal_form_path: Path) -> None:
        """FormtuistApp stores form path and parses the form."""
        db_path = Path(":memory:")
        app = FormtuistApp(minimal_form_path, db_path)
        assert app.form_path == minimal_form_path
        assert app.db_path == db_path
        assert app.form.name is not None

    def test_on_mount(self, minimal_form_path: Path) -> None:
        """on_mount pushes the welcome screen."""
        db_path = Path(":memory:")
        tui_app = FormtuistApp(minimal_form_path, db_path)
        with patch.object(tui_app, "push_screen") as mock_push_screen:
            tui_app.on_mount()
        mock_push_screen.assert_called_once()

    def test_form_provenance_is_loaded_and_passed_to_screen(
        self, tmp_path: Path
    ) -> None:
        """FormtuistApp passes exact source provenance to FormScreen."""
        raw = b'{\n  "name": "Versioned",\n  "version": "v1",\n'
        raw += b'  "questions": []\n}\n'
        form_path = tmp_path / "versioned.json"
        form_path.write_bytes(raw)
        tui_app = FormtuistApp(form_path, tmp_path / "responses.db")
        with patch.object(tui_app, "push_screen") as mock_push_screen:
            tui_app.on_mount()
        screen = mock_push_screen.call_args.args[0]
        assert screen.form.version == "v1"
        assert screen.form_hash == hashlib.sha256(raw).hexdigest()
        assert screen.form_source_path == form_path.resolve()
        assert screen.form_contents == raw.decode("utf-8")

    def test_footer_orders_navigation_keys_together(self) -> None:
        """The custom footer shows Ctrl+N and Ctrl+P adjacent."""

        async def run() -> None:
            app = FormtuistApp(Path("examples/minimal.json"), Path(":memory:"))
            async with app.run_test():
                footer = app.screen.query_one(Footer)
                actions = [
                    str(getattr(child, "action", ""))
                    for child in footer.children
                ]
                assert "focus_next" in actions
                assert "focus_previous" in actions
                next_idx = actions.index("focus_next")
                prev_idx = actions.index("focus_previous")
                assert abs(next_idx - prev_idx) == 1

        asyncio.run(run())

    def test_footer_keeps_command_palette_last(self) -> None:
        """The command palette binding stays at the end of the footer."""

        async def run() -> None:
            app = FormtuistApp(Path("examples/minimal.json"), Path(":memory:"))
            async with app.run_test():
                footer = app.screen.query_one(Footer)
                actions = [
                    str(getattr(child, "action", ""))
                    for child in footer.children
                ]
                assert actions[-1] == "command_palette"

        asyncio.run(run())
