"""Typer-based CLI entry point for the formtuist application."""

import getpass
import os
import sqlite3
import uuid
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Literal, cast

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

from formtuist.analyze import (
    histogram,
    per_question_stats,
    quiz_stats,
    sparkline_for_question,
)
from formtuist.database import (
    ANSWERS_JSON_COLUMN,
    ATTEMPT_ID_ENV_NAME,
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
    export_grades_to_csv,
    export_grades_to_json,
    export_grades_to_jsonl,
    export_to_csv,
    export_to_json,
    export_to_jsonl,
    export_to_sqlite,
    grade_columns,
)
from formtuist.grader import (
    BREAKDOWN_ID_KEY,
    BREAKDOWN_KEY,
    BREAKDOWN_SCORE_KEY,
    FINAL_SCORE_KEY,
    MAX_KEY,
    PERCENTAGE_FINAL_KEY,
    PERCENTAGE_KEY,
    TOTAL_FINAL_KEY,
    TOTAL_KEY,
    grade_report_to_json,
    grade_response,
    is_pending,
    refresh_prelim,
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
APP_HELP = "Formtuist helps programmers and agents create, complete, and circulate forms!"

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
    "sparklines",
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
        or getattr(q, "review", "none") == "required"
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

DB_NOT_FOUND_PREFIX = "Responses database not found at "
DB_NOT_FOUND_SUFFIX = ". Create it with the display or serve command."


def _resolve_responses_path(
    responses_path: Path | None,
    db_dir: Path | None,
    database_name: str | None,
) -> Path:
    """Return the responses DB path, defaulting to the platformdir.

    An explicit path wins when it names an existing file. A bare
    filename that only exists inside the default database directory
    resolves there too, so every reader command can be run from any
    working directory against the databases that display or serve
    created.
    """
    if responses_path is None:
        return resolve_db_path(db_dir, database_name)
    path = Path(responses_path)
    if path.exists():
        return path
    if not path.is_absolute():
        base_dir = db_dir if db_dir is not None else get_default_db_dir()
        candidate = base_dir / path
        if candidate.exists():
            return candidate
    return path


def _require_responses_db(db_path: Path) -> None:
    """Exit with a friendly error when the responses database is absent."""
    if not db_path.exists():
        console.print(f"{DB_NOT_FOUND_PREFIX}{db_path}{DB_NOT_FOUND_SUFFIX}")
        raise typer.Exit(code=1)


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
    code_dir: Path | None = typer.Option(
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

    if code_dir is None:
        app_ui = FormtuistApp(form_path, db_path)
    else:
        app_ui = FormtuistApp(form_path, db_path, code_dir)
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
    # one shared attempt id for the whole serve run; every spawned display
    # subprocess inherits it through the environment so all clients of this
    # run land in the same single-submission fairness domain
    os.environ[ATTEMPT_ID_ENV_NAME] = str(uuid.uuid4())
    templates_dir = Path(__file__).parent / "templates"
    server = FormtuistServer(
        cmd,
        host=host,
        port=port,
        title=form.name,
        templates_path=templates_dir,
        quiet=False,
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
EXPORT_TYPE_DEFAULT = "full"
EXPORT_TYPE_HELP = "What to export: full or graded."
EXPORT_FORM_HELP = (
    "Recompute grades against this form for a graded export "
    "(default: stored grade snapshots)."
)
EXPORT_GRADED_NO_SQLITE = (
    "The sqlite format is not supported for a graded export; "
    "use csv, json, or jsonl."
)
EXPORT_STORED_GRADES_NOTE = (
    "Graded export uses stored snapshots; pass --form to recompute "
    "against the current answer key."
)


def _export_full(
    responses: list[dict[str, Any]],
    output: Path,
    format: Literal["csv", "json", "jsonl", "sqlite"],
) -> None:
    """Write the full export in the requested format."""
    if format == "csv":
        export_to_csv(responses, output)
    elif format == "json":
        export_to_json(responses, output)
    elif format == "jsonl":
        export_to_jsonl(responses, output)
    else:
        export_to_sqlite(responses, output)


def _export_graded(
    responses: list[dict[str, Any]],
    question_ids: list[str],
    form: FormDefinition | None,
    output: Path,
    format: Literal["csv", "json", "jsonl"],
) -> None:
    """Write the graded export in the requested format."""
    if format == "csv":
        export_grades_to_csv(responses, question_ids, form, output)
    elif format == "json":
        export_grades_to_json(responses, question_ids, form, output)
    else:
        export_grades_to_jsonl(responses, question_ids, form, output)


@app.command()
def export(  # noqa: PLR0913, PLR0917
    responses_path: Path | None = typer.Argument(
        None,
        help=RESPONSES_PATH_HELP,
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
    export_type: Literal["full", "graded"] = typer.Option(
        EXPORT_TYPE_DEFAULT,
        "--type",
        help=EXPORT_TYPE_HELP,
    ),
    form_path: Path | None = typer.Option(
        None,
        "--form",
        help=EXPORT_FORM_HELP,
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
    db_dir: Path | None = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
    database_name: str | None = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
) -> None:
    """Export responses to CSV, JSON, JSONL, or SQLite format."""
    db_path = _resolve_responses_path(responses_path, db_dir, database_name)
    _require_responses_db(db_path)
    conn = init_db(db_path)
    try:
        responses = get_responses(conn, form_name=form_name)
    finally:
        conn.close()
    if not responses:
        console.print(EXPORT_NO_RESPONSES)
        raise typer.Exit(code=0)
    if export_type == "graded" and format == "sqlite":
        console.print(EXPORT_GRADED_NO_SQLITE)
        raise typer.Exit(code=1)
    form = None
    if form_path is not None:
        try:
            form = parse_form(form_path, code_dir)
        except ValidationError:
            raise typer.Exit(code=1)
    if export_type == "full":
        _export_full(responses, output, format)
    else:
        question_ids = grade_columns(responses, form)
        if form is None:
            console.print(EXPORT_STORED_GRADES_NOTE)
        narrowed = cast(Literal["csv", "json", "jsonl"], format)
        _export_graded(responses, question_ids, form, output, narrowed)
    console.print(
        f"{EXPORT_SUCCESS_PREFIX}{len(responses)}{EXPORT_SUCCESS_SUFFIX}"
        f"[bold]{output}[/bold]"
    )
    raise typer.Exit(code=0)


PROVENANCE_VIEW_HELP = "Initial view: list, latest, or response."
PROVENANCE_RESPONSE_HELP = "Optional response ID to open directly."
PROVENANCE_LATEST_HELP = "Open the newest response directly."
PROVENANCE_NO_RESPONSE = "No response found for ID "
PROVENANCE_OPTION_CONFLICT = "Choose only one provenance selection option."
PROVENANCE_RESPONSE_REQUIRED = (
    "--view response requires --response-id or a response ID argument."
)


@app.command()
def provenance(  # noqa: PLR0913, PLR0917
    responses_path: Path | None = typer.Argument(
        None,
        help=RESPONSES_PATH_HELP,
        dir_okay=False,
        readable=True,
    ),
    response_id: int | None = typer.Argument(
        None,
        help=PROVENANCE_RESPONSE_HELP,
    ),
    view_mode: Literal["list", "latest", "response"] = typer.Option(
        "list",
        "--view",
        help=PROVENANCE_VIEW_HELP,
    ),
    latest: bool = typer.Option(
        False,
        "--latest",
        help=PROVENANCE_LATEST_HELP,
    ),
    response_id_option: int | None = typer.Option(
        None,
        "--response-id",
        help=PROVENANCE_RESPONSE_HELP,
    ),
    db_dir: Path | None = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
    database_name: str | None = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
) -> None:
    """Inspect stored form provenance in a read-only TUI."""
    if response_id is not None and response_id_option is not None:
        typer.echo(PROVENANCE_OPTION_CONFLICT)
        raise typer.Exit(code=2)
    selected_id = (
        response_id_option if response_id_option is not None else response_id
    )
    if latest and selected_id is not None:
        typer.echo(PROVENANCE_OPTION_CONFLICT)
        raise typer.Exit(code=2)
    if latest and view_mode != "list":
        typer.echo(PROVENANCE_OPTION_CONFLICT)
        raise typer.Exit(code=2)
    if selected_id is not None and view_mode not in {"list", "response"}:
        typer.echo(PROVENANCE_OPTION_CONFLICT)
        raise typer.Exit(code=2)
    initial_view = "latest" if latest else view_mode
    if selected_id is not None:
        initial_view = "response"
    if initial_view == "response" and selected_id is None:
        typer.echo(PROVENANCE_RESPONSE_REQUIRED)
        raise typer.Exit(code=2)
    db_path = _resolve_responses_path(responses_path, db_dir, database_name)
    _require_responses_db(db_path)
    if selected_id is not None:
        conn = init_db(db_path)
        try:
            response_ids = {
                response[ID_COLUMN] for response in get_responses(conn)
            }
        finally:
            conn.close()
        if selected_id not in response_ids:
            typer.echo(f"{PROVENANCE_NO_RESPONSE}{selected_id}.")
            raise typer.Exit(code=1)
    from formtuist.tui.app import ProvenanceApp  # noqa: PLC0415

    app_ui = ProvenanceApp(
        db_path,
        initial_view=initial_view,
        response_id=selected_id,
    )
    app_ui.run()


VIEW_START_PREFIX = "Starting datasette for "
VIEW_START_SUFFIX = " at http://127.0.0.1:"
VIEW_DATASETTE_MISSING = (
    "datasette is not installed. Install it with: uv add datasette"
)


@app.command()
def view(
    responses_path: Path | None = typer.Argument(
        None,
        help=RESPONSES_PATH_HELP,
        dir_okay=False,
        readable=True,
    ),
    port: int = typer.Option(8001, "--port", help="Port for datasette."),
    db_dir: Path | None = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
    database_name: str | None = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
) -> None:
    """Browse responses in a web browser via datasette."""
    import importlib.util  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    db_path = _resolve_responses_path(responses_path, db_dir, database_name)
    _require_responses_db(db_path)
    # datasette must live in the same environment as formtuist so the
    # subprocess below can resolve it through the project virtualenv
    if importlib.util.find_spec("datasette") is None:
        console.print(VIEW_DATASETTE_MISSING)
        raise typer.Exit(code=1)
    console.print(
        f"{VIEW_START_PREFIX}[bold]{db_path}[/bold]{VIEW_START_SUFFIX}{port}"
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "datasette",
            "serve",
            str(db_path),
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


@app.command(hidden=True)
def grade(  # noqa: PLR0913, PLR0917
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    responses_path: Path | None = typer.Argument(
        None,
        help=RESPONSES_PATH_HELP,
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
    db_dir: Path | None = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
    database_name: str | None = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
) -> None:
    """Grade responses against a form with correct answers."""
    try:
        form = parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)
    db_path = _resolve_responses_path(responses_path, db_dir, database_name)
    _require_responses_db(db_path)
    conn = init_db(db_path)
    try:
        responses = get_responses(conn, form_name=form.name)
        if not responses:
            console.print(f"{GRADE_NO_RESPONSES_PREFIX}{form.name}.")
            raise typer.Exit(code=0)
        graded = [
            question
            for question in form.questions
            if getattr(question, "correct_answer", None) is not None
            or getattr(question, "review", "none") == "required"
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
    on the fly. Recompute refreshes prelim scores but preserves any
    human manual_score and comment.
    """
    stored: dict[str, Any] | None = response.get(GRADE_JSON_COLUMN)
    if not recompute and stored is not None:
        return stored
    if recompute and stored is not None:
        report = refresh_prelim(stored, form, response[ANSWERS_JSON_COLUMN])
        update_response_grade(
            conn, response[ID_COLUMN], grade_report_to_json(report)
        )
        return report
    report = grade_response(form, response[ANSWERS_JSON_COLUMN])
    if recompute:
        update_response_grade(
            conn, response[ID_COLUMN], grade_report_to_json(report)
        )
    return report


REVIEW_TYPE_HELP = "Which review queue to open: required or all."
REVIEW_QUESTION_HELP = "Only review this question id."
REVIEWER_HELP = (
    "Reviewer identity for reviewed_by; defaults to the detected local"
    " username when omitted."
)
REVIEW_BATCH_HELP = "Batch-apply manual scores from a CSV file."
REVIEW_STUDENT_HELP = "Show the student's name during review."


def _resolve_reviewer(reviewer: str | None) -> str:
    """Return the reviewer identity, defaulting to the OS username."""
    if reviewer is not None and reviewer.strip():
        return reviewer.strip()
    return getpass.getuser()


@app.command()
def review(  # noqa: PLR0913, PLR0917
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    responses_path: Path | None = typer.Argument(
        None,
        help=RESPONSES_PATH_HELP,
        dir_okay=False,
        readable=True,
    ),
    review_type: Literal["required", "all"] = typer.Option(
        "required",
        "--review-type",
        help=REVIEW_TYPE_HELP,
    ),
    question: str | None = typer.Option(
        None,
        "--question",
        help=REVIEW_QUESTION_HELP,
    ),
    reviewer: str | None = typer.Option(
        None,
        "--reviewer",
        help=REVIEWER_HELP,
    ),
    batch: Path | None = typer.Option(
        None,
        "--batch",
        help=REVIEW_BATCH_HELP,
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
    db_dir: Path | None = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
    database_name: str | None = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
    show_student_name: bool = typer.Option(
        True,
        "--show-student-name/--no-show-student-name",
        help=REVIEW_STUDENT_HELP,
    ),
) -> None:
    """Review and post-grade responses requiring human judgement."""
    try:
        form = parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)
    db_path = _resolve_responses_path(responses_path, db_dir, database_name)
    _require_responses_db(db_path)
    # batch mode: apply CSV overrides without launching the TUI
    if batch is not None:
        import csv  # noqa: PLC0415

        from formtuist.database import set_post_grade  # noqa: PLC0415

        conn = init_db(db_path)
        try:
            # reviewer defaults to the local OS username; each CSV row may
            # still override it with its own reviewer column
            batch_reviewer = _resolve_reviewer(reviewer)
            count = 0
            with batch.open(encoding="utf-8", newline="") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    rid_raw = row.get("response_id") or row.get("id")
                    qid = row.get("question_id") or row.get("id_")
                    score_raw = row.get("manual_score") or row.get("score")
                    if rid_raw is None or qid is None or score_raw is None:
                        continue
                    try:
                        rid = int(str(rid_raw).strip())
                        score = int(str(score_raw).strip())
                    except ValueError:
                        continue
                    comment = row.get("comment")
                    if comment is not None and not str(comment).strip():
                        comment = None
                    row_reviewer = row.get("reviewer") or batch_reviewer
                    set_post_grade(
                        conn,
                        form,
                        rid,
                        str(qid).strip(),
                        score,
                        comment=comment,
                        reviewer=row_reviewer,
                    )
                    count += 1
            # report the number of manual grades applied
            typer.echo(f"Applied {count} manual grade(s).")
        finally:
            conn.close()
        raise typer.Exit(code=0)
    # interactive TUI mode; defaults to the local OS username
    effective_reviewer = _resolve_reviewer(reviewer)
    from formtuist.tui.app import ReviewApp  # noqa: PLC0415

    app_ui = ReviewApp(
        form_path,
        db_path,
        review_type,
        question,
        effective_reviewer,
        show_student_name,
    )
    app_ui.run()


ANALYZE_REVIEW_HELP = "Use prelim or final scores."
ANALYZE_QUESTION_HELP = "Only analyze this question id."
ANALYZE_FORMAT_HELP = "Output format: table, json, or csv."
ANALYZE_OUTPUT_HELP = "Write output to a file."
ANALYZE_BINS_HELP = "Number of histogram bins."
ANALYZE_SPARKLINES_HELP = (
    "Comma-separated question ids for sparklines (table only, e.g., q1,q2)."
)
ANALYZE_SPARKLINES_ALL_HELP = (
    "Show sparklines for all gradeable questions (table only)."
)


@app.command()
def analyze(  # noqa: PLR0912, PLR0913, PLR0915, PLR0917
    form_path: Path = typer.Argument(
        ...,
        help=FORM_PATH_HELP,
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    responses_path: Path | None = typer.Argument(
        None,
        help=RESPONSES_PATH_HELP,
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
    review: Literal["final", "prelim"] = typer.Option(
        "final",
        "--review",
        help=ANALYZE_REVIEW_HELP,
    ),
    question: str | None = typer.Option(
        None,
        "--question",
        help=ANALYZE_QUESTION_HELP,
    ),
    format: Literal["table", "json", "csv"] = typer.Option(
        "table",
        "--format",
        help=ANALYZE_FORMAT_HELP,
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help=ANALYZE_OUTPUT_HELP,
        dir_okay=False,
    ),
    bins: int = typer.Option(
        10,
        "--bins",
        help=ANALYZE_BINS_HELP,
    ),
    sparklines_id: str | None = typer.Option(
        None,
        "--sparklines-id",
        help=ANALYZE_SPARKLINES_HELP,
    ),
    sparklines_all: bool = typer.Option(
        False,
        "--sparklines-all",
        help=ANALYZE_SPARKLINES_ALL_HELP,
    ),
    db_dir: Path | None = typer.Option(
        None,
        help=DB_DIR_HELP,
        file_okay=False,
        dir_okay=True,
    ),
    database_name: str | None = typer.Option(
        None,
        "--database-name",
        help=DB_NAME_HELP,
    ),
) -> None:
    """Analyze quiz statistics with average, distribution, and ranking."""
    import csv as csvlib  # noqa: PLC0415
    import json as jsonlib  # noqa: PLC0415

    try:
        form = parse_form(form_path, code_dir)
    except ValidationError:
        raise typer.Exit(code=1)
    db_path = _resolve_responses_path(responses_path, db_dir, database_name)
    _require_responses_db(db_path)
    conn = init_db(db_path)
    try:
        responses = get_responses(conn, form_name=form.name)
    finally:
        conn.close()
    if not responses:
        console.print(f"{GRADE_NO_RESPONSES_PREFIX}{form.name}.")
        raise typer.Exit(code=0)
    # build reports, handling review mode and pending
    reports: list[dict[str, Any]] = []
    for resp in responses:
        grade = resp.get(GRADE_JSON_COLUMN)
        if grade is None:
            grade = grade_report_to_json(
                grade_response(form, resp[ANSWERS_JSON_COLUMN])
            )
        else:
            # ensure final fields exist for legacy snapshots
            from formtuist.grader import finalize_report  # noqa: PLC0415

            grade = finalize_report(grade)
        if review == "prelim":
            # use prelim totals for prelim view
            prelim_report = {
                **grade,
                TOTAL_FINAL_KEY: grade[TOTAL_KEY],
                PERCENTAGE_FINAL_KEY: grade[PERCENTAGE_KEY],
            }
            # per-entry final should be prelim
            prelim_report[BREAKDOWN_KEY] = [
                {
                    **e,
                    FINAL_SCORE_KEY: e.get(
                        BREAKDOWN_SCORE_KEY, e.get(FINAL_SCORE_KEY)
                    ),
                }
                for e in grade[BREAKDOWN_KEY]
            ]
            reports.append(prelim_report)
        else:
            reports.append(grade)
    # filter by question focus if requested
    per_q_all = per_question_stats(reports, form)
    if question is not None:
        per_q_all = [p for p in per_q_all if p["id"] == question]
        if not per_q_all:
            console.print(f"unknown question id: {question}")
            raise typer.Exit(code=1)
    # sparklines handling — mutually exclusive flags
    if sparklines_all and sparklines_id is not None:
        console.print("cannot use both --sparklines-all and --sparklines-id")
        raise typer.Exit(code=1)
    spark_ids: list[str] | None = None
    if sparklines_all:
        from formtuist.exporter import grade_columns  # noqa: PLC0415

        spark_ids = grade_columns(reports, form)  # type: ignore[arg-type]
        if not spark_ids:
            spark_ids = [
                q.id  # type: ignore[union-attr]
                for q in form.questions
                if getattr(q, "correct_answer", None) is not None
                or getattr(q, "review", "none") == "required"
            ]
    elif sparklines_id is not None:
        spark_ids = [s.strip() for s in sparklines_id.split(",") if s.strip()]
        valid_ids = {q.id for q in form.questions}  # type: ignore[union-attr]
        for sid in spark_ids:
            if sid not in valid_ids:
                console.print(f"unknown question id: {sid}")
                raise typer.Exit(code=1)
    # compute aggregates
    max_points = sum(
        getattr(q, "points", 0)  # type: ignore[union-attr]
        for q in form.questions
        if getattr(q, "correct_answer", None) is not None
        or getattr(q, "review", "none") == "required"
    )
    qstats = quiz_stats(reports, max_points)
    # histogram over finalized percentages
    finalized_reports = [r for r in reports if not is_pending(r)]
    percentages = [
        r.get(PERCENTAGE_FINAL_KEY, r[PERCENTAGE_KEY])
        for r in finalized_reports
    ]
    hist = histogram(percentages, bins=bins)  # type: ignore[arg-type]
    # output handling
    if format in ("json", "csv"):
        payload = {
            "form": form.name,
            "quiz": qstats,
            "histogram": hist,
            "per_question": per_q_all,
        }
        if spark_ids is not None:
            spark_map = {
                sid: sparkline_for_question(sid, reports)
                for sid in spark_ids or []
            }
            payload["sparklines"] = spark_map
        if format == "json":
            out_text = jsonlib.dumps(payload, indent=2)
            if output is not None:
                output.write_text(out_text, encoding="utf-8")
                console.print(f"Analysis written to [bold]{output}[/bold]")
            else:
                typer.echo(out_text)
        else:
            # csv: per-question rows
            fieldnames = [
                "id",
                "points",
                "avg_final",
                "median_final",
                "p",
                "difficulty",
                "correct_rate",
                "n_finalized",
                "pending",
            ]
            if spark_ids is not None:
                fieldnames.append("sparkline")
            rows = []
            for row in per_q_all:
                r: dict[str, Any] = {
                    k: row[k] for k in fieldnames if k != "sparkline"
                }
                if spark_ids is not None:
                    if row["id"] in spark_ids:
                        r["sparkline"] = sparkline_for_question(
                            row["id"], reports
                        )
                    else:
                        r["sparkline"] = ""
                rows.append(r)
            if output is not None:
                with output.open("w", encoding="utf-8", newline="") as f:
                    w = csvlib.DictWriter(f, fieldnames=fieldnames)
                    w.writeheader()
                    w.writerows(rows)
                console.print(f"Analysis written to [bold]{output}[/bold]")
            else:
                # write csv to stdout via typer
                import io  # noqa: PLC0415

                buf = io.StringIO()
                w = csvlib.DictWriter(buf, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)
                typer.echo(buf.getvalue())
        raise typer.Exit(code=0)
    # table format (default) — three panels
    # panel 1: quiz-level
    qtable = Table(
        title=f"Quiz Statistics for {form.name}",
        header_style="bold",
    )
    qtable.add_column("Metric")
    qtable.add_column("Value", justify="right")
    pending_n = qstats["n_total"] - qstats["n_finalized"]
    qtable.add_row("Responses", str(qstats["n_total"]))
    qtable.add_row("Finalized", str(qstats["n_finalized"]))
    qtable.add_row("Pending", str(pending_n))
    qtable.add_row("Max points", str(qstats["max_points"]))
    if qstats["n_finalized"] > 0:
        qtable.add_row(
            "Mean",
            f"{qstats['mean_total']:.1f}/{qstats['max_points']} "
            f"({qstats['mean_percentage']:.1f}%)",
        )
        qtable.add_row(
            "Median",
            f"{qstats['median_total']:.1f} "
            f"({qstats['median_percentage']:.1f}%)",
        )
        qtable.add_row(
            "Stddev",
            f"{qstats['stdev_total']:.1f} ({qstats['stdev_percentage']:.1f}%)",
        )
        qtable.add_row(
            "Five-number %",
            f"min {qstats['min_percentage']:.1f}  "
            f"Q1 {qstats['q1_percentage']:.1f}  "
            f"med {qstats['median_percentage']:.1f}  "
            f"Q3 {qstats['q3_percentage']:.1f}  "
            f"max {qstats['max_percentage']:.1f}",
        )
        if pending_n > 0:
            qtable.add_row(
                "Note",
                f"[yellow]Pending: {pending_n} need review[/yellow]",
            )
    console.print(qtable)
    console.print("")
    # panel 2: histogram with min/max context for the bar
    hist_title = (
        f"Distribution (percentage_{review}, "
        f"n_finalized={qstats['n_finalized']}"
    )
    if qstats["n_finalized"] > 0:
        hist_title += (
            f", min {qstats['min_percentage']:.1f}%, "
            f"max {qstats['max_percentage']:.1f}%"
        )
    hist_title += ")"
    htable = Table(
        title=hist_title,
        header_style="bold",
    )
    htable.add_column("Range")
    htable.add_column("Count", justify="right")
    htable.add_column("Bar")
    max_count = max((b["count"] for b in hist), default=1)
    for b in hist:
        bar = "█" * int(b["count"] / max_count * 10) if max_count else ""
        htable.add_row(b["label"], str(b["count"]), bar)
    console.print(htable)
    if qstats["n_finalized"] > 0:
        console.print(
            f"[dim]Bar: 1 █ = 1 response "
            f"(min 0, max {max_count} per bin)[/dim]"
        )
    console.print("")
    # panel 3: per-question ranking
    ptable = Table(
        title="Per-question (easiest → hardest, final)",
        header_style="bold",
    )
    ptable.add_column("Rank", justify="right")
    ptable.add_column("ID")
    ptable.add_column("Pts", justify="right")
    ptable.add_column("Avg", justify="right")
    ptable.add_column("p%", justify="right")
    ptable.add_column("Correct%", justify="right")
    ptable.add_column("Pending", justify="right")
    if spark_ids is not None:
        ptable.add_column("Sparkline")
    for idx, row in enumerate(per_q_all, start=1):
        avg_str = f"{row['avg_final']:.1f}/{row['points']}"
        p_str = f"{row['p'] * 100:.0f}%"
        corr_str = f"{row['correct_rate'] * 100:.0f}%"
        cols: list[str] = [
            str(idx),
            row["id"],
            str(row["points"]),
            avg_str,
            p_str,
            corr_str,
            str(row["pending"]),
        ]
        if spark_ids is not None:
            if row["id"] in spark_ids:
                cols.append(sparkline_for_question(row["id"], reports))
            else:
                cols.append("")
        ptable.add_row(*cols)
    console.print(ptable)
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
    """Display help for the formtuist command-line interface."""


def main() -> None:
    """Entry point for the formtuist CLI."""
    app()


if __name__ == "__main__":
    main()
