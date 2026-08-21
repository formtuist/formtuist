"""Tests for the post-grade manual review feature."""

# ruff: noqa: PLR2004
import asyncio
import csv
import getpass
import json
from pathlib import Path

import pytest
from textual.app import App
from typer.testing import CliRunner

from formtuist.cli import app
from formtuist.database import (
    get_responses,
    init_db,
    list_pending,
    save_response,
    set_post_grade,
)
from formtuist.exporter import (
    FLAT_FINAL_TOTAL,
    FLAT_PENDING_COUNT,
    METADATA_COLUMNS,
    flatten_grades,
    flatten_response,
    grade_columns,
    pending_columns,
)
from formtuist.grader import (
    BREAKDOWN_ID_KEY,
    COMMENT_KEY,
    FINAL_SCORE_KEY,
    MANUAL_SCORE_KEY,
    NEEDS_REVIEW_KEY,
    PERCENTAGE_FINAL_KEY,
    REVIEWED_BY_KEY,
    TOTAL_FINAL_KEY,
    apply_post_grade,
    finalize_report,
    grade_report_to_json,
    grade_response,
    has_gradeable_questions,
    is_pending,
    refresh_prelim,
)
from formtuist.schema import FormConfig, FormDefinition, ShortTextQuestion


def _form_with_review(tmp_path: Path) -> FormDefinition:
    """Build a form with required and permitted review questions."""
    return FormDefinition(
        name="ReviewForm",
        questions=[
            ShortTextQuestion(
                id="q1",
                text="Explain?",
                type="short_text",
                correct_answer="answer",
                points=10,
                grading_type="exact",
                review="required",
            ),
            ShortTextQuestion(
                id="q2",
                text="Optional?",
                type="short_text",
                correct_answer="ok",
                points=5,
                grading_type="exact",
                review="permitted",
            ),
            ShortTextQuestion(
                id="q3",
                text="Manual?",
                type="short_text",
                points=15,
                review="required",
            ),
        ],
    )


def _manual_form() -> FormDefinition:
    """Form with a manual-only question and no correct answer."""
    return FormDefinition(
        name="ManualForm",
        questions=[
            ShortTextQuestion(
                id="m1",
                text="Essay?",
                type="short_text",
                points=10,
                review="required",
            )
        ],
    )


class TestSchemaReview:
    """Tests for the review enum validation."""

    def test_permitted_requires_correct_answer(self) -> None:
        """Permitted review without a correct answer is rejected."""
        with pytest.raises(Exception, match="review permitted"):
            ShortTextQuestion(
                id="q",
                text="T?",
                type="short_text",
                points=10,
                review="permitted",
            )

    def test_required_allows_no_correct_answer(self) -> None:
        """Required review without a correct answer is accepted."""
        q = ShortTextQuestion(
            id="q", text="T?", type="short_text", points=10, review="required"
        )
        assert q.review == "required"

    def test_required_with_correct_answer(self) -> None:
        """Required review with a correct answer is accepted."""
        q = ShortTextQuestion(
            id="q",
            text="T?",
            type="short_text",
            correct_answer="a",
            points=10,
            grading_type="exact",
            review="required",
        )
        assert q.review == "required"

    def test_auto_grade_with_required(self) -> None:
        """auto_grade counts a required review question as gradeable."""
        form = FormDefinition(
            name="F",
            config=FormConfig(auto_grade=True),
            questions=[
                ShortTextQuestion(
                    id="m1",
                    text="Essay?",
                    type="short_text",
                    points=10,
                    review="required",
                )
            ],
        )
        assert form.config.auto_grade is True


class TestHasGradeable:
    """Tests for has_gradeable_questions with review."""

    def test_required_without_correct_is_gradeable(self) -> None:
        """A required manual question makes has_gradeable true."""
        form = _manual_form()
        assert has_gradeable_questions(form) is True

    def test_none_not_gradeable(self) -> None:
        """A form with review none and no correct is not gradeable."""
        form = FormDefinition(
            name="F",
            questions=[
                ShortTextQuestion(
                    id="q", text="T?", type="short_text", points=10
                )
            ],
        )
        assert has_gradeable_questions(form) is False


