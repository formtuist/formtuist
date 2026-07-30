"""SQLite storage layer for form responses with WAL mode support."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import platformdirs

# sqlite3 is part of the Python standard library — no extra dependency needed

DATABASE_FILENAME = "responses.db"
WAL_JOURNAL_MODE = "wal"


def get_default_db_dir() -> Path:
    """Return the platform-appropriate directory for formtuitous data."""
    return Path(platformdirs.user_data_dir("formtuitous", ensure_exists=True))


def ensure_db_dir(db_dir: Path) -> Path:
    """Create the database directory if it does not exist and return it."""
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def resolve_db_path(db_dir: Path | None = None) -> Path:
    """Return the full path to the database file.

    When *db_dir* is provided the directory is created if needed and the
    default filename is appended.  When *db_dir* is *None* the platform-
    appropriate default directory is used.
    """
    if db_dir is None:
        db_dir = get_default_db_dir()
    ensure_db_dir(db_dir)
    return db_dir / DATABASE_FILENAME


BUSY_TIMEOUT_MS = 30000
ID_COLUMN = "id"
FORM_NAME_COLUMN = "form_name"
SUBMITTED_AT_COLUMN = "submitted_at"
ANSWERS_JSON_COLUMN = "answers_json"
RESPONSES_TABLE = "responses"

CREATE_TABLE_SQL = (
    f"CREATE TABLE IF NOT EXISTS {RESPONSES_TABLE} ("
    f"    {ID_COLUMN} INTEGER PRIMARY KEY AUTOINCREMENT,"
    f"    {FORM_NAME_COLUMN} TEXT NOT NULL,"
    f"    {SUBMITTED_AT_COLUMN} TEXT NOT NULL,"
    f"    {ANSWERS_JSON_COLUMN} TEXT NOT NULL"
    f")"
)

PRAGMA_WAL = f"PRAGMA journal_mode={WAL_JOURNAL_MODE};"
PRAGMA_BUSY_TIMEOUT = f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS};"


def init_db(db_path: Path) -> sqlite3.Connection:
    """Open a connection and ensure WAL mode, busy timeout, and table exist."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(PRAGMA_WAL)
    conn.execute(PRAGMA_BUSY_TIMEOUT)
    conn.execute(CREATE_TABLE_SQL)
    conn.commit()
    return conn


def save_response(
    conn: sqlite3.Connection, form_name: str, answers: dict[str, Any]
) -> int:
    """Insert a response row and return the new row id."""
    submitted_at = datetime.now(timezone.utc).isoformat()
    answers_json = json.dumps(answers)
    cursor = conn.execute(
        f"INSERT INTO {RESPONSES_TABLE} "
        f"({FORM_NAME_COLUMN}, {SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN}) "
        f"VALUES (?, ?, ?)",
        (form_name, submitted_at, answers_json),
    )
    conn.commit()
    row_id = cursor.lastrowid
    assert row_id is not None
    return row_id


def get_responses(
    conn: sqlite3.Connection, form_name: str | None = None
) -> list[dict[str, Any]]:
    """Return all responses, optionally filtered by form name."""
    if form_name is None:
        rows = conn.execute(
            f"SELECT {ID_COLUMN}, {FORM_NAME_COLUMN}, "
            f"{SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN} "
            f"FROM {RESPONSES_TABLE} ORDER BY {ID_COLUMN}"
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {ID_COLUMN}, {FORM_NAME_COLUMN}, "
            f"{SUBMITTED_AT_COLUMN}, {ANSWERS_JSON_COLUMN} "
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
