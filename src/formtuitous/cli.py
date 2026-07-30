"""Typer-based CLI entry point for the formtuitous application."""

from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console

from formtuitous.parser import parse_form

console = Console()

app = typer.Typer(
    name="formtuitous",
    help=("Creating forms with JSON and a TUI is an unexpected success!"),
)


@app.command()
def check(
    form_path: Path = typer.Argument(
        ...,
        help="Path to a JSON form definition file.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Validate a form JSON file and print a summary."""
    try:
        form = parse_form(form_path)
    except ValidationError:
        raise typer.Exit(code=1)

    total = len(form.questions)
    required_count = sum(1 for q in form.questions if q.required)
    optional_count = total - required_count
    graded_count = sum(
        1
        for q in form.questions
        if getattr(q, "correct_answer", None) is not None
    )
    auto_grade = form.config.auto_grade

    console.print(f"Form: {form.name}")
    if form.description:
        console.print(f"Description: {form.description}")
    console.print(
        f"Questions: {total} ({required_count} required, "
        f"{optional_count} optional)"
    )
    if graded_count > 0:
        console.print(
            f"Graded: {graded_count} question(s) "
            f"(auto-grade is "
            f"{'on' if auto_grade else 'off'})"
        )
    else:
        console.print("Graded: none")
    console.print("Status: valid")

    raise typer.Exit(code=0)


@app.command()
def display(
    form_path: Path = typer.Argument(
        ...,
        help="Path to a JSON form definition file.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Display a form in the TUI and collect responses."""
    raise typer.Exit(code=0)


@app.command()
def serve(
    form_path: Path = typer.Argument(
        ...,
        help="Path to a JSON form definition file.",
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
        help="Path to a responses SQLite database.",
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
        help="Path to a responses SQLite database.",
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
        help="Path to a JSON form definition file.",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
    responses_path: Path = typer.Argument(
        ...,
        help="Path to a responses SQLite database.",
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