class TestGraderReview:
    """Tests for prelim→final grading with review."""

    def test_grade_response_required_pending(self, tmp_path: Path) -> None:
        """Required questions get needs_review and prelim 0 for manual."""
        form = _manual_form()
        report = grade_response(form, {"m1": "hello"})
        assert len(report["breakdown"]) == 1
        entry = report["breakdown"][0]
        assert entry[NEEDS_REVIEW_KEY] is True
        assert entry[MANUAL_SCORE_KEY] is None
        assert entry[BREAKDOWN_ID_KEY] == "m1"
        assert report["total"] == 0
        assert TOTAL_FINAL_KEY in report

    def test_grade_response_required_with_correct(
        self, tmp_path: Path
    ) -> None:
        """Required with correct answer still gets prelim and needs_review."""
        form = _form_with_review(tmp_path)
        report = grade_response(form, {"q1": "answer"})
        q1 = next(e for e in report["breakdown"] if e["id"] == "q1")
        assert q1[NEEDS_REVIEW_KEY] is True
        assert q1["score"] == 10

    def test_is_pending(self, tmp_path: Path) -> None:
        """is_pending detects unset manual scores."""
        form = _manual_form()
        report = grade_response(form, {"m1": "x"})
        assert is_pending(report) is True
        fixed = apply_post_grade(
            report, {"m1": {"manual_score": 7, "comment": "ok"}}
        )
        assert is_pending(fixed) is False

    def test_apply_post_grade(self, tmp_path: Path) -> None:
        """apply_post_grade sets manual, final, comment, reviewer."""
        form = _manual_form()
        report = grade_response(form, {"m1": "x"})
        updated = apply_post_grade(
            report,
            {"m1": {"manual_score": 8, "comment": "good", "reviewer": "prof"}},
        )
        entry = updated["breakdown"][0]
        assert entry[MANUAL_SCORE_KEY] == 8
        assert entry[FINAL_SCORE_KEY] == 8
        assert entry[COMMENT_KEY] == "good"
        assert entry["reviewed_by"] == "prof"
        assert entry["reviewed_at"] is not None
        assert updated[TOTAL_FINAL_KEY] == 8
        assert updated[PERCENTAGE_FINAL_KEY] == 80.0

    def test_apply_overwrites(self, tmp_path: Path) -> None:
        """Re-applying overwrites previous manual values."""
        form = _manual_form()
        report = grade_response(form, {"m1": "x"})
        first = apply_post_grade(report, {"m1": {"manual_score": 5}})
        second = apply_post_grade(first, {"m1": {"manual_score": 9}})
        assert second["breakdown"][0][MANUAL_SCORE_KEY] == 9
        assert second[TOTAL_FINAL_KEY] == 9

    def test_finalize_report(self, tmp_path: Path) -> None:
        """finalize_report recomputes final totals."""
        form = _manual_form()
        report = grade_response(form, {"m1": "x"})
        report["breakdown"][0][MANUAL_SCORE_KEY] = 6
        report["breakdown"][0][FINAL_SCORE_KEY] = 6
        fin = finalize_report(report)
        assert fin[TOTAL_FINAL_KEY] == 6

    def test_refresh_prelim_preserves_manual(self, tmp_path: Path) -> None:
        """refresh_prelim keeps manual when recomputing prelim."""
        form = _form_with_review(tmp_path)
        report = grade_response(form, {"q1": "answer", "q3": "hello"})
        patched = apply_post_grade(report, {"q1": {"manual_score": 5}})
        refreshed = refresh_prelim(
            patched, form, {"q1": "wrong", "q3": "hello"}
        )
        q1 = next(e for e in refreshed["breakdown"] if e["id"] == "q1")
        # prelim changed to 0 (wrong) but final stays 5
        assert q1["score"] == 0
        assert q1[FINAL_SCORE_KEY] == 5
        assert q1[MANUAL_SCORE_KEY] == 5

    def test_grade_report_to_json_round_trip(self, tmp_path: Path) -> None:
        """Snapshot survives a JSON round trip with new keys."""
        form = _manual_form()
        report = grade_response(form, {"m1": "x"})
        report = apply_post_grade(report, {"m1": {"manual_score": 7}})
        snap = grade_report_to_json(report)
        assert snap[TOTAL_FINAL_KEY] == 7
        assert snap["breakdown"][0][MANUAL_SCORE_KEY] == 7
        assert json.loads(json.dumps(snap)) == snap


