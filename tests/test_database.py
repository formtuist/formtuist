"""Tests for the SQLite database storage layer."""

import json
import sqlite3
from pathlib import Path

import pytest

from formtuist.database import (
    DATABASE_FILENAME,
    ensure_db_dir,
    ensure_single_submission_index,
    get_default_db_dir,
    get_response_count,
    get_responses,
    has_submission,
    init_db,
    resolve_db_path,
    save_response,
    update_response_grade,
)

EXPECTED_TWO_RESPONSES = 2
EXPECTED_THREE_RESPONSES = 3
EXPECTED_AGE_VALUE = 22
EXPECTED_GPA_VALUE = 3.75
EXPECTED_FIRST_ID = 1
EXPECTED_SECOND_ID = 2
EXPECTED_THIRD_ID = 3
ATTEMPT_ONE = "attempt-1"
ATTEMPT_TWO = "attempt-2"


class TestInitDb:
    """Tests for database initialisation."""

    def test_init_creates_file(self, tmp_path: Path) -> None:
        """init_db creates a SQLite file at the given path."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        conn.close()
        assert db_path.exists()

    def test_init_creates_table(self, tmp_path: Path) -> None:
        """init_db creates the responses table."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        assert ("responses",) in tables

    def test_init_sets_wal_mode(self, tmp_path: Path) -> None:
        """init_db enables WAL journal mode."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert journal_mode == "wal"

    def test_init_sets_busy_timeout(self, tmp_path: Path) -> None:
        """init_db sets a non-zero busy timeout."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.close()
        assert busy_timeout > 0


class TestSaveResponse:
    """Tests for saving responses."""

    def test_save_returns_row_id(self, tmp_path: Path) -> None:
        """save_response returns the new row id."""
        conn = init_db(tmp_path / "test.db")
        row_id = save_response(conn, "TestForm", {"q1": "answer"})
        conn.close()
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_save_persists_data(self, tmp_path: Path) -> None:
        """Saved data is readable from the database."""
        db_path = tmp_path / "test.db"
        conn = init_db(db_path)
        save_response(conn, "FormA", {"name": "Alice"})
        conn.close()
        conn2 = init_db(db_path)
        rows = conn2.execute("SELECT * FROM responses").fetchall()
        conn2.close()
        assert len(rows) == 1
        assert rows[0][1] == "FormA"

    def test_save_stores_iso_timestamp(self, tmp_path: Path) -> None:
        """save_response stores an ISO 8601 timestamp."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "Form", {"x": 1})
        timestamp = conn.execute(
            "SELECT submitted_at FROM responses"
        ).fetchone()[0]
        conn.close()
        assert "T" in timestamp
        assert timestamp.endswith("+00:00") or "+" in timestamp

    def test_multiple_saves_increment_id(self, tmp_path: Path) -> None:
        """Each save returns a unique increasing row id."""
        conn = init_db(tmp_path / "test.db")
        id1 = save_response(conn, "F", {"a": 1})
        id2 = save_response(conn, "F", {"a": 2})
        id3 = save_response(conn, "F", {"a": 3})
        conn.close()
        assert id1 < id2 < id3


class TestGetResponses:
    """Tests for retrieving responses."""

    def test_get_all_returns_all(self, tmp_path: Path) -> None:
        """get_responses returns every saved response when no filter given."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "A", {"q": "a"})
        save_response(conn, "B", {"q": "b"})
        results = get_responses(conn)
        conn.close()
        assert len(results) == EXPECTED_TWO_RESPONSES

    def test_get_by_form_name(self, tmp_path: Path) -> None:
        """get_responses filters by form name."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "FormX", {"x": 1})
        save_response(conn, "FormY", {"y": 2})
        results = get_responses(conn, form_name="FormX")
        conn.close()
        assert len(results) == 1
        assert results[0]["form_name"] == "FormX"

    def test_get_returns_parsed_json(self, tmp_path: Path) -> None:
        """The answers_json column is returned as a parsed dict."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "F", {"name": "Alice", "age": 30})
        results = get_responses(conn)
        conn.close()
        assert results[0]["answers_json"] == {"name": "Alice", "age": 30}

    def test_get_empty_db(self, tmp_path: Path) -> None:
        """get_responses returns an empty list when no rows exist."""
        conn = init_db(tmp_path / "test.db")
        results = get_responses(conn)
        conn.close()
        assert results == []


