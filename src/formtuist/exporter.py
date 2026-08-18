"""Export form responses to CSV, JSON, JSONL, or SQLite format."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from formtuist.database import (
    ANSWERS_JSON_COLUMN,
    FORM_NAME_COLUMN,
    GITHUB_URL_COLUMN,
    GITHUB_USERNAME_COLUMN,
    GRADE_JSON_COLUMN,
    ID_COLUMN,
    SUBMITTED_AT_COLUMN,
)
from formtuist.grader import MAX_KEY, PERCENTAGE_KEY, TOTAL_KEY

# flat export column names shared by every output format
FLAT_ID = "id"
FLAT_FORM_NAME = "form_name"
FLAT_SUBMITTED_AT = "submitted_at"
FLAT_GITHUB_USERNAME = "github_username"
FLAT_GITHUB_URL = "github_url"
FLAT_TOTAL = "total"
FLAT_MAX = "max"
FLAT_PERCENTAGE = "percentage"

# the flat metadata columns that precede the per-question answer columns
METADATA_COLUMNS = [
    FLAT_ID,
    FLAT_FORM_NAME,
    FLAT_SUBMITTED_AT,
    FLAT_GITHUB_USERNAME,
    FLAT_GITHUB_URL,
    FLAT_TOTAL,
    FLAT_MAX,
    FLAT_PERCENTAGE,
]

# the flat table written by the sqlite export for datasette browsing
FLAT_TABLE = "responses_flat"

# encoding used for all export files
EXPORT_ENCODING = "utf-8"

# newline argument for csv writing to avoid blank lines on Windows
CSV_NEWLINE = ""


def answer_columns(responses: list[dict[str, Any]]) -> list[str]:
    """Return the sorted union of answer keys across all responses."""
    keys: set[str] = set()
    for response in responses:
        keys.update(response[ANSWERS_JSON_COLUMN])
    return sorted(keys)


def flatten_response(
    response: dict[str, Any], columns: list[str]
) -> dict[str, Any]:
    """Flatten one response into a single row with metadata and answers."""
    grade = response[GRADE_JSON_COLUMN]
    flat = {
        FLAT_ID: response[ID_COLUMN],
        FLAT_FORM_NAME: response[FORM_NAME_COLUMN],
        FLAT_SUBMITTED_AT: response[SUBMITTED_AT_COLUMN],
        FLAT_GITHUB_USERNAME: response[GITHUB_USERNAME_COLUMN],
        FLAT_GITHUB_URL: response[GITHUB_URL_COLUMN],
        FLAT_TOTAL: grade[TOTAL_KEY] if grade is not None else None,
        FLAT_MAX: grade[MAX_KEY] if grade is not None else None,
        FLAT_PERCENTAGE: grade[PERCENTAGE_KEY] if grade is not None else None,
    }
    answers = response[ANSWERS_JSON_COLUMN]
    for column in columns:
        flat[column] = answers.get(column)
    return flat


def _flatten_all(
    responses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return flat rows plus the answer columns they use."""
    columns = answer_columns(responses)
    return [flatten_response(r, columns) for r in responses], columns


def export_to_csv(responses: list[dict[str, Any]], output_path: Path) -> None:
    """Write responses as a flat CSV table to output_path."""
    rows, columns = _flatten_all(responses)
    fieldnames = METADATA_COLUMNS + columns
    with output_path.open(
        "w", encoding=EXPORT_ENCODING, newline=CSV_NEWLINE
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: _csv_value(value) for key, value in row.items()}
            )


def export_to_json(responses: list[dict[str, Any]], output_path: Path) -> None:
    """Write responses as a JSON array of flat objects."""
    rows, _columns = _flatten_all(responses)
    output_path.write_text(
        json.dumps(rows, indent=2), encoding=EXPORT_ENCODING
    )


def export_to_jsonl(
    responses: list[dict[str, Any]], output_path: Path
) -> None:
    """Write responses as JSON-lines, one flat object per line."""
    rows, _columns = _flatten_all(responses)
    with output_path.open("w", encoding=EXPORT_ENCODING) as file:
        for row in rows:
            file.write(json.dumps(row))
            file.write("\n")


def export_to_sqlite(
    responses: list[dict[str, Any]], output_path: Path
) -> None:
    """Write responses into a flat responses_flat table for datasette."""
    rows, columns = _flatten_all(responses)
    conn = sqlite3.connect(str(output_path))
    try:
        conn.execute(f"DROP TABLE IF EXISTS {FLAT_TABLE}")
        fieldnames = METADATA_COLUMNS + columns
        column_sql = ", ".join(f'"{name}"' for name in fieldnames)
        conn.execute(f"CREATE TABLE {FLAT_TABLE} ({column_sql})")
        placeholders = ", ".join("?" for _ in fieldnames)
        for row in rows:
            conn.execute(
                f"INSERT INTO {FLAT_TABLE} VALUES ({placeholders})",
                tuple(_sqlite_value(row[name]) for name in fieldnames),
            )
        conn.commit()
    finally:
        conn.close()


def _csv_value(value: Any) -> Any:
    """Return a csv-safe scalar for a flat row value."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value


def _sqlite_value(value: Any) -> Any:
    """Return a bindable sqlite value for a flat row value."""
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return value
