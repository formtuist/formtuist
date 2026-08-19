"""Tests for the response export functionality."""

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
    get_responses,
    init_db,
    save_response,
)
from formtuist.exporter import (
    FLAT_FORM_NAME,
    FLAT_GITHUB_USERNAME,
    FLAT_ID,
    FLAT_MAX,
    FLAT_PERCENTAGE,
    FLAT_STUDENT,
    FLAT_TABLE,
    FLAT_TOTAL,
    METADATA_COLUMNS,
    answer_columns,
    export_grades_to_csv,
    export_grades_to_json,
    export_grades_to_jsonl,
    export_to_csv,
    export_to_json,
    export_to_jsonl,
    export_to_sqlite,
    flatten_grades,
    flatten_response,
    grade_columns,
)
from formtuist.schema import FormDefinition, ShortTextQuestion

FORM_NAME = "Quiz"
FIRST_ANSWER = "a"
SECOND_ANSWER = "b"
LIST_ANSWER = ["x", "y"]
NUMERIC_ANSWER = 3
GRADE_TOTAL = 20
GRADE_MAX = 20
GRADE_PERCENT = 100.0
RESPONSE_COUNT = 2
FIRST_RESPONSE_ANSWERS = {"q1": FIRST_ANSWER, "q2": NUMERIC_ANSWER}
SECOND_RESPONSE_ANSWERS = {"q1": SECOND_ANSWER}


def _grade() -> dict[str, Any]:
    """Build a JSON-safe grade snapshot for a perfect score."""
    return {
        "total": GRADE_TOTAL,
        "max": GRADE_MAX,
        "percentage": GRADE_PERCENT,
        "breakdown": [],
        "graded_at": "2026-08-01T00:00:00+00:00",
    }


def _responses(tmp_path: Path) -> list[dict[str, Any]]:
    """Create a database with two responses and return them."""
    db_path = tmp_path / "responses.db"
    conn = init_db(db_path)
    save_response(
        conn,
        FORM_NAME,
        FIRST_RESPONSE_ANSWERS,
        github_username="alice",
        grade=_grade(),
    )
    save_response(
        conn,
        FORM_NAME,
        SECOND_RESPONSE_ANSWERS,
        github_username="bob",
    )
    conn.close()
    return _read_all(db_path)


def _single_response(
    tmp_path: Path, answers: dict[str, Any]
) -> dict[str, Any]:
    """Create a database with one response and return it."""
    db_path = tmp_path / "single.db"
    conn = init_db(db_path)
    save_response(conn, FORM_NAME, answers, github_username="alice")
    conn.close()
    return _read_all(db_path)[0]


def _read_all(db_path: Path) -> list[dict[str, Any]]:
    """Return every response stored in the database at db_path."""
    conn = init_db(db_path)
    try:
        return get_responses(conn)
    finally:
        conn.close()


class TestAnswerColumns:
    """Tests for deriving the flat answer columns."""

    def test_union_sorted(self, tmp_path: Path) -> None:
        """Answer columns are the sorted union of answer keys."""
        responses = _responses(tmp_path)
        assert answer_columns(responses) == ["q1", "q2"]

    def test_no_answers(self) -> None:
        """A response without answers contributes no columns."""
        response: dict[str, Any] = {
            ID_COLUMN: 1,
            FORM_NAME_COLUMN: "F",
            SUBMITTED_AT_COLUMN: "now",
            ANSWERS_JSON_COLUMN: {},
            GITHUB_USERNAME_COLUMN: None,
            GITHUB_URL_COLUMN: None,
            GRADE_JSON_COLUMN: None,
        }
        assert answer_columns([response]) == []