class TestDatabasePostGrade:
    """Tests for set_post_grade, get_final_report, list_pending."""

    def test_set_and_list_pending(self, tmp_path: Path) -> None:
        """Manual scores persist and clear pending."""
        form = _manual_form()
        db = tmp_path / "db.db"
        conn = init_db(db)

        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))

        rid = save_response(conn, form.name, {"m1": "hi"}, grade=report)
        pending = list_pending(conn, form.name)
        assert len(pending) == 1
        set_post_grade(
            conn, form, rid, "m1", 9, comment="nice", reviewer="prof"
        )
        pending2 = list_pending(conn, form.name)
        assert len(pending2) == 0
        pending_q = list_pending(conn, form.name, question_id="m1")
        assert len(pending_q) == 0
        conn.close()

    def test_bounds_validation(self, tmp_path: Path) -> None:
        """Out-of-range manual_score is rejected."""
        form = _manual_form()
        db = tmp_path / "db.db"
        conn = init_db(db)

        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))
        rid = save_response(conn, form.name, {"m1": "hi"}, grade=report)
        with pytest.raises(ValueError, match="out of range"):
            set_post_grade(conn, form, rid, "m1", 20)
        with pytest.raises(ValueError, match="unknown question"):
            set_post_grade(conn, form, rid, "nope", 5)
        conn.close()

    def test_re_review_overwrites(self, tmp_path: Path) -> None:
        """Re-review overwrites the previous score and comment."""
        form = _manual_form()
        db = tmp_path / "db.db"
        conn = init_db(db)

        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))
        rid = save_response(conn, form.name, {"m1": "hi"}, grade=report)
        set_post_grade(conn, form, rid, "m1", 5, comment="first")
        set_post_grade(conn, form, rid, "m1", 8, comment="second")
        from formtuist.database import get_responses  # noqa: PLC0415

        resp = get_responses(conn)[0]
        entry = resp["grade_json"]["breakdown"][0]
        assert entry[MANUAL_SCORE_KEY] == 8
        assert entry[COMMENT_KEY] == "second"
        conn.close()


class TestExporterPostGrade:
    """Tests for exporter final columns and pending helpers."""

    def test_flatten_response_final(self, tmp_path: Path) -> None:
        """flatten_response includes final_total and pending."""
        form = _manual_form()
        db = tmp_path / "db.db"
        conn = init_db(db)

        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))
        save_response(conn, form.name, {"m1": "hi"}, grade=report)
        resp = get_responses(conn)[0]
        row = flatten_response(resp, ["m1"])
        assert row[FLAT_FINAL_TOTAL] == 0
        assert row[FLAT_PENDING_COUNT] == 1
        conn.close()

    def test_flatten_grades_final_and_comment(self, tmp_path: Path) -> None:
        """flatten_grades uses final_score and exposes comment."""
        form = _manual_form()
        db = tmp_path / "db.db"
        conn = init_db(db)

        report = grade_response(form, {"m1": "hi"})
        report = apply_post_grade(
            report, {"m1": {"manual_score": 7, "comment": "good"}}
        )
        snap = grade_report_to_json(report)
        save_response(conn, form.name, {"m1": "hi"}, grade=snap)
        responses = get_responses(conn)
        qids = grade_columns(responses, form)
        rows = flatten_grades(responses, qids)
        assert rows[0]["m1"] == 7
        assert rows[0]["m1_comment"] == "good"
        assert rows[0][FLAT_PENDING_COUNT] == 0
        conn.close()

    def test_pending_columns(self, tmp_path: Path) -> None:
        """pending_columns returns ids with pending reviews."""
        form = _manual_form()
        db = tmp_path / "db.db"
        conn = init_db(db)

        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))
        save_response(conn, form.name, {"m1": "hi"}, grade=report)
        responses = get_responses(conn)
        assert pending_columns(responses) == ["m1"]
        conn.close()

    def test_metadata_columns_include_final(self) -> None:
        """METADATA_COLUMNS contains final and pending fields."""
        assert FLAT_FINAL_TOTAL in METADATA_COLUMNS
        assert FLAT_PENDING_COUNT in METADATA_COLUMNS


