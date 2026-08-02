"""SQLite storage layer for form responses with WAL mode support."""

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
SUBMITTED_AT_COLUMN = "submitted_at"
ANSWERS_JSON_COLUMN = "answers_json"
GITHUB_USERNAME_COLUMN = "github_username"
GITHUB_URL_COLUMN = "github_url"
GRADE_JSON_COLUMN = "grade_json"
RESPONSES_TABLE = "responses"

CREATE_TABLE_SQL = (
    f"CREATE TABLE IF NOT EXISTS {RESPONSES_TABLE} ("
    f"    {ID_COLUMN} INTEGER PRIMARY KEY AUTOINCREMENT,"
    f"    {FORM_NAME_COLUMN} TEXT NOT NULL,"
    f"    {SUBMITTED_AT_COLUMN} TEXT NOT NULL,"
    f"    {ANSWERS_JSON_COLUMN} TEXT NOT NULL,"
    f"    {GITHUB_USERNAME_COLUMN} TEXT,"
    f"    {GITHUB_URL_COLUMN} TEXT"
    f")"
)

# columns added after the initial table definition (for migrations)
EXTRA_COLUMNS: dict[str, str] = {
    GITHUB_USERNAME_COLUMN: "TEXT",
    GITHUB_URL_COLUMN: "TEXT",
    GRADE_JSON_COLUMN: "TEXT",
}

PRAGMA_WAL = f"PRAGMA journal_mode={WAL_JOURNAL_MODE};"
PRAGMA_BUSY_TIMEOUT = f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};"


def get_default_db_dir() -> Path:
    """Return the platform-appropriate directory for formtuitous data."""
    return Path(platformdirs.user_data_dir("formtuitous"))


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
) -> int:
    """Insert a response row and return the new row id.

    The *github_username* and *github_url* identity fields are optional
    and stored as nullable columns. The *grade* argument is an optional
    JSON-safe grade snapshot stored in the grade_json column. The raw
    authentication token is never stored.
    """
    submitted_at = datetime.now(timezone.utc).isoformat()
    answers_json = json.dumps(answers)
    grade_json = json.dumps(grade) if grade is not None else None
    cursor = conn.execute(
        f"INSERT INTO {RESPONSES_TABLE} "
        f"({FORM_NAME_COLUMN}, {SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN},"
        f" {GITHUB_USERNAME_COLUMN}, {GITHUB_URL_COLUMN},"
        f" {GRADE_JSON_COLUMN}) "
        f"VALUES (?, ?, ?, ?, ?, ?)",
        (
            form_name,
            submitted_at,
            answers_json,
            github_username,
            github_url,
            grade_json,
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


def get_responses(
    conn: sqlite3.Connection, form_name: str | None = None
) -> list[dict[str, Any]]:
    """Return all responses, optionally filtered by form name."""
    if form_name is None:
        rows = conn.execute(
            f"SELECT {ID_COLUMN}, {FORM_NAME_COLUMN}, "
            f"{SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN}, "
            f"{GITHUB_USERNAME_COLUMN}, {GITHUB_URL_COLUMN}, "
            f"{GRADE_JSON_COLUMN} "
            f"FROM {RESPONSES_TABLE} ORDER BY {ID_COLUMN}"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {ID_COLUMN}, {FORM_NAME_COLUMN}, "
            f"{SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN}, "
            f"{GITHUB_USERNAME_COLUMN}, {GITHUB_URL_COLUMN}, "
            f"{GRADE_JSON_COLUMN} "
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
        }
        for row in rows
    ]


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