class TestFlattenResponse:
    """Tests for flattening a single response into a flat row."""

    def test_metadata_and_answers(self, tmp_path: Path) -> None:
        """The flat row keeps metadata, grade, and answer values."""
        responses = _responses(tmp_path)
        row = flatten_response(responses[0], ["q1", "q2"])
        assert row[FLAT_ID] == responses[0][ID_COLUMN]
        assert row[FLAT_FORM_NAME] == FORM_NAME
        assert row[FLAT_TOTAL] == GRADE_TOTAL
        assert row[FLAT_MAX] == GRADE_MAX
        assert row[FLAT_PERCENTAGE] == GRADE_PERCENT
        assert row[FLAT_GITHUB_USERNAME] == "alice"
        assert row["q1"] == FIRST_ANSWER
        assert row["q2"] == NUMERIC_ANSWER

    def test_missing_answer_and_grade(self, tmp_path: Path) -> None:
        """Missing answers and grades become None values."""
        responses = _responses(tmp_path)
        row = flatten_response(responses[1], ["q1", "q2"])
        assert row["q2"] is None
        assert row[FLAT_TOTAL] is None
        assert row[FLAT_MAX] is None
        assert row[FLAT_PERCENTAGE] is None


class TestExportToCsv:
    """Tests for the CSV export format."""

    def test_writes_header_and_rows(self, tmp_path: Path) -> None:
        """The CSV has metadata and answer columns with values."""
        responses = _responses(tmp_path)
        out = tmp_path / "responses.csv"
        export_to_csv(responses, out)
        with out.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        assert len(rows) == RESPONSE_COUNT
        assert rows[0][FLAT_FORM_NAME] == FORM_NAME
        assert rows[0]["q1"] == FIRST_ANSWER
        assert rows[0]["q2"] == "3"
        assert rows[0][FLAT_TOTAL] == str(GRADE_TOTAL)
        assert rows[0][FLAT_GITHUB_USERNAME] == "alice"
        assert rows[1]["q2"] == ""
        assert rows[1][FLAT_TOTAL] == ""

    def test_list_answer_json_encoded(self, tmp_path: Path) -> None:
        """List answers are JSON-encoded in CSV cells."""
        response = _single_response(tmp_path, {"q1": LIST_ANSWER})
        out = tmp_path / "responses.csv"
        export_to_csv([response], out)
        with out.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))
        assert json.loads(rows[0]["q1"]) == LIST_ANSWER


