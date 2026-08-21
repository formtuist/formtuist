"""SQLite storage layer for form responses with WAL mode support."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import platformdirs

DATABASE_FILENAME = "responses.db"
WAL_JOURNAL_MODE = "wal"

BUSY_TIMEOUT_MS = 30000
ID_COLUMN = "id"
FORM_NAME_COLUMN = "form_name"
ATTEMPT_ID_COLUMN = "attempt_id"
SUBMITTED_AT_COLUMN = "submitted_at"
ANSWERS_JSON_COLUMN = "answers_json"
GITHUB_USERNAME_COLUMN = "github_username"
GITHUB_URL_COLUMN = "github_url"
GRADE_JSON_COLUMN = "grade_json"
FORM_VERSION_COLUMN = "form_version"
FORM_HASH_COLUMN = "form_hash"
FORM_PATH_COLUMN = "form_path"
FORM_CONTENTS_COLUMN = "form_contents"
RESPONSES_TABLE = "responses"

# environment variable carrying the shared attempt id for a server run
ATTEMPT_ID_ENV_NAME = "FORMTUIST_ATTEMPT_ID"

CREATE_TABLE_SQL = (
    f"CREATE TABLE IF NOT EXISTS {RESPONSES_TABLE} ("
    f"    {ID_COLUMN} INTEGER PRIMARY KEY AUTOINCREMENT,"
    f"    {FORM_NAME_COLUMN} TEXT NOT NULL,"
    f"    {ATTEMPT_ID_COLUMN} TEXT,"
    f"    {SUBMITTED_AT_COLUMN} TEXT NOT NULL,"
    f"    {ANSWERS_JSON_COLUMN} TEXT NOT NULL,"
    f"    {GITHUB_USERNAME_COLUMN} TEXT,"
    f"    {GITHUB_URL_COLUMN} TEXT,"
    f"    {GRADE_JSON_COLUMN} TEXT,"
    f"    {FORM_VERSION_COLUMN} TEXT,"
    f"    {FORM_HASH_COLUMN} TEXT,"
    f"    {FORM_PATH_COLUMN} TEXT,"
    f"    {FORM_CONTENTS_COLUMN} TEXT"
    f")"
)

# columns added after the initial table definition (for migrations)
EXTRA_COLUMNS: dict[str, str] = {
    ATTEMPT_ID_COLUMN: "TEXT",
    GITHUB_USERNAME_COLUMN: "TEXT",
    GITHUB_URL_COLUMN: "TEXT",
    GRADE_JSON_COLUMN: "TEXT",
    FORM_VERSION_COLUMN: "TEXT",
    FORM_HASH_COLUMN: "TEXT",
    FORM_PATH_COLUMN: "TEXT",
    FORM_CONTENTS_COLUMN: "TEXT",
}

# per-form unique index that blocks duplicate identity submissions
UNIQUE_IDENTITY_INDEX_PREFIX = "idx_responses_unique_identity_"
INDEX_NAME_HASH_LENGTH = 16
FORM_NAME_ENCODING = "utf-8"

PRAGMA_WAL = f"PRAGMA journal_mode={WAL_JOURNAL_MODE};"
PRAGMA_BUSY_TIMEOUT = f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};"


def get_default_db_dir() -> Path:
    """Return the platform-appropriate directory for formtuist data."""
    return Path(platformdirs.user_data_dir("formtuist"))


def ensure_db_dir(db_dir: Path) -> Path:
    """Create the database directory if it does not exist and return it."""
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def resolve_db_path(
    db_dir: Path | None = None,
    db_name: str | None = None,
) -> Path:
    """Return the full path to the database file.

    When *db_dir* is provided the directory is created if needed.
    When *db_dir* is *None* the platform-appropriate default directory is
    used. The filename is *db_name* when given, otherwise the default
    *DATABASE_FILENAME* is used.
    """
    if db_dir is None:
        db_dir = get_default_db_dir()
    ensure_db_dir(db_dir)
    filename = db_name if db_name is not None else DATABASE_FILENAME
    return db_dir / filename


def _ensure_extra_columns(conn: sqlite3.Connection) -> None:
    """Add any missing columns to an existing responses table."""
    existing = {
        row[1]
        for row in conn.execute(
            f"PRAGMA table_info({RESPONSES_TABLE})"
        ).fetchall()
    }
    for column, definition in EXTRA_COLUMNS.items():
        if column not in existing:
            conn.execute(
                f"ALTER TABLE {RESPONSES_TABLE} "
                f"ADD COLUMN {column} {definition}"
            )


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open a connection and ensure WAL mode, busy timeout, and table exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(PRAGMA_WAL)
    conn.execute(PRAGMA_BUSY_TIMEOUT)
    conn.execute(CREATE_TABLE_SQL)
    _ensure_extra_columns(conn)
    conn.commit()
    return conn


def save_response(  # noqa: PLR0913, PLR0917
    conn: sqlite3.Connection,
    form_name: str,
    answers: dict[str, Any],
    github_username: str | None = None,
    github_url: str | None = None,
    grade: dict[str, Any] | None = None,
    attempt_id: str | None = None,
    form_version: str | None = None,
    form_hash: str | None = None,
    form_path: str | None = None,
    form_contents: str | None = None,
) -> int:
    """Insert a response row and return the new row id.

    The *github_username* and *github_url* identity fields are optional
    and stored as nullable columns. The *grade* argument is an optional
    JSON-safe grade snapshot stored in the grade_json column. The
    *attempt_id* scopes a submission to one run of the form. Form provenance
    fields identify and reproduce the input JSON used for the submission. The
    raw authentication token is never stored.
    """
    submitted_at = datetime.now(timezone.utc).isoformat()
    answers_json = json.dumps(answers)
    grade_json = json.dumps(grade) if grade is not None else None
    cursor = conn.execute(
        f"INSERT INTO {RESPONSES_TABLE} "
        f"({FORM_NAME_COLUMN}, {ATTEMPT_ID_COLUMN}, {SUBMITTED_AT_COLUMN},"
        f" {ANSWERS_JSON_COLUMN}, {GITHUB_USERNAME_COLUMN},"
        f" {GITHUB_URL_COLUMN}, {GRADE_JSON_COLUMN},"
        f" {FORM_VERSION_COLUMN}, {FORM_HASH_COLUMN}, {FORM_PATH_COLUMN},"
        f" {FORM_CONTENTS_COLUMN}) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            form_name,
            attempt_id,
            submitted_at,
            answers_json,
            github_username,
            github_url,
            grade_json,
            form_version,
            form_hash,
            form_path,
            form_contents,
        ),
    )
    conn.commit()
    row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def update_response_grade(
    conn: sqlite3.Connection, response_id: int, grade: dict[str, Any]
) -> None:
    """Replace the stored grade snapshot for an existing response."""
    grade_json = json.dumps(grade)
    conn.execute(
        f"UPDATE {RESPONSES_TABLE} SET {GRADE_JSON_COLUMN} = ? "
        f"WHERE {ID_COLUMN} = ?",
        (grade_json, response_id),
    )
    conn.commit()


def _find_question(form: Any, question_id: str) -> Any | None:  # type: ignore[no-untyped-def]
    """Return the question with the given id, or None."""
    for question in form.questions:
        if question.id == question_id:
            return question
    return None


def set_post_grade(  # noqa: PLR0913, PLR0917
    conn: sqlite3.Connection,
    form: Any,  # FormDefinition
    response_id: int,
    question_id: str,
    manual_score: int,
    comment: str | None = None,
    reviewer: str | None = None,
) -> None:
    """Persist a manual score for one question in a response.

    Validates ``0 <= manual_score <= points`` and merges the
    human decision into ``grade_json`` via the grader helpers.
    The write overwrites any prior manual score so re-review is
    supported. Commits the updated snapshot.
    """
    from formtuist.grader import (  # noqa: PLC0415
        apply_post_grade,
        grade_report_to_json,
        grade_response,
    )

    question = _find_question(form, question_id)
    if question is None:
        raise ValueError(f"unknown question id: {question_id}")
    points = getattr(question, "points", 0)
    if not 0 <= manual_score <= points:
        raise ValueError(
            f"manual_score {manual_score} out of range 0..{points}"
            f" for question {question_id}"
        )
    # load the existing response row
    row = conn.execute(
        f"SELECT {ANSWERS_JSON_COLUMN}, {GRADE_JSON_COLUMN} "
        f"FROM {RESPONSES_TABLE} WHERE {ID_COLUMN} = ?",
        (response_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown response id: {response_id}")
    answers = json.loads(row[0])
    grade = json.loads(row[1]) if row[1] is not None else None
    if grade is None:
        # create a fresh prelim report for manual-only forms
        grade = grade_report_to_json(grade_response(form, answers))
    overrides = {
        question_id: {
            "manual_score": manual_score,
            "comment": comment,
            "reviewer": reviewer,
        }
    }
    updated = apply_post_grade(grade, overrides)
    # ensure json-safe snapshot with refreshed timestamp
    snapshot = grade_report_to_json(updated)
    # preserve manual fields that grade_report_to_json would reset
    # by copying them from updated into snapshot
    by_old = {e["id"]: e for e in updated.get("breakdown", [])}  # type: ignore[union-attr]
    for entry in snapshot.get("breakdown", []):  # type: ignore[union-attr]
        old = by_old.get(entry["id"])
        if old is not None and old.get("manual_score") is not None:
            entry["manual_score"] = old["manual_score"]
            entry["final_score"] = old["final_score"]
            entry["comment"] = old.get("comment")
            entry["reviewed_by"] = old.get("reviewed_by")
            entry["reviewed_at"] = old.get("reviewed_at")
    # recompute final totals after manual merge (in case snapshot reset)
    from formtuist.grader import (  # noqa: PLC0415
        PERCENTAGE_FINAL_KEY,
        TOTAL_FINAL_KEY,
    )

    snapshot[TOTAL_FINAL_KEY] = updated[TOTAL_FINAL_KEY]
    snapshot[PERCENTAGE_FINAL_KEY] = updated[PERCENTAGE_FINAL_KEY]
    update_response_grade(conn, response_id, snapshot)


def get_final_report(
    conn: sqlite3.Connection, response_id: int
) -> dict[str, Any] | None:
    """Return the final report for a response, or None if missing."""
    from formtuist.grader import finalize_report  # noqa: PLC0415

    row = conn.execute(
        f"SELECT {GRADE_JSON_COLUMN} FROM {RESPONSES_TABLE} "
        f"WHERE {ID_COLUMN} = ?",
        (response_id,),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    grade = json.loads(row[0])
    # ensure final fields exist for legacy snapshots
    return finalize_report(grade)


def list_pending(
    conn: sqlite3.Connection,
    form_name: str | None = None,
    question_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return responses with a pending required review.

    When *question_id* is given only responses pending for that
    question are returned.
    """
    responses = get_responses(conn, form_name=form_name)
    pending: list[dict[str, Any]] = []
    for response in responses:
        grade = response.get(GRADE_JSON_COLUMN)
        if grade is None:
            continue
        for entry in grade.get("breakdown", []):
            if not entry.get("needs_review"):
                continue
            if entry.get("manual_score") is not None:
                continue
            if question_id is not None and entry.get("id") != question_id:
                continue
            pending.append(response)
            break
    return pending