class TestCliReviewBatch:
    """Tests for the review CLI batch mode."""

    def test_batch_applies_scores(self, tmp_path: Path) -> None:
        """Batch CSV applies manual scores via set_post_grade."""
        form = _manual_form()
        # write a minimal form file
        form_path = tmp_path / "form.json"
        form_path.write_text(form.model_dump_json(), encoding="utf-8")
        db = tmp_path / "batch.db"
        conn = init_db(db)

        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))
        rid = save_response(conn, form.name, {"m1": "hi"}, grade=report)
        conn.close()
        # write batch csv
        batch = tmp_path / "overrides.csv"
        with batch.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "response_id",
                    "question_id",
                    "manual_score",
                    "comment",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "response_id": rid,
                    "question_id": "m1",
                    "manual_score": "8",
                    "comment": "batch",
                }
            )
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "review",
                str(form_path),
                str(db),
                "--batch",
                str(batch),
                "--reviewer",
                "tester",
            ],
        )
        assert result.exit_code == 0
        # rich and textual may emit ANSI codes or write to
        # either stdout/stderr depending on console detection;
        # use the combined output stream for a stable check
        assert "Applied 1" in result.output
        conn2 = init_db(db)
        resp = get_responses(conn2)[0]
        assert resp["grade_json"]["breakdown"][0][MANUAL_SCORE_KEY] == 8
        assert resp["grade_json"]["breakdown"][0][COMMENT_KEY] == "batch"
        conn2.close()

    def test_batch_reviewer_defaults_to_local_user(
        self, tmp_path: Path
    ) -> None:
        """Batch without --reviewer records the local OS username."""
        form = _manual_form()
        form_path = tmp_path / "form.json"
        form_path.write_text(form.model_dump_json(), encoding="utf-8")
        db = tmp_path / "batch.db"
        conn = init_db(db)
        report = grade_report_to_json(grade_response(form, {"m1": "hi"}))
        rid = save_response(conn, form.name, {"m1": "hi"}, grade=report)
        conn.close()
        batch = tmp_path / "overrides.csv"
        with batch.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "response_id",
                    "question_id",
                    "manual_score",
                ],
            )
            w.writeheader()
            w.writerow(
                {
                    "response_id": rid,
                    "question_id": "m1",
                    "manual_score": "8",
                }
            )
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "review",
                str(form_path),
                str(db),
                "--batch",
                str(batch),
            ],
        )
        assert result.exit_code == 0
        assert "Applied 1" in result.output
        conn2 = init_db(db)
        resp = get_responses(conn2)[0]
        assert (
            resp["grade_json"]["breakdown"][0][REVIEWED_BY_KEY]
            == getpass.getuser()
        )
        conn2.close()

    def test_review_interactive_exits_without_form(
        self, tmp_path: Path
    ) -> None:
        """Review with an invalid form path exits with error."""
        runner = CliRunner()
        result = runner.invoke(app, ["review", "nope.json", "nope.db"])
        assert result.exit_code != 0


class TestTuiReview:
    """Smoke tests for the reviewer TUI."""

    def test_review_screen_instantiates(self, tmp_path: Path) -> None:
        """ReviewScreen can be instantiated with required questions."""
        form = _manual_form()
        db = tmp_path / "tui.db"
        init_db(db).close()
        from formtuist.tui.review import ReviewScreen  # noqa: PLC0415

        screen = ReviewScreen(form, db, review_type="required")
        assert len(screen.reviewable_questions) == 1

    def test_review_app_instantiates(self, tmp_path: Path) -> None:
        """ReviewApp can be instantiated without error."""
        form = _manual_form()
        form_path = tmp_path / "f.json"
        form_path.write_text(form.model_dump_json(), encoding="utf-8")
        db = tmp_path / "tui2.db"
        init_db(db).close()
        from formtuist.tui.app import ReviewApp  # noqa: PLC0415

        app_inst = ReviewApp(form_path, db, review_type="required")
        assert app_inst.form.name == "ManualForm"

    def test_review_toggles_sidebar(self, tmp_path: Path) -> None:
        """action_toggle_sidebar hides and shows the review sidebar."""
        form = _manual_form()
        db = tmp_path / "tui_side.db"
        init_db(db).close()
        from formtuist.tui.review import ReviewScreen  # noqa: PLC0415

        async def run() -> None:
            app: App = App()
            async with app.run_test():
                screen = ReviewScreen(form, db, review_type="required")
                await app.push_screen(screen)
                sidebar = screen.query_one("#sidebar")
                assert "hidden" not in sidebar.classes
                screen.action_toggle_sidebar()
                assert "hidden" in sidebar.classes
                screen.action_toggle_sidebar()
                assert "hidden" not in sidebar.classes

        asyncio.run(run())