class TestGetResponseCount:
    """Tests for counting responses."""

    def test_count_all(self, tmp_path: Path) -> None:
        """get_response_count returns total row count."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "A", {"q": 1})
        save_response(conn, "A", {"q": 2})
        save_response(conn, "B", {"q": 3})
        count = get_response_count(conn)
        conn.close()
        assert count == EXPECTED_THREE_RESPONSES

    def test_count_by_form(self, tmp_path: Path) -> None:
        """get_response_count filters by form name."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "X", {"q": 1})
        save_response(conn, "X", {"q": 2})
        save_response(conn, "Y", {"q": 3})
        count = get_response_count(conn, form_name="X")
        conn.close()
        assert count == EXPECTED_TWO_RESPONSES

    def test_count_empty(self, tmp_path: Path) -> None:
        """get_response_count returns 0 for an empty database."""
        conn = init_db(tmp_path / "test.db")
        count = get_response_count(conn)
        conn.close()
        assert count == 0


class TestConcurrency:
    """Tests for concurrent write safety with WAL mode."""

    def test_two_connections_both_write(self, tmp_path: Path) -> None:
        """Two connections can both write when WAL is active."""
        db_path = tmp_path / "concurrent.db"
        conn_a = init_db(db_path)
        conn_b = init_db(db_path)
        id_a = save_response(conn_a, "F", {"from": "a"})
        id_b = save_response(conn_b, "F", {"from": "b"})
        conn_a.close()
        conn_b.close()
        assert id_a != id_b
        conn = init_db(db_path)
        assert get_response_count(conn) == EXPECTED_TWO_RESPONSES
        conn.close()


