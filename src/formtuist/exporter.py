"""Export form responses to CSV, JSON, JSONL, or SQLite format."""

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

from formtuist.database import (
    ANSWERS_JSON_COLUMN,
    ATTEMPT_ID_COLUMN,
    FORM_CONTENTS_COLUMN,
    FORM_HASH_COLUMN,
    FORM_NAME_COLUMN,
    FORM_PATH_COLUMN,
    FORM_VERSION_COLUMN,
    GITHUB_URL_COLUMN,
    GITHUB_USERNAME_COLUMN,
    GRADE_JSON_COLUMN,
    ID_COLUMN,
    SUBMITTED_AT_COLUMN,
)
from formtuist.grader import (
    BREAKDOWN_ID_KEY,
    BREAKDOWN_KEY,
    BREAKDOWN_SCORE_KEY,
    COMMENT_KEY,
    FINAL_SCORE_KEY,
    MANUAL_SCORE_KEY,
    MAX_KEY,
    NEEDS_REVIEW_KEY,
    PERCENTAGE_FINAL_KEY,
    PERCENTAGE_KEY,
    TOTAL_FINAL_KEY,
    TOTAL_KEY,
    grade_response,
)
from formtuist.schema import FormDefinition

# flat export column names shared by every output format
FLAT_ID = "id"
FLAT_FORM_NAME = "form_name"
FLAT_ATTEMPT_ID = "attempt_id"
FLAT_SUBMITTED_AT = "submitted_at"
FLAT_GITHUB_USERNAME = "github_username"
FLAT_GITHUB_URL = "github_url"
FLAT_FORM_VERSION = "form_version"
FLAT_FORM_HASH = "form_hash"
FLAT_FORM_PATH = "form_path"
FLAT_FORM_CONTENTS = "form_contents"
FLAT_TOTAL = "total"
FLAT_MAX = "max"
FLAT_PERCENTAGE = "percentage"
FLAT_FINAL_TOTAL = "final_total"
FLAT_FINAL_PERCENTAGE = "final_percentage"
FLAT_PENDING_COUNT = "pending_count"

# the flat metadata columns that precede the per-question answer columns
METADATA_COLUMNS = [
    FLAT_ID,
    FLAT_FORM_NAME,
    FLAT_ATTEMPT_ID,
    FLAT_SUBMITTED_AT,
    FLAT_GITHUB_USERNAME,
    FLAT_GITHUB_URL,
    FLAT_TOTAL,
    FLAT_MAX,
    FLAT_PERCENTAGE,
    FLAT_FINAL_TOTAL,
    FLAT_FINAL_PERCENTAGE,
    FLAT_PENDING_COUNT,
    FLAT_FORM_VERSION,
    FLAT_FORM_HASH,
    FLAT_FORM_PATH,
    FLAT_FORM_CONTENTS,
]

# flat name for the student column in the graded export and its placeholder
FLAT_STUDENT = "student"
GRADE_UNKNOWN_STUDENT = "-"

