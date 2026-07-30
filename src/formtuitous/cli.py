"""Typer-based CLI entry point for the formtuitous application."""

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.rule import Rule

from formtuitous.database import resolve_db_path
from formtuitous.parser import parse_form

# rich console for all user-facing output
console = Console()

# constants for rule styling and output labels
RULE_STYLE = "dim"
LABEL_FORM = "[bold]Form:[/bold]"
LABEL_DESCRIPTION = "[bold]Description:[/bold]"
LABEL_QUESTIONS = "[bold]Questions:[/bold]"
LABEL_GRADED = "[bold]Graded:[/bold]"
LABEL_GRADED_NONE = "[bold]Graded:[/bold] none"
LABEL_STATUS = "[bold]Status:[/bold] [green]valid[/green]"
GRADE_STATUS_ON = "on"
GRADE_STATUS_OFF = "off"
GRADED_SUFFIX = " question(s)"
AUTO_GRADE_PREFIX = " (auto-grade is "
AUTO_GRADE_SUFFIX = ")"
QUESTIONS_SEPARATOR = " required, "
QUESTIONS_SUFFIX = " optional)"

# constants for shared typer argument help strings
FORM_PATH_HELP = "Path to a JSON form definition file."
RESPONSES_PATH_HELP = "Path to a responses SQLite database."
APP_HELP = "Creating forms with JSON and a TUI is an unexpected success!"

app = typer.Typer(
    name="formtuitous",
    help=APP_HELP,
)


@app.command()
def check(
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Validate a form JSON file and print a summary."""
    # attempt to parse and validate the form; exit on failure
    try:
        form = parse_form(form_path)
    except ValidationError:
        raise typer.Exit(code=1)
    # count questions by required status and grading presence
    total = len(form.questions)
    required_count = sum(1 for q in form.questions if q.required)
    optional_count = total - required_count
    graded_count = sum(
        1
        for q in form.questions
        if getattr(q, "correct_answer", None) is not None
    )
    auto_grade = form.config.auto_grade
    # print a labelled summary with rich markup
    console.print(Rule(style=RULE_STYLE))
    console.print(f"{LABEL_FORM} {form.name}")
    if form.description:
        console.print(f"{LABEL_DESCRIPTION} {form.description}")
    console.print(
        f"{LABEL_QUESTIONS} {total}"
        f" ({required_count}{QUESTIONS_SEPARATOR}"
        f"{optional_count}{QUESTIONS_SUFFIX}"
    )
    if graded_count > 0:
        grade_status = GRADE_STATUS_ON if auto_grade else GRADE_STATUS_OFF
        console.print(
            f"{LABEL_GRADED} {graded_count}{GRADED_SUFFIX}"
            f"{AUTO_GRADE_PREFIX}{grade_status}{AUTO_GRADE_SUFFIX}"
        )
    else:
        console.print(LABEL_GRADED_NONE)
    console.print(LABEL_STATUS)
    console.print(Rule(style=RULE_STYLE))
    raise typer.Exit(code=0)


DB_DIR_HELP = "Directory for the responses database (default: platformdirs user_data_dir)."


@app.command()
def display(
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    db_dir: Path = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Display a form in the TUI and collect responses."""
    # imported here to avoid loading Textual unless needed
    from formtuitous.tui.app import FormtuitousApp  # noqa: PLC0415

    # validate the form before launching the TUI
    try:
        parse_form(form_path)
    except ValidationError:
        raise typer.Exit(code=1)
    db_path = resolve_db_path(db_dir)
    app_ui = FormtuitousApp(form_path, db_path)
    app_ui.run()


@app.command()
def serve(
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Serve a form as a web application via textual-serve."""
    raise typer.Exit(code=0)


@app.command()
def export(
    responses_path: Path = typer.Argument(
        ...,
        help=RESPONSES_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Export responses to CSV, JSON, or SQLite format."""
    raise typer.Exit(code=0)


@app.command()
def view(
    responses_path: Path = typer.Argument(
        ...,
        help=RESPONSES_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """View responses in a web browser via datasette."""
    raise typer.Exit(code=0)


@app.command()
def grade(
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    responses_path: Path = typer.Argument(
        ...,
        help=RESPONSES_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Grade responses against a form with correct answers."""
    raise typer.Exit(code=0)


def main() -> None:
    """Entry point for the formtuitous CLI."""
    app()
