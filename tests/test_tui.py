"""Smoke tests for TUI screens and application construction."""

from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

from formtuitous.schema import FormDefinition, ShortTextQuestion
from formtuitous.tui.app import FormtuitousApp
from formtuitous.tui.screens import FormScreen, SubmitScreen, WelcomeScreen

MIN_WELCOME_CHILDREN = 3
MIN_SUBMIT_CHILDREN = 3


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
        with patch.object(FormScreen, "action_submit") as mock_action:
            button = MagicMock()
            button.id = "submit"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_action.assert_called_once()

    def test_on_button_pressed_other(
        self, minimal_form: FormDefinition
    ) -> None:
        """Pressing a non-submit button does nothing."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        with patch.object(FormScreen, "action_submit") as mock_action:
            button = MagicMock()
            button.id = "other"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_action.assert_not_called()

    def test_action_submit_valid(self, minimal_form: FormDefinition) -> None:
        """action_submit saves valid answers and pushes submit screen."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock()
        mock_input.value = "Alice"
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuitous.tui.screens.init_db") as mock_init:
                    with patch(
                        "formtuitous.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        screen.action_submit()
        mock_init.assert_called_once()
        mock_save.assert_called_once_with(
            mock_init.return_value, "Minimal", {"q1": "Alice"}
        )
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()

    def test_action_submit_missing_required(
        self, minimal_form: FormDefinition
    ) -> None:
        """action_submit notifies when required fields are empty."""
        screen = FormScreen(minimal_form, Path(":memory:"))
        mock_app = MagicMock()
        mock_input = MagicMock()
        mock_input.value = ""
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuitous.tui.screens.init_db") as mock_init:
                    screen.action_submit()
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
        mock_input = MagicMock()
        mock_input.value = ""
        screen.inputs["q1"] = mock_input
        with patch.object(
            FormScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            with patch.object(FormScreen, "notify") as mock_notify:
                with patch("formtuitous.tui.screens.init_db") as mock_init:
                    with patch(
                        "formtuitous.tui.screens.save_response"
                    ) as mock_save:
                        mock_save.return_value = 1
                        screen.action_submit()
        mock_init.assert_called_once()
        mock_save.assert_called_once_with(
            mock_init.return_value, "Test", {"q1": ""}
        )
        mock_app.push_screen.assert_called_once()
        mock_notify.assert_not_called()


class TestSubmitScreen:
    """Tests for the submit screen construction."""

    def test_construct(self) -> None:
        """SubmitScreen can be constructed."""
        screen = SubmitScreen()
        assert screen is not None

    def test_compose_yields_widgets(self) -> None:
        """SubmitScreen compose produces at least 3 children."""
        screen = SubmitScreen()
        children = list(screen.compose())
        assert len(children) >= MIN_SUBMIT_CHILDREN

    def test_on_button_pressed_exit(self) -> None:
        """Pressing exit exits the application."""
        screen = SubmitScreen()
        mock_app = MagicMock()
        with patch.object(
            SubmitScreen, "app", new_callable=PropertyMock
        ) as mock_prop:
            mock_prop.return_value = mock_app
            button = MagicMock()
            button.id = "exit"
            event = MagicMock()
            event.button = button
            screen.on_button_pressed(event)
        mock_app.exit.assert_called_once()

    def test_on_button_pressed_other(self) -> None:
        """Pressing a non-exit button does nothing."""
        screen = SubmitScreen()
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
        mock_app.exit.assert_not_called()


class TestFormtuitousApp:
    """Tests for the main application class."""

    def test_construct(self, minimal_form_path: Path) -> None:
        """FormtuitousApp stores form path and parses the form."""
        db_path = Path(":memory:")
        app = FormtuitousApp(minimal_form_path, db_path)
        assert app.form_path == minimal_form_path
        assert app.db_path == db_path
        assert app.form.name is not None

    def test_on_mount(self, minimal_form_path: Path) -> None:
        """on_mount pushes the welcome screen."""
        db_path = Path(":memory:")
        tui_app = FormtuitousApp(minimal_form_path, db_path)
        tui_app.push_screen = MagicMock()
        tui_app.on_mount()
        tui_app.push_screen.assert_called_once()
