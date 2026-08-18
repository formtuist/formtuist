"""Typer-based CLI entry point for the formtuist application."""

import sqlite3
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from formtuist.database import (
    ANSWERS_JSON_COLUMN,
    GITHUB_USERNAME_COLUMN,
    GRADE_JSON_COLUMN,
    ID_COLUMN,
    get_default_db_dir,
    get_responses,
    init_db,
    resolve_db_path,
    update_response_grade,
)
from formtuist.exporter import (
    export_to_csv,
    export_to_json,
    export_to_jsonl,
    export_to_sqlite,
)
from formtuist.grader import (
    BREAKDOWN_ID_KEY,
    BREAKDOWN_KEY,
    BREAKDOWN_SCORE_KEY,
    MAX_KEY,
    PERCENTAGE_KEY,
    TOTAL_KEY,
    grade_report_to_json,
    grade_response,
)
from formtuist.parser import parse_form
from formtuist.schema import FormDefinition
from formtuist.version import FORMTUIST_VERSION

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

# constants for the grade command output
GRADE_TABLE_TITLE_PREFIX = "Grades for "
GRADE_COLUMN_ID = "ID"
GRADE_COLUMN_STUDENT = "Student"
GRADE_COLUMN_TOTAL = "Total"
GRADE_COLUMN_MAX = "Max"
GRADE_COLUMN_PERCENT = "%"
GRADE_QUESTION_COLUMN_PREFIX = "Q"
GRADE_UNKNOWN_STUDENT = "-"
GRADE_NO_SCORE = "-"
GRADE_NO_RESPONSES_PREFIX = "No responses for "

# constants for shared typer argument help strings
FORM_PATH_HELP = "Path to a JSON form definition file."
RESPONSES_PATH_HELP = "Path to a responses SQLite database."
CODE_DIR_HELP = (
    "Directory that code file references are relative to "
    "(default: the form file's directory)."
)
APP_HELP = "Creating forms with JSON and a TUI is an unexpected success for programmers and agents!"

app = typer.Typer(
    name="formtuist",
    help=APP_HELP,
)

# main runtime dependencies shown by --version
# (note that this needs to be manually updated
# when new dependencies are added)
DEPENDENCY_NAMES = [
    "pydantic",
    "textual",
    "textual-serve",
    "bitbang",
    "rich",
    "datasette",
    "click",
    "typer",
    "platformdirs",
]

VERSION_TITLE = f"formtuist {FORMTUIST_VERSION}"
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
    code_dir: Path = typer.Option(
        None,
        "--code-dir",
        help=CODE_DIR_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Validate a form JSON file and print a summary."""
    # attempt to parse and validate the form; exit on failure
    try:
        form = parse_form(form_path, code_dir)
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


DB_NAME_HELP = "Name of the database file (default: responses.db)."


def _display_db_dir() -> str:
    """Return the default db directory with the home prefix shortened."""
    db_dir = get_default_db_dir()
    home = Path.home()
    try:
        return f"~/{db_dir.relative_to(home)}"
    except ValueError:
        return str(db_dir)


DB_DIR_HELP = (
    f"Directory for the responses database (default: {_display_db_dir()})."
)
HOST_HELP = "Host address for the web server."
PORT_HELP = "Port for the web server."


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
    database_name: str = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
    code_dir: Path = typer.Option(
        None,
        "--code-dir",
        help=CODE_DIR_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Display a form in the TUI and collect responses."""
    # validate the form before launching the TUI
    try:
        parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)

    db_path = resolve_db_path(db_dir, database_name)

    from formtuist.tui.app import FormtuistApp  # noqa: PLC0415

    app_ui = FormtuistApp(form_path, db_path)
    app_ui.run()