class TestDatabaseContent:
    """Verify database content correctness and round-trip fidelity."""

    def test_round_trip_exact_values(self, tmp_path: Path) -> None:
        """Answers saved and retrieved are byte-for-byte identical."""
        conn = init_db(tmp_path / "test.db")
        original = {"name": "Alice", "score": 95, "active": True}
        save_response(conn, "RoundTrip", original)
        results = get_responses(conn)
        conn.close()
        assert len(results) == 1
        assert results[0]["answers_json"] == original

    def test_multiple_saves_same_form_all_present(
        self, tmp_path: Path
    ) -> None:
        """All submissions for the same form are stored and retrievable."""
        conn = init_db(tmp_path / "test.db")
        answers_list = [
            {"q1": "Alice"},
            {"q1": "Bob"},
            {"q1": "Charlie"},
        ]
        for answers in answers_list:
            save_response(conn, "Attendance", answers)
        results = get_responses(conn, form_name="Attendance")
        conn.close()
        assert len(results) == len(answers_list)
        saved_answers = [r["answers_json"] for r in results]
        for expected in answers_list:
            assert expected in saved_answers

    def test_multiple_forms_separate_contents(self, tmp_path: Path) -> None:
        """Responses for different forms are stored independently and separated by form_name."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "Quiz", {"q": "answer", "score": 10})
        save_response(conn, "Survey", {"feedback": "great"})
        save_response(conn, "Quiz", {"q": "other", "score": 8})
        conn.close()
        conn = init_db(tmp_path / "test.db")
        quiz_responses = get_responses(conn, form_name="Quiz")
        survey_responses = get_responses(conn, form_name="Survey")
        all_responses = get_responses(conn)
        conn.close()
        assert len(quiz_responses) == EXPECTED_TWO_RESPONSES
        assert len(survey_responses) == 1
        assert len(all_responses) == EXPECTED_THREE_RESPONSES
        assert survey_responses[0]["answers_json"] == {"feedback": "great"}

    def test_form_name_matches_saved(self, tmp_path: Path) -> None:
        """The form_name column stores the exact name provided."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "CS 101 Exam", {"q": "ok"})
        results = get_responses(conn)
        conn.close()
        assert results[0]["form_name"] == "CS 101 Exam"

    def test_various_data_types_round_trip(self, tmp_path: Path) -> None:
        """Answers with mixed types survive a round trip through the database."""
        conn = init_db(tmp_path / "test.db")
        answers = {
            "name": "Alice",
            "age": EXPECTED_AGE_VALUE,
            "gpa": EXPECTED_GPA_VALUE,
            "enrolled": True,
            "notes": None,
        }
        save_response(conn, "Types", answers)
        results = get_responses(conn)
        conn.close()
        retrieved = results[0]["answers_json"]
        assert retrieved["name"] == "Alice"
        assert retrieved["age"] == EXPECTED_AGE_VALUE
        assert retrieved["gpa"] == EXPECTED_GPA_VALUE
        assert retrieved["enrolled"] is True
        assert retrieved["notes"] is None

    def test_three_saves_incremental_ids(self, tmp_path: Path) -> None:
        """Three saves produce rows with ids 1, 2, 3."""
        conn = init_db(tmp_path / "test.db")
        id1 = save_response(conn, "F", {"n": 1})
        id2 = save_response(conn, "F", {"n": 2})
        id3 = save_response(conn, "F", {"n": 3})
        conn.close()
        assert id1 == EXPECTED_FIRST_ID
        assert id2 == EXPECTED_SECOND_ID
        assert id3 == EXPECTED_THIRD_ID

    def test_get_responses_id_order(self, tmp_path: Path) -> None:
        """Responses are returned in ascending id order."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "Order", {"seq": "first"})
        save_response(conn, "Order", {"seq": "second"})
        save_response(conn, "Order", {"seq": "third"})
        results = get_responses(conn)
        conn.close()
        ids = [r["id"] for r in results]
        assert ids == sorted(ids)

    def test_empty_answers_dict(self, tmp_path: Path) -> None:
        """Saving an empty answers dict works correctly."""
        conn = init_db(tmp_path / "test.db")
        row_id = save_response(conn, "Empty", {})
        results = get_responses(conn)
        conn.close()
        assert len(results) == 1
        assert results[0]["answers_json"] == {}
        assert results[0]["id"] == row_id


class TestDbDirectory:
    """Tests for database directory resolution and platformdirs integration."""

    def test_get_default_db_dir_returns_path(self) -> None:
        """get_default_db_dir returns a Path ending with formtuist."""
        db_dir = get_default_db_dir()
        assert isinstance(db_dir, Path)
        assert "formtuist" in db_dir.parts

    def test_ensure_db_dir_creates_directory(self, tmp_path: Path) -> None:
        """ensure_db_dir creates the directory tree."""
        target = tmp_path / "a" / "b" / "c"
        assert not target.exists()
        ensure_db_dir(target)
        assert target.is_dir()

    def test_ensure_db_dir_idempotent(self, tmp_path: Path) -> None:
        """ensure_db_dir succeeds when the directory already exists."""
        target = tmp_path / "existing"
        target.mkdir(parents=True)
        ensure_db_dir(target)
        assert target.is_dir()

    def test_resolve_db_path_with_dir(self, tmp_path: Path) -> None:
        """resolve_db_path appends DATABASE_FILENAME and creates the dir."""
        db_dir = tmp_path / "my_responses"
        full_path = resolve_db_path(db_dir)
        assert full_path == db_dir / DATABASE_FILENAME
        assert db_dir.is_dir()

    def test_resolve_db_path_defaults(self) -> None:
        """resolve_db_path with no arg uses the platform-appropriate dir."""
        full_path = resolve_db_path()
        assert full_path.name == DATABASE_FILENAME
        assert "formtuist" in full_path.parts

    def test_resolve_db_path_with_name(self, tmp_path: Path) -> None:
        """resolve_db_path uses a custom database name."""
        db_dir = tmp_path / "custom_dir"
        full_path = resolve_db_path(db_dir, "attendance.db")
        assert full_path == db_dir / "attendance.db"
        assert db_dir.is_dir()

    def test_resolve_db_path_with_name_defaults(self) -> None:
        """resolve_db_path with a name uses the platform dir and that name."""
        full_path = resolve_db_path(db_name="quiz.db")
        assert full_path.name == "quiz.db"
        assert "formtuist" in full_path.parts

    def test_resolve_db_path_distinct_names(self, tmp_path: Path) -> None:
        """Two database names resolve to distinct files in the same dir."""
        db_dir = tmp_path / "responses"
        quiz_path = resolve_db_path(db_dir, "quiz.db")
        survey_path = resolve_db_path(db_dir, "survey.db")
        assert quiz_path != survey_path
        assert quiz_path.parent == survey_path.parent


class TestGitHubIdentityColumns:
    """Tests for the GitHub identity columns in the responses table."""

    def test_init_creates_identity_columns(self, tmp_path: Path) -> None:
        """init_db creates the github_username and github_url columns."""
        conn = init_db(tmp_path / "test.db")
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(responses)").fetchall()
        }
        conn.close()
        assert "github_username" in columns
        assert "github_url" in columns

    def test_save_response_stores_identity(self, tmp_path: Path) -> None:
        """save_response stores the GitHub identity on the row."""
        conn = init_db(tmp_path / "test.db")
        save_response(
            conn,
            "FormA",
            {"q1": "answer"},
            github_username="octocat",
            github_url="https://github.com/octocat",
        )
        results = get_responses(conn)
        conn.close()
        assert results[0]["github_username"] == "octocat"
        assert results[0]["github_url"] == "https://github.com/octocat"

    def test_save_response_without_identity(self, tmp_path: Path) -> None:
        """save_response stores NULL identity when not provided."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "FormA", {"q1": "answer"})
        results = get_responses(conn)
        conn.close()
        assert results[0]["github_username"] is None
        assert results[0]["github_url"] is None

    def test_existing_db_gets_identity_columns(self, tmp_path: Path) -> None:
        """An older database is migrated to add the identity columns."""
        db_path = tmp_path / "old.db"
        conn = init_db(db_path)
        conn.execute("DROP TABLE responses")
        conn.execute(
            "CREATE TABLE responses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "form_name TEXT NOT NULL,"
            "submitted_at TEXT NOT NULL,"
            "answers_json TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "INSERT INTO responses (form_name, submitted_at, answers_json)"
            " VALUES ('Old', '2024-01-01', '{}')"
        )
        conn.commit()
        conn.close()
        conn2 = init_db(db_path)
        columns = {
            row[1]
            for row in conn2.execute("PRAGMA table_info(responses)").fetchall()
        }
        results = get_responses(conn2)
        conn2.close()
        assert "github_username" in columns
        assert "github_url" in columns
        assert results[0]["github_username"] is None

    def test_existing_db_gets_attempt_column(self, tmp_path: Path) -> None:
        """An older database is migrated to add the attempt column."""
        db_path = tmp_path / "old.db"
        conn = init_db(db_path)
        conn.execute("DROP TABLE responses")
        conn.execute(
            "CREATE TABLE responses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "form_name TEXT NOT NULL,"
            "submitted_at TEXT NOT NULL,"
            "answers_json TEXT NOT NULL"
            ")"
        )
        conn.commit()
        conn.close()
        conn2 = init_db(db_path)
        columns = {
            row[1]
            for row in conn2.execute("PRAGMA table_info(responses)").fetchall()
        }
        conn2.close()
        assert "attempt_id" in columns