def get_responses(
    conn: sqlite3.Connection, form_name: str | None = None
) -> list[dict[str, Any]]:
    """Return all responses, optionally filtered by form name."""
    if form_name is None:
        rows = conn.execute(
            f"SELECT {ID_COLUMN}, {FORM_NAME_COLUMN}, "
            f"{SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN}, "
            f"{GITHUB_USERNAME_COLUMN}, {GITHUB_URL_COLUMN}, "
            f"{GRADE_JSON_COLUMN}, {ATTEMPT_ID_COLUMN}, "
            f"{FORM_VERSION_COLUMN}, {FORM_HASH_COLUMN}, "
            f"{FORM_PATH_COLUMN}, {FORM_CONTENTS_COLUMN} "
            f"FROM {RESPONSES_TABLE} ORDER BY {ID_COLUMN}"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {ID_COLUMN}, {FORM_NAME_COLUMN}, "
            f"{SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN}, "
            f"{GITHUB_USERNAME_COLUMN}, {GITHUB_URL_COLUMN}, "
            f"{GRADE_JSON_COLUMN}, {ATTEMPT_ID_COLUMN}, "
            f"{FORM_VERSION_COLUMN}, {FORM_HASH_COLUMN}, "
            f"{FORM_PATH_COLUMN}, {FORM_CONTENTS_COLUMN} "
            f"FROM {RESPONSES_TABLE} "
            f"WHERE {FORM_NAME_COLUMN} = ? ORDER BY {ID_COLUMN}",
            (form_name,),
        ).fetchall()
    return [
        {
            ID_COLUMN: row[0],
            FORM_NAME_COLUMN: row[1],
            SUBMITTED_AT_COLUMN: row[2],
            ANSWERS_JSON_COLUMN: json.loads(row[3]),
            GITHUB_USERNAME_COLUMN: row[4],
            GITHUB_URL_COLUMN: row[5],
            GRADE_JSON_COLUMN: (
                json.loads(row[6]) if row[6] is not None else None
            ),
            ATTEMPT_ID_COLUMN: row[7],
            FORM_VERSION_COLUMN: row[8],
            FORM_HASH_COLUMN: row[9],
            FORM_PATH_COLUMN: row[10],
            FORM_CONTENTS_COLUMN: row[11],
        }
        for row in rows
    ]