# the metadata columns that precede the per-question score columns
GRADE_COLUMNS = [
    FLAT_ID,
    FLAT_FORM_NAME,
    FLAT_ATTEMPT_ID,
    FLAT_STUDENT,
    FLAT_TOTAL,
    FLAT_MAX,
    FLAT_PERCENTAGE,
    FLAT_FINAL_TOTAL,
    FLAT_FINAL_PERCENTAGE,
    FLAT_PENDING_COUNT,
    FLAT_FORM_VERSION,
    FLAT_FORM_HASH,
    FLAT_FORM_PATH,
    FLAT_FORM_CONTENTS,
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
    response: dict[str, Any],
    columns: list[str],
    comment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Flatten one response into a row with metadata and answers."""
    grade = response[GRADE_JSON_COLUMN]
    if grade is not None:
        final_total = grade.get(TOTAL_FINAL_KEY, grade.get(TOTAL_KEY))
        final_perc = grade.get(PERCENTAGE_FINAL_KEY, grade.get(PERCENTAGE_KEY))
        pending = sum(
            1
            for entry in grade.get(BREAKDOWN_KEY, [])
            if entry.get(NEEDS_REVIEW_KEY)
            and entry.get(MANUAL_SCORE_KEY) is None
        )
    else:
        final_total, final_perc, pending = None, None, None
    comments: dict[str, Any] = {}
    if grade is not None:
        comments = {
            entry[BREAKDOWN_ID_KEY]: entry.get(COMMENT_KEY)
            for entry in grade.get(BREAKDOWN_KEY, [])
        }
    flat = {
        FLAT_ID: response[ID_COLUMN],
        FLAT_FORM_NAME: response[FORM_NAME_COLUMN],
        FLAT_ATTEMPT_ID: response[ATTEMPT_ID_COLUMN],
        FLAT_SUBMITTED_AT: response[SUBMITTED_AT_COLUMN],
        FLAT_GITHUB_USERNAME: response[GITHUB_USERNAME_COLUMN],
        FLAT_GITHUB_URL: response[GITHUB_URL_COLUMN],
        FLAT_FORM_VERSION: response.get(FORM_VERSION_COLUMN),
        FLAT_FORM_HASH: response.get(FORM_HASH_COLUMN),
        FLAT_FORM_PATH: response.get(FORM_PATH_COLUMN),
        FLAT_FORM_CONTENTS: response.get(FORM_CONTENTS_COLUMN),
        FLAT_TOTAL: grade[TOTAL_KEY] if grade is not None else None,
        FLAT_MAX: grade[MAX_KEY] if grade is not None else None,
        FLAT_PERCENTAGE: (
            grade[PERCENTAGE_KEY] if grade is not None else None
        ),
        FLAT_FINAL_TOTAL: final_total,
        FLAT_FINAL_PERCENTAGE: final_perc,
        FLAT_PENDING_COUNT: pending,
    }
    answers = response[ANSWERS_JSON_COLUMN]
    for column in columns:
        flat[column] = answers.get(column)
    for qid in comment_ids or []:
        flat[f"{qid}_comment"] = comments.get(qid)
    return flat


def pending_count(response: dict[str, Any]) -> int | None:
    """Return the number of pending reviews for a response."""
    grade = response[GRADE_JSON_COLUMN]
    if grade is None:
        return None
    return sum(
        1
        for entry in grade.get(BREAKDOWN_KEY, [])
        if entry.get(NEEDS_REVIEW_KEY) and entry.get(MANUAL_SCORE_KEY) is None
    )


def _gradeable_ids(responses: list[dict[str, Any]]) -> list[str]:
    """Return sorted question ids found in any grade breakdown."""
    ids: set[str] = set()
    for response in responses:
        grade = response[GRADE_JSON_COLUMN]
        if grade is None:
            continue
        for entry in grade.get(BREAKDOWN_KEY, []):
            ids.add(entry[BREAKDOWN_ID_KEY])
    return sorted(ids)


def comment_columns(responses: list[dict[str, Any]]) -> list[str]:
    """Return a qid_comment column for every gradeable question."""
    return [f"{qid}_comment" for qid in _gradeable_ids(responses)]


def _flatten_all(
    responses: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return flat rows plus the answer and comment columns they use."""
    columns = answer_columns(responses)
    gradeable = _gradeable_ids(responses)
    return (
        [flatten_response(r, columns, gradeable) for r in responses],
        columns + [f"{qid}_comment" for qid in gradeable],
    )


def _write_csv(
    rows: list[dict[str, Any]], fieldnames: list[str], output_path: Path
) -> None:
    """Write rows as a flat CSV table to output_path."""
    with output_path.open(
        "w", encoding=EXPORT_ENCODING, newline=CSV_NEWLINE
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {key: _csv_value(value) for key, value in row.items()}
            )


def _write_json(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Write rows as a JSON array to output_path."""
    output_path.write_text(
        json.dumps(rows, indent=2), encoding=EXPORT_ENCODING
    )


def _write_jsonl(rows: list[dict[str, Any]], output_path: Path) -> None:
    """Write rows as JSON-lines, one object per line."""
    with output_path.open("w", encoding=EXPORT_ENCODING) as file:
        for row in rows:
            file.write(json.dumps(row))
            file.write("\n")


def export_to_csv(responses: list[dict[str, Any]], output_path: Path) -> None:
    """Write responses as a flat CSV table to output_path."""
    rows, columns = _flatten_all(responses)
    _write_csv(rows, METADATA_COLUMNS + columns, output_path)


def export_to_json(responses: list[dict[str, Any]], output_path: Path) -> None:
    """Write responses as a JSON array of flat objects."""
    rows, _columns = _flatten_all(responses)
    _write_json(rows, output_path)


def export_to_jsonl(
    responses: list[dict[str, Any]], output_path: Path
) -> None:
    """Write responses as JSON-lines, one flat object per line."""
    rows, _columns = _flatten_all(responses)
    _write_jsonl(rows, output_path)


def grade_columns(
    responses: list[dict[str, Any]], form: FormDefinition | None = None
) -> list[str]:
    """Return the ordered question ids for the graded export columns.

    With a form the ids follow the form's question order; otherwise they
    follow the first-seen order across all stored grade snapshots.
    """
    if form is not None:
        return [
            question.id
            for question in form.questions
            if getattr(question, "correct_answer", None) is not None
            or getattr(question, "review", "none") == "required"
        ]
    question_ids: list[str] = []
    seen_ids: set[str] = set()
    for response in responses:
        grade = response[GRADE_JSON_COLUMN]
        breakdown: list[Any] = (
            grade[BREAKDOWN_KEY] if grade is not None else []
        )
        for entry in breakdown:
            question_id = entry[BREAKDOWN_ID_KEY]
            if question_id in seen_ids:
                continue
            seen_ids.add(question_id)
            question_ids.append(question_id)
    return question_ids


def flatten_grades(
    responses: list[dict[str, Any]],
    question_ids: list[str],
    form: FormDefinition | None = None,
) -> list[dict[str, Any]]:
    """Return grade-only flat rows, recomputed or from stored snapshots."""
    rows = []
    for response in responses:
        if form is not None:
            report = grade_response(form, response[ANSWERS_JSON_COLUMN])
            # overlay stored manual scores when a snapshot exists
            stored = response[GRADE_JSON_COLUMN]
            if stored is not None:
                # reuse manual fields from stored snapshot
                from formtuist.grader import refresh_prelim  # noqa: PLC0415

                report = refresh_prelim(
                    stored, form, response[ANSWERS_JSON_COLUMN]
                )
            scores = {
                entry[BREAKDOWN_ID_KEY]: entry.get(
                    FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY]
                )
                for entry in report[BREAKDOWN_KEY]
            }
            comments = {
                entry[BREAKDOWN_ID_KEY]: entry.get(COMMENT_KEY)
                for entry in report[BREAKDOWN_KEY]
            }
            total = report.get(TOTAL_FINAL_KEY, report[TOTAL_KEY])
            max_total = report[MAX_KEY]
            percentage = report.get(
                PERCENTAGE_FINAL_KEY, report[PERCENTAGE_KEY]
            )
            pending = sum(
                1
                for entry in report[BREAKDOWN_KEY]
                if entry.get(NEEDS_REVIEW_KEY)
                and entry.get(MANUAL_SCORE_KEY) is None
            )
        else:
            grade = response[GRADE_JSON_COLUMN]
            if grade is None:
                scores, comments = {}, {}
                total, max_total, percentage, pending = (
                    None,
                    None,
                    None,
                    None,
                )
            else:
                scores = {
                    entry[BREAKDOWN_ID_KEY]: entry.get(
                        FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY]
                    )
                    for entry in grade[BREAKDOWN_KEY]
                }
                comments = {
                    entry[BREAKDOWN_ID_KEY]: entry.get(COMMENT_KEY)
                    for entry in grade[BREAKDOWN_KEY]
                }
                total = grade.get(TOTAL_FINAL_KEY, grade.get(TOTAL_KEY))
                max_total = grade[MAX_KEY]
                percentage = grade.get(
                    PERCENTAGE_FINAL_KEY, grade.get(PERCENTAGE_KEY)
                )
                pending = sum(
                    1
                    for entry in grade.get(BREAKDOWN_KEY, [])
                    if entry.get(NEEDS_REVIEW_KEY)
                    and entry.get(MANUAL_SCORE_KEY) is None
                )
        row: dict[str, Any] = {
            FLAT_ID: response[ID_COLUMN],
            FLAT_FORM_NAME: response[FORM_NAME_COLUMN],
            FLAT_ATTEMPT_ID: response[ATTEMPT_ID_COLUMN],
            FLAT_FORM_VERSION: response.get(FORM_VERSION_COLUMN),
            FLAT_FORM_HASH: response.get(FORM_HASH_COLUMN),
            FLAT_FORM_PATH: response.get(FORM_PATH_COLUMN),
            FLAT_FORM_CONTENTS: response.get(FORM_CONTENTS_COLUMN),
            FLAT_STUDENT: (
                response[GITHUB_USERNAME_COLUMN] or GRADE_UNKNOWN_STUDENT
            ),
            FLAT_TOTAL: total,
            FLAT_MAX: max_total,
            FLAT_PERCENTAGE: percentage,
            FLAT_FINAL_TOTAL: total,
            FLAT_FINAL_PERCENTAGE: percentage,
            FLAT_PENDING_COUNT: pending,
        }
        for question_id in question_ids:
            row[question_id] = scores.get(question_id)
            # expose review comment alongside each score column
            row[f"{question_id}_comment"] = comments.get(question_id)
        rows.append(row)
    return rows


def export_grades_to_csv(
    responses: list[dict[str, Any]],
    question_ids: list[str],
    form: FormDefinition | None,
    output_path: Path,
) -> None:
    """Write the graded view as a flat CSV table to output_path."""
    rows = flatten_grades(responses, question_ids, form)
    comment_cols = [f"{qid}_comment" for qid in question_ids]
    _write_csv(rows, GRADE_COLUMNS + question_ids + comment_cols, output_path)


def export_grades_to_json(
    responses: list[dict[str, Any]],
    question_ids: list[str],
    form: FormDefinition | None,
    output_path: Path,
) -> None:
    """Write the graded view as a JSON array to output_path."""
    rows = flatten_grades(responses, question_ids, form)
    _write_json(rows, output_path)


def export_grades_to_jsonl(
    responses: list[dict[str, Any]],
    question_ids: list[str],
    form: FormDefinition | None,
    output_path: Path,
) -> None:
    """Write the graded view as JSON-lines to output_path."""
    rows = flatten_grades(responses, question_ids, form)
    _write_jsonl(rows, output_path)


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