@app.command()
def serve(  # noqa: PLR0913, PLR0917
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
    code_dir: Path = typer.Option(
        None,
        "--code-dir",
        help=CODE_DIR_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Serve a form as a web application via textual-serve."""
    # validate the form before launching the server
    try:
        form = parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)

    from formtuist.server import FormtuistServer  # noqa: PLC0415

    cmd = f"formtuist display {form_path}"
    if db_dir is not None:
        cmd += f" --db-dir {db_dir}"
    if database_name is not None:
        cmd += f" --database-name {database_name}"
    if code_dir is not None:
        cmd += f" --code-dir {code_dir}"
    templates_dir = Path(__file__).parent / "templates"
    server = FormtuistServer(
        cmd,
        host=host,
        port=port,
        title=form.name,
        templates_path=templates_dir,
    )
    console.print(f"Serving [bold]{form.name}[/bold] at http://{host}:{port}")
    server.serve()


PUBLISH_HOST_HELP = "Local host address for the textual-serve server."
PUBLISH_PORT_HELP = "Local port for the textual-serve server."
PUBLISH_SIGNALING_HELP = "Bitbang signaling server hostname."
PUBLISH_PIN_HELP = "Optional PIN required from people opening the URL."
PUBLISH_EPHEMERAL_HELP = "Create a new temporary bitbang identity."
PUBLISH_START_PREFIX = "Publishing [bold]"
PUBLISH_START_SUFFIX = "[/bold] through bitbang."


@app.command()
def publish(  # noqa: PLR0913, PLR0917
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
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        help=PUBLISH_HOST_HELP,
    ),
    port: int = typer.Option(
        8000,
        "--port",
        help=PUBLISH_PORT_HELP,
    ),
    signaling: str = typer.Option(
        "bitba.ng",
        "--signaling",
        help=PUBLISH_SIGNALING_HELP,
    ),
    pin: str | None = typer.Option(
        None,
        "--pin",
        help=PUBLISH_PIN_HELP,
    ),
    ephemeral: bool = typer.Option(
        False,
        "--ephemeral",
        help=PUBLISH_EPHEMERAL_HELP,
    ),
    code_dir: Path = typer.Option(
        None,
        "--code-dir",
        help=CODE_DIR_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
) -> None:
    """Publish a form through a peer-to-peer bitbang URL."""
    try:
        form = parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)
    from formtuist.publisher import publish_form  # noqa: PLC0415

    console.print(f"{PUBLISH_START_PREFIX}{form.name}{PUBLISH_START_SUFFIX}")
    publish_form(
        form_path,
        host,
        port,
        signaling,
        pin,
        ephemeral,
        db_dir,
        database_name,
        code_dir,
    )


# constants for the export command
EXPORT_FORMAT_HELP = "Output format: csv, json, jsonl, or sqlite."
EXPORT_OUTPUT_HELP = "Path to write the exported responses."
EXPORT_FORM_NAME_HELP = "Only export responses for this form name."
EXPORT_FORMAT_DEFAULT = "csv"
EXPORT_SUCCESS_PREFIX = "Exported "
EXPORT_SUCCESS_SUFFIX = " response(s) to "
EXPORT_NO_RESPONSES = "No responses to export."


@app.command()
def export(
    responses_path: Path = typer.Argument(
        ...,
        help=RESPONSES_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help=EXPORT_OUTPUT_HELP,
        dir_okay=False,
    ),
    format: Literal["csv", "json", "jsonl", "sqlite"] = typer.Option(
        EXPORT_FORMAT_DEFAULT,
        "--format",
        help=EXPORT_FORMAT_HELP,
    ),
    form_name: str | None = typer.Option(
        None,
        "--form-name",
        help=EXPORT_FORM_NAME_HELP,
    ),
) -> None:
    """Export responses to CSV, JSON, JSONL, or SQLite format."""
    conn = init_db(responses_path)
    try:
        responses = get_responses(conn, form_name=form_name)
    finally:
        conn.close()
    if not responses:
        console.print(EXPORT_NO_RESPONSES)
        raise typer.Exit(code=0)
    if format == "csv":
        export_to_csv(responses, output)
    elif format == "json":
        export_to_json(responses, output)
    elif format == "jsonl":
        export_to_jsonl(responses, output)
    else:
        export_to_sqlite(responses, output)
    console.print(
        f"{EXPORT_SUCCESS_PREFIX}{len(responses)}{EXPORT_SUCCESS_SUFFIX}"
        f"[bold]{output}[/bold]"
    )
    raise typer.Exit(code=0)


VIEW_START_PREFIX = "Starting datasette for "
VIEW_START_SUFFIX = " at http://127.0.0.1:"
VIEW_DATASETTE_MISSING = (
    "datasette is not installed. Install it with: uv add datasette"
)


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
    import importlib.util  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    # datasette must live in the same environment as formtuist so the
    # subprocess below can resolve it through the project virtualenv
    if importlib.util.find_spec("datasette") is None:
        console.print(VIEW_DATASETTE_MISSING)
        raise typer.Exit(code=1)
    console.print(
        f"{VIEW_START_PREFIX}[bold]{responses_path}[/bold]"
        f"{VIEW_START_SUFFIX}{port}"
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
            "--open",
        ],
        check=False,
    )


SCHEMA_OUTPUT_HELP = "Save the schema to a JSON file instead of printing it."
SCHEMA_THEME_HELP = "Pygments theme for syntax highlighting."
SCHEMA_THEME_DEFAULT = "ansi_dark"


@app.command()
def schema(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=SCHEMA_OUTPUT_HELP,
        dir_okay=False,
    ),
    theme: str = typer.Option(
        SCHEMA_THEME_DEFAULT,
        "--theme",
        help=SCHEMA_THEME_HELP,
    ),
) -> None:
    """Display the JSON schema that formtuist enforces."""
    import json  # noqa: PLC0415

    from rich.syntax import Syntax  # noqa: PLC0415

    from formtuist.schema import FormDefinition  # noqa: PLC0415

    schema_json = json.dumps(FormDefinition.model_json_schema(), indent=2)
    if output is not None:
        output.write_text(schema_json, encoding="utf-8")
        console.print(f"Schema saved to [bold]{output}[/bold]")
    else:
        syntax = Syntax(schema_json, "json", theme=theme)
        console.print(syntax)


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
    code_dir: Path = typer.Option(
        None,
        "--code-dir",
        help=CODE_DIR_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
    ),
    recompute: bool = typer.Option(
        False,
        "--recompute",
        help="Re-grade every response with the current form and update"
        " stored snapshots.",
    ),
) -> None:
    """Grade responses against a form with correct answers."""
    try:
        form = parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)
    conn = init_db(responses_path)
    try:
        responses = get_responses(conn, form_name=form.name)
        if not responses:
            console.print(f"{GRADE_NO_RESPONSES_PREFIX}{form.name}.")
            raise typer.Exit(code=0)
        graded = [
            question
            for question in form.questions
            if getattr(question, "correct_answer", None) is not None
        ]
        table = Table(
            title=f"{GRADE_TABLE_TITLE_PREFIX}{form.name}",
            header_style="bold",
        )
        table.add_column(GRADE_COLUMN_ID, justify="right")
        table.add_column(GRADE_COLUMN_STUDENT)
        for index, _question in enumerate(graded, start=1):
            table.add_column(
                f"{GRADE_QUESTION_COLUMN_PREFIX}{index}", justify="right"
            )
        table.add_column(GRADE_COLUMN_TOTAL, justify="right")
        table.add_column(GRADE_COLUMN_MAX, justify="right")
        table.add_column(GRADE_COLUMN_PERCENT, justify="right")
        for response in responses:
            report = _response_report(conn, form, response, recompute)
            breakdown = report[BREAKDOWN_KEY]
            by_id = {entry[BREAKDOWN_ID_KEY]: entry for entry in breakdown}
            row = [
                str(response[ID_COLUMN]),
                response[GITHUB_USERNAME_COLUMN] or GRADE_UNKNOWN_STUDENT,
            ]
            row.extend(
                str(by_id[question.id][BREAKDOWN_SCORE_KEY])
                if question.id in by_id
                else GRADE_NO_SCORE
                for question in graded
            )
            row.extend(
                [
                    str(report[TOTAL_KEY]),
                    str(report[MAX_KEY]),
                    f"{report[PERCENTAGE_KEY]:g}",
                ]
            )
            table.add_row(*row)
        console.print(table)
    finally:
        conn.close()
    raise typer.Exit(code=0)


def _response_report(
    conn: sqlite3.Connection,
    form: FormDefinition,
    response: dict[str, Any],
    recompute: bool,
) -> dict[str, Any]:
    """Return the report for one response, stored or freshly graded.

    The stored snapshot is used when present unless recompute is set.
    Missing snapshots (legacy rows, non-auto-graded forms) are graded
    on the fly. Recompute writes the fresh snapshot back to the row.
    """
    stored: dict[str, Any] | None = response.get(GRADE_JSON_COLUMN)
    if not recompute and stored is not None:
        return stored
    report = grade_response(form, response[ANSWERS_JSON_COLUMN])
    if recompute:
        update_response_grade(
            conn, response[ID_COLUMN], grade_report_to_json(report)
        )
    return report


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
    """Display help for the formtuist command-line interface."""


def main() -> None:
    """Entry point for the formtuist CLI."""
    app()


if __name__ == "__main__":
    main()