def get_response_provenance(
    conn: sqlite3.Connection, response_id: int
) -> dict[str, Any] | None:
    """Return stored form provenance for a response, or None if missing."""
    row = conn.execute(
        f"SELECT {FORM_VERSION_COLUMN}, {FORM_HASH_COLUMN}, "
        f"{FORM_PATH_COLUMN}, {FORM_CONTENTS_COLUMN} "
        f"FROM {RESPONSES_TABLE} WHERE {ID_COLUMN} = ?",
        (response_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        FORM_VERSION_COLUMN: row[0],
        FORM_HASH_COLUMN: row[1],
        FORM_PATH_COLUMN: row[2],
        FORM_CONTENTS_COLUMN: row[3],
    }


def get_response_count(
    conn: sqlite3.Connection, form_name: str | None = None
) -> int:
    """Return the number of responses, optionally filtered by form name."""
    if form_name is None:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {RESPONSES_TABLE}"
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT COUNT(*) FROM {RESPONSES_TABLE} "
            f"WHERE {FORM_NAME_COLUMN} = ?",
            (form_name,),
        ).fetchone()
    result: int = row[0]
    return result


def _sql_literal(value: str) -> str:
    """Return a SQL string literal with embedded single quotes escaped."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def has_submission(
    conn: sqlite3.Connection,
    form_name: str,
    attempt_id: str,
    github_username: str,
) -> bool:
    """Return whether an identity has already submitted in this attempt."""
    row = conn.execute(
        f"SELECT COUNT(*) FROM {RESPONSES_TABLE} "
        f"WHERE {FORM_NAME_COLUMN} = ? AND {ATTEMPT_ID_COLUMN} = ? "
        f"AND {GITHUB_USERNAME_COLUMN} = ?",
        (form_name, attempt_id, github_username),
    ).fetchone()
    result: int = row[0]
    return result > 0


def ensure_single_submission_index(
    conn: sqlite3.Connection, form_name: str, attempt_id: str
) -> bool:
    """Create the unique identity index for a single-submission attempt.

    The index is scoped to one form name and one attempt id so that
    forms which allow repeat submissions keep accepting them and so that
    a re-run of the same form starts a fresh fairness domain. Legacy
    databases holding duplicate identity rows cannot take the index;
    those return False so callers keep working with the pre-save check
    alone.
    """
    seed = f"{form_name}\x00{attempt_id}"
    digest = hashlib.sha256(seed.encode(FORM_NAME_ENCODING)).hexdigest()
    index_name = (
        f"{UNIQUE_IDENTITY_INDEX_PREFIX}{digest[:INDEX_NAME_HASH_LENGTH]}"
    )
    form_literal = _sql_literal(form_name)
    attempt_literal = _sql_literal(attempt_id)
    sql = (
        f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
        f"ON {RESPONSES_TABLE} ({FORM_NAME_COLUMN}, {ATTEMPT_ID_COLUMN},"
        f" {GITHUB_USERNAME_COLUMN}) "
        f"WHERE {GITHUB_USERNAME_COLUMN} IS NOT NULL "
        f"AND {FORM_NAME_COLUMN} = {form_literal} "
        f"AND {ATTEMPT_ID_COLUMN} = {attempt_literal}"
    )
    try:
        conn.execute(sql)
        conn.commit()
        return True
    except (sqlite3.OperationalError, sqlite3.IntegrityError):
        return False
