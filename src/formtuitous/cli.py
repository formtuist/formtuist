"""Typer-based CLI entry point for the formtuitous application."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from formtuitous.database import resolve_db_path
from formtuitous.parser import parse_form
from formtuitous.version import FORMTUITOUS_VERSION

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
APP_HELP = "Creating forms with JSON and a TUI is an unexpected success for programmers and agents!"

app = typer.Typer(
    name="formtuitous",
    help=APP_HELP,
)

# main runtime dependencies shown by --version
# (note that this needs to be manually updated
# when new dependencies are added)
DEPENDENCY_NAMES = [
    "pydantic",
    "textual",
    "textual-serve",
    "rich",
    "datasette",
    "click",
    "typer",
    "platformdirs",
]

VERSION_TITLE = f"formtuitous {FORMTUITOUS_VERSION}"
COMPONENT_COLUMN = "Component"
VERSION_COLUMN = "Version"


def _package_version(package: str) -> str:
    """Return the installed version of a package, or unknown."""
    try:
        return version(package)
    except PackageNotFoundError:
        return "unknown"


def _version_callback(value: bool) -> None:
    """Print version information and exit when --version is provided."""
    if not value:
        return
    table = Table(title=VERSION_TITLE, header_style="bold")
    table.add_column(COMPONENT_COLUMN)
    table.add_column(VERSION_COLUMN)
    for name in sorted(DEPENDENCY_NAMES):
        table.add_row(name, _package_version(name))
    console.print(table)
    raise typer.Exit()


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
DB_NAME_HELP = "Name of the database file (default: responses.db)."
SERVE_HELP = "Serve the form in a web browser instead of the local TUI."
HOST_HELP = "Host address for the web server."
PORT_HELP = "Port for the web server."


@app.command()
def display(  # noqa: PLR0913, PLR0917
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
    database_name: str = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help=SERVE_HELP,
    ),
    host: str = typer.Option(
        "0.0.0.0",
        "--host",
        help=HOST_HELP,
    ),
    port: int = typer.Option(
        8000,
        "--port",
        help=PORT_HELP,
    ),
) -> None:
    """Display a form in the TUI and collect responses."""
    # validate the form before launching the TUI or server
    try:
        form = parse_form(form_path)
    except ValidationError:
        raise typer.Exit(code=1)

    db_path = resolve_db_path(db_dir, database_name)

    if serve:
        from textual_serve.server import Server  # noqa: PLC0415

        cmd = f"formtuitous display {form_path}"
        if db_dir is not None:
            cmd += f" --db-dir {db_dir}"
        if database_name is not None:
            cmd += f" --database-name {database_name}"
        server = Server(
            cmd,
            host=host,
            port=port,
            title=form.name,
        )
        console.print(
            f"Serving [bold]{form.name}[/bold] at http://{host}:{port}"
        )
        server.serve()
    else:
        from formtuitous.tui.app import FormtuitousApp  # noqa: PLC0415

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
    port: int = typer.Option(8001, "--port", help="Port for datasette."),
) -> None:
    """Browse responses in a web browser via datasette."""
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    console.print(
        f"Starting datasette for [bold]{responses_path}[/bold]"
        f" at http://127.0.0.1:{port}"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "datasette",
            "serve",
            str(responses_path),
            "--port",
            str(port),
            "--open-browser",
        ],
        check=False,
    )


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


@app.callback()
def _app_callback(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show version information and exit.",
    ),
) -> None:
    """Display help for the formtuitous command-line interface."""


def main() -> None:
    """Entry point for the formtuitous CLI."""
    app()