class TestHasSubmission:
    """Tests for duplicate-submission detection."""

    def test_false_when_no_rows(self, tmp_path: Path) -> None:
        """has_submission is false for a fresh identity."""
        conn = init_db(tmp_path / "test.db")
        assert has_submission(conn, "Quiz", ATTEMPT_ONE, "octocat") is False
        conn.close()

    def test_true_after_save(self, tmp_path: Path) -> None:
        """has_submission is true after the identity submits."""
        conn = init_db(tmp_path / "test.db")
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        assert has_submission(conn, "Quiz", ATTEMPT_ONE, "octocat") is True
        conn.close()

    def test_scoped_to_form_name(self, tmp_path: Path) -> None:
        """Submissions to another form do not count against this one."""
        conn = init_db(tmp_path / "test.db")
        save_response(
            conn,
            "Other",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        assert has_submission(conn, "Quiz", ATTEMPT_ONE, "octocat") is False
        conn.close()

    def test_scoped_to_username(self, tmp_path: Path) -> None:
        """Another identity's rows do not count against this one."""
        conn = init_db(tmp_path / "test.db")
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="alice",
            attempt_id=ATTEMPT_ONE,
        )
        assert has_submission(conn, "Quiz", ATTEMPT_ONE, "bob") is False
        conn.close()

    def test_scoped_to_attempt(self, tmp_path: Path) -> None:
        """A re-run with a new attempt id is not treated as a duplicate."""
        conn = init_db(tmp_path / "test.db")
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        assert has_submission(conn, "Quiz", ATTEMPT_TWO, "octocat") is False
        conn.close()

    def test_ignores_null_identity_rows(self, tmp_path: Path) -> None:
        """Anonymous rows never match an identity check."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "Quiz", {"q": "a"})
        assert has_submission(conn, "Quiz", ATTEMPT_ONE, "octocat") is False
        conn.close()


class TestSingleSubmissionIndex:
    """Tests for the per-form unique identity index."""

    def test_blocks_duplicate_identity(self, tmp_path: Path) -> None:
        """The index rejects a second submission by the same identity."""
        conn = init_db(tmp_path / "test.db")
        assert (
            ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE) is True
        )
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        with pytest.raises(sqlite3.IntegrityError):
            save_response(
                conn,
                "Quiz",
                {"q": "b"},
                github_username="octocat",
                attempt_id=ATTEMPT_ONE,
            )
        conn.close()

    def test_permits_different_identity(self, tmp_path: Path) -> None:
        """The index still accepts a second, different identity."""
        conn = init_db(tmp_path / "test.db")
        ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE)
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        save_response(
            conn,
            "Quiz",
            {"q": "b"},
            github_username="alice",
            attempt_id=ATTEMPT_ONE,
        )
        assert get_response_count(conn, "Quiz") == EXPECTED_TWO_RESPONSES
        conn.close()

    def test_scoped_to_form_name(self, tmp_path: Path) -> None:
        """The index does not constrain a different form name."""
        conn = init_db(tmp_path / "test.db")
        ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE)
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        save_response(
            conn,
            "Other",
            {"q": "b"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        assert get_response_count(conn) == EXPECTED_TWO_RESPONSES
        conn.close()

    def test_scoped_to_attempt(self, tmp_path: Path) -> None:
        """A re-run with a new attempt id allows the same identity again."""
        conn = init_db(tmp_path / "test.db")
        ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE)
        ensure_single_submission_index(conn, "Quiz", ATTEMPT_TWO)
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        save_response(
            conn,
            "Quiz",
            {"q": "b"},
            github_username="octocat",
            attempt_id=ATTEMPT_TWO,
        )
        assert get_response_count(conn, "Quiz") == EXPECTED_TWO_RESPONSES
        conn.close()

    def test_idempotent_recreation(self, tmp_path: Path) -> None:
        """Creating the index twice is harmless."""
        conn = init_db(tmp_path / "test.db")
        assert (
            ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE) is True
        )
        assert (
            ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE) is True
        )
        conn.close()

    def test_legacy_duplicates_skip_index(self, tmp_path: Path) -> None:
        """Databases with duplicates cannot take the index and return False."""
        conn = init_db(tmp_path / "test.db")
        save_response(
            conn,
            "Quiz",
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        save_response(
            conn,
            "Quiz",
            {"q": "b"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        assert (
            ensure_single_submission_index(conn, "Quiz", ATTEMPT_ONE) is False
        )
        conn.close()

    def test_form_name_with_quote(self, tmp_path: Path) -> None:
        """A form name containing a quote is safely embedded in the index."""
        conn = init_db(tmp_path / "test.db")
        name = "Quiz O'Brien"
        assert ensure_single_submission_index(conn, name, ATTEMPT_ONE) is True
        save_response(
            conn,
            name,
            {"q": "a"},
            github_username="octocat",
            attempt_id=ATTEMPT_ONE,
        )
        with pytest.raises(sqlite3.IntegrityError):
            save_response(
                conn,
                name,
                {"q": "b"},
                github_username="octocat",
                attempt_id=ATTEMPT_ONE,
            )
        conn.close()


class TestGradeColumn:
    """Tests for the grade_json column on the responses table."""

    def test_init_creates_grade_column(self, tmp_path: Path) -> None:
        """init_db creates the grade_json column."""
        conn = init_db(tmp_path / "test.db")
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(responses)").fetchall()
        }
        conn.close()
        assert "grade_json" in columns

    def test_save_response_stores_grade(self, tmp_path: Path) -> None:
        """save_response stores a JSON-safe grade snapshot."""
        conn = init_db(tmp_path / "test.db")
        grade = {
            "total": 10,
            "max": 20,
            "percentage": 50.0,
            "breakdown": [
                {"id": "q1", "score": 10, "max": 10, "correct": True}
            ],
            "graded_at": "2026-08-01T00:00:00+00:00",
        }
        save_response(conn, "Quiz", {"q1": "a"}, grade=grade)
        results = get_responses(conn)
        conn.close()
        assert results[0]["grade_json"] == grade

    def test_save_response_without_grade(self, tmp_path: Path) -> None:
        """save_response stores NULL grade when not provided."""
        conn = init_db(tmp_path / "test.db")
        save_response(conn, "FormA", {"q1": "answer"})
        results = get_responses(conn)
        conn.close()
        assert results[0]["grade_json"] is None

    def test_existing_db_gets_grade_column(self, tmp_path: Path) -> None:
        """An older database is migrated to add the grade column."""
        db_path = tmp_path / "old.db"
        conn = init_db(db_path)
        conn.execute("DROP TABLE responses")
        conn.execute(
            "CREATE TABLE responses ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "form_name TEXT NOT NULL,"
            "submitted_at TEXT NOT NULL,"
            "answers_json TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "INSERT INTO responses (form_name, submitted_at, answers_json)"
            " VALUES ('Old', '2024-01-01', '{}')"
        )
        conn.commit()
        conn.close()
        conn2 = init_db(db_path)
        columns = {
            row[1]
            for row in conn2.execute("PRAGMA table_info(responses)").fetchall()
        }
        results = get_responses(conn2)
        conn2.close()
        assert "grade_json" in columns
        assert results[0]["grade_json"] is None

    def test_update_response_grade_replaces_snapshot(
        self, tmp_path: Path
    ) -> None:
        """update_response_grade overwrites the stored grade snapshot."""
        conn = init_db(tmp_path / "test.db")
        row_id = save_response(conn, "Quiz", {"q1": "a"})
        first = {"total": 10, "max": 10, "percentage": 100.0}
        second = {"total": 0, "max": 10, "percentage": 0.0}
        update_response_grade(conn, row_id, first)
        update_response_grade(conn, row_id, second)
        results = get_responses(conn)
        conn.close()
        assert results[0]["grade_json"]["total"] == 0

    def test_update_response_grade_round_trip(self, tmp_path: Path) -> None:
        """An updated snapshot survives a JSON round trip."""
        conn = init_db(tmp_path / "test.db")
        row_id = save_response(conn, "Quiz", {"q1": "a"})
        grade = {
            "total": 8,
            "max": 10,
            "percentage": 80.0,
            "breakdown": [{"id": "q1", "score": 8, "correct": False}],
        }
        update_response_grade(conn, row_id, grade)
        results = get_responses(conn)
        conn.close()
        assert json.loads(json.dumps(results[0]["grade_json"])) == grade