class TestExportToJson:
    """Tests for the JSON array export format."""

    def test_writes_flat_array(self, tmp_path: Path) -> None:
        """The JSON file is an array of flat response objects."""
        responses = _responses(tmp_path)
        out = tmp_path / "responses.json"
        export_to_json(responses, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert isinstance(data, list)
        assert len(data) == RESPONSE_COUNT
        assert data[0][FLAT_FORM_NAME] == FORM_NAME
        assert data[0]["q1"] == FIRST_ANSWER
        assert data[0][FLAT_TOTAL] == GRADE_TOTAL
        assert data[0][FLAT_GITHUB_USERNAME] == "alice"
        assert data[1]["q2"] is None
        assert data[1][FLAT_TOTAL] is None

    def test_preserves_native_list_answer(self, tmp_path: Path) -> None:
        """List answers stay JSON arrays in the JSON export."""
        response = _single_response(tmp_path, {"q1": LIST_ANSWER})
        out = tmp_path / "responses.json"
        export_to_json([response], out)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["q1"] == LIST_ANSWER

    def test_round_trip_into_database(self, tmp_path: Path) -> None:
        """Flat JSON records re-import into a fresh database."""
        responses = _responses(tmp_path)
        out = tmp_path / "responses.json"
        export_to_json(responses, out)
        records = json.loads(out.read_text(encoding="utf-8"))
        db_path = tmp_path / "roundtrip.db"
        conn = init_db(db_path)
        for record in records:
            answers = {
                key: value
                for key, value in record.items()
                if key not in set(METADATA_COLUMNS)
            }
            save_response(conn, record[FLAT_FORM_NAME], answers)
        conn.close()
        imported = _read_all(db_path)
        assert [r[ANSWERS_JSON_COLUMN] for r in imported] == [
            FIRST_RESPONSE_ANSWERS,
            {**SECOND_RESPONSE_ANSWERS, "q2": None},
        ]


class TestExportToJsonl:
    """Tests for the JSON-lines export format."""

    def test_one_object_per_line(self, tmp_path: Path) -> None:
        """Each line holds one flat response object."""
        responses = _responses(tmp_path)
        out = tmp_path / "responses.jsonl"
        export_to_jsonl(responses, out)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == RESPONSE_COUNT
        records = [json.loads(line) for line in lines]
        assert records[0]["q1"] == FIRST_ANSWER
        assert records[1][FLAT_GITHUB_USERNAME] == "bob"


class TestExportToSqlite:
    """Tests for the SQLite flat-table export format."""

    def test_creates_flat_table(self, tmp_path: Path) -> None:
        """The sqlite export writes a browsable responses_flat table."""
        responses = _responses(tmp_path)
        out = tmp_path / "flat.db"
        export_to_sqlite(responses, out)
        conn = sqlite3.connect(str(out))
        try:
            columns = [
                row[1]
                for row in conn.execute(f"PRAGMA table_info({FLAT_TABLE})")
            ]
            rows = conn.execute(
                f"SELECT {FLAT_FORM_NAME}, {FLAT_TOTAL}, q1 FROM {FLAT_TABLE}"
            ).fetchall()
            bob_q2 = conn.execute(
                f"SELECT q2 FROM {FLAT_TABLE} WHERE {FLAT_ID} = 2"
            ).fetchone()[0]
        finally:
            conn.close()
        assert columns == [
            "id",
            "form_name",
            "attempt_id",
            "submitted_at",
            "github_username",
            "github_url",
            "total",
            "max",
            "percentage",
            "q1",
            "q2",
        ]
        assert rows[0] == (FORM_NAME, GRADE_TOTAL, FIRST_ANSWER)
        assert bob_q2 is None

    def test_replaces_flat_table(self, tmp_path: Path) -> None:
        """A second export replaces the flat table instead of duplicating."""
        responses = _responses(tmp_path)
        out = tmp_path / "flat.db"
        export_to_sqlite(responses, out)
        export_to_sqlite(responses[:1], out)
        conn = sqlite3.connect(str(out))
        try:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {FLAT_TABLE}"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 1

    def test_list_answer_stored_as_json(self, tmp_path: Path) -> None:
        """List answers are JSON-encoded strings in the flat table."""
        response = _single_response(tmp_path, {"q1": LIST_ANSWER})
        out = tmp_path / "flat.db"
        export_to_sqlite([response], out)
        conn = sqlite3.connect(str(out))
        try:
            value = conn.execute(f"SELECT q1 FROM {FLAT_TABLE}").fetchone()[0]
        finally:
            conn.close()
        assert json.loads(value) == LIST_ANSWER


GRADED_QUESTION_IDS = ["q1", "q2"]
GRADED_TOTAL = 15
GRADED_MAX = 20
GRADED_Q1_SCORE = 10
GRADED_Q2_SCORE = 5
ZERO_SCORE = 0


def _graded_snapshot() -> dict[str, Any]:
    """Build a stored grade snapshot with two graded questions."""
    return {
        "total": GRADED_TOTAL,
        "max": GRADED_MAX,
        "percentage": 75.0,
        "breakdown": [
            {"id": "q1", "score": GRADED_Q1_SCORE, "max": 10, "correct": True},
            {
                "id": "q2",
                "score": GRADED_Q2_SCORE,
                "max": 10,
                "correct": False,
            },
        ],
    }


def _graded_responses(tmp_path: Path) -> list[dict[str, Any]]:
    """Create a database with one graded and one ungraded response."""
    db_path = tmp_path / "grades.db"
    conn = init_db(db_path)
    save_response(
        conn,
        FORM_NAME,
        {"q1": "a", "q2": "b"},
        github_username="alice",
        grade=_graded_snapshot(),
    )
    save_response(conn, FORM_NAME, {"q1": "c"}, github_username="bob")
    conn.close()
    return _read_all(db_path)


def _short_form(question_ids: list[str]) -> FormDefinition:
    """Build a form with one gradeable short_text question per id."""
    return FormDefinition(
        name=FORM_NAME,
        questions=[
            ShortTextQuestion(
                id=qid,
                text=f"Question {qid}?",
                type="short_text",
                correct_answer="a" if qid == "q1" else "b",
                points=10,
                grading_type="exact",
            )
            for qid in question_ids
        ],
    )


class TestGradeColumns:
    """Tests for deriving the graded export question columns."""

    def test_from_form_order(self, tmp_path: Path) -> None:
        """With a form the columns follow the form question order."""
        responses = _graded_responses(tmp_path)
        form = _short_form(["q2", "q1"])
        assert grade_columns(responses, form) == ["q2", "q1"]

    def test_from_stored_snapshot(self, tmp_path: Path) -> None:
        """Without a form the columns follow the stored breakdown order."""
        responses = _graded_responses(tmp_path)
        assert grade_columns(responses) == GRADED_QUESTION_IDS

    def test_empty_when_no_snapshots(self, tmp_path: Path) -> None:
        """No stored grades means no graded columns."""
        responses = _responses(tmp_path)
        assert grade_columns(responses) == []


class TestFlattenGrades:
    """Tests for the grade-only flatten view."""

    def test_from_stored_snapshot(self, tmp_path: Path) -> None:
        """Stored snapshot scores populate the graded rows."""
        responses = _graded_responses(tmp_path)
        qids = grade_columns(responses)
        rows = flatten_grades(responses, qids)
        first = rows[0]
        assert first[FLAT_STUDENT] == "alice"
        assert first["q1"] == GRADED_Q1_SCORE
        assert first["q2"] == GRADED_Q2_SCORE
        assert first[FLAT_TOTAL] == GRADED_TOTAL

    def test_missing_snapshot_blank(self, tmp_path: Path) -> None:
        """Responses without a stored snapshot get blank scores."""
        responses = _graded_responses(tmp_path)
        rows = flatten_grades(responses, ["q1", "q2"])
        second = rows[1]
        assert second[FLAT_STUDENT] == "bob"
        assert second["q1"] is None
        assert second[FLAT_TOTAL] is None

    def test_unknown_student(self, tmp_path: Path) -> None:
        """Responses without an identity use the placeholder student."""
        db_path = tmp_path / "anon.db"
        conn = init_db(db_path)
        save_response(conn, FORM_NAME, {"q1": "a"}, grade=_graded_snapshot())
        conn.close()
        responses = _read_all(db_path)
        row = flatten_grades(responses, ["q1", "q2"])[0]
        assert row[FLAT_STUDENT] == "-"

    def test_recomputed_from_form(self, tmp_path: Path) -> None:
        """With a form, grades are recomputed from the stored answers."""
        responses = _responses(tmp_path)
        form = _short_form(["q1"])
        qids = grade_columns(responses, form)
        rows = flatten_grades(responses, qids, form)
        assert rows[0]["q1"] == GRADED_Q1_SCORE
        assert rows[1]["q1"] == ZERO_SCORE
        assert rows[0][FLAT_TOTAL] == GRADED_Q1_SCORE


class TestExportGrades:
    """Tests for writing the graded view to each format."""

    def test_export_grades_to_csv(self, tmp_path: Path) -> None:
        """Graded CSV includes the student and per-question score columns."""
        responses = _graded_responses(tmp_path)
        qids = grade_columns(responses)
        out = tmp_path / "grades.csv"
        export_grades_to_csv(responses, qids, None, out)
        text = out.read_text(encoding="utf-8")
        assert "student" in text.splitlines()[0]
        assert "q1" in text.splitlines()[0]
        assert "alice" in text

    def test_export_grades_to_json(self, tmp_path: Path) -> None:
        """Graded JSON exposes the flat grade row."""
        responses = _graded_responses(tmp_path)
        qids = grade_columns(responses)
        out = tmp_path / "grades.json"
        export_grades_to_json(responses, qids, None, out)
        rows = json.loads(out.read_text(encoding="utf-8"))
        assert rows[0][FLAT_STUDENT] == "alice"
        assert rows[0]["q1"] == GRADED_Q1_SCORE

    def test_export_grades_to_jsonl(self, tmp_path: Path) -> None:
        """Graded JSONL writes one grade row per line."""
        responses = _graded_responses(tmp_path)
        qids = grade_columns(responses)
        out = tmp_path / "grades.jsonl"
        export_grades_to_jsonl(responses, qids, None, out)
        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == len(responses)
        assert json.loads(lines[0])[FLAT_STUDENT] == "alice"
