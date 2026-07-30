"""Tests for the SQLite database storage layer."""

from pathlib import Path

from formtuitous.database import (
    get_response_count,
    get_responses,
    init_db,
    save_response,
)

EXPECTED_TWO_RESPONSES = 2
EXPECTED_THREE_RESPONSES = 3


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
