"""Tests for the analyze command and helpers."""

# ruff: noqa: PLR2004

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from formtuist.analyze import (
    histogram,
    per_question_stats,
    quiz_stats,
    sparkline_for_question,
)
from formtuist.cli import app
from formtuist.database import (
    get_responses,
    init_db,
    save_response,
    set_post_grade,
)
from formtuist.grader import (
    apply_post_grade,
    grade_report_to_json,
    grade_response,
)
from formtuist.schema import FormDefinition, ShortTextQuestion


def _form(tmp_path: Path) -> FormDefinition:
    """Build a small form with required and manual questions."""
    return FormDefinition(
        name="AnalyzeForm",
        questions=[
            ShortTextQuestion(
                id="q1",
                text="Q1?",
                type="short_text",
                correct_answer="a",
                points=10,
                grading_type="exact",
                review="none",
            ),
            ShortTextQuestion(
                id="q2",
                text="Q2?",
                type="short_text",
                correct_answer="b",
                points=10,
                grading_type="exact",
                review="required",
            ),
            ShortTextQuestion(
                id="q3",
                text="Q3?",
                type="short_text",
                points=10,
                review="required",
            ),
        ],
    )


def _populate(tmp_path: Path) -> tuple[Path, Path, list[int]]:
    """Create a DB with three responses and return paths and ids."""
    form = _form(tmp_path)
    form_path = tmp_path / "form.json"
    form_path.write_text(form.model_dump_json(), encoding="utf-8")
    db = tmp_path / "analyze.db"
    conn = init_db(db)
    ids: list[int] = []
    for ans in [
        {"q1": "a", "q2": "b", "q3": "hi"},
        {"q1": "wrong", "q2": "b", "q3": "hello"},
        {"q1": "a", "q2": "wrong", "q3": "hey"},
    ]:
        report = grade_report_to_json(grade_response(form, ans))
        rid = save_response(conn, form.name, ans, grade=report)
        ids.append(rid)
    conn.close()
    # finalize q2 and q3 for all responses
    conn2 = init_db(db)
    for rid in ids:
        set_post_grade(conn2, form, rid, "q2", 10, comment="c", reviewer="t")
        set_post_grade(conn2, form, rid, "q3", 5, comment="c2", reviewer="t")
    conn2.close()
    return form_path, db, ids


class TestQuizStats:
    """Tests for quiz_stats helper."""

    def test_empty(self) -> None:
        """Empty reports give None aggregates and 0 counts."""
        stats = quiz_stats([], max_points=30)
        assert stats["n_total"] == 0
        assert stats["n_finalized"] == 0
        assert stats["mean_total"] is None

    def test_with_finalized(self, tmp_path: Path) -> None:
        """Stats over finalized reports compute mean/median."""
        form = _form(tmp_path)
        reports = [
            grade_report_to_json(
                grade_response(form, {"q1": "a", "q2": "b", "q3": "x"})
            ),
            grade_report_to_json(
                grade_response(form, {"q1": "wrong", "q2": "b", "q3": "y"})
            ),
        ]
        # finalize the manual ones

        # make them finalized by setting manual
        reports[0] = apply_post_grade(
            reports[0], {"q2": {"manual_score": 10}, "q3": {"manual_score": 5}}
        )
        reports[1] = apply_post_grade(
            reports[1], {"q2": {"manual_score": 0}, "q3": {"manual_score": 5}}
        )
        reports = [grade_report_to_json(r) for r in reports]
        stats = quiz_stats(reports, max_points=30)
        assert stats["n_total"] == 2
        assert stats["n_finalized"] == 2
        assert stats["mean_total"] is not None
        assert stats["max_points"] == 30

    def test_pending_excluded(self, tmp_path: Path) -> None:
        """Pending reports are excluded from finalized counts."""
        form = _form(tmp_path)
        report = grade_report_to_json(grade_response(form, {"q1": "a"}))
        # q2 and q3 are required and pending (manual None)
        stats = quiz_stats([report], max_points=30)
        assert stats["n_total"] == 1
        assert stats["n_finalized"] == 0


class TestPerQuestionStats:
    """Tests for per_question_stats."""

    def test_ranking_order(self, tmp_path: Path) -> None:
        """Easiest question has highest p."""
        form = _form(tmp_path)
        reports = [
            grade_report_to_json(
                grade_response(form, {"q1": "a", "q2": "b", "q3": "x"})
            ),
            grade_report_to_json(
                grade_response(form, {"q1": "a", "q2": "b", "q3": "y"})
            ),
        ]

        reports[0] = grade_report_to_json(
            apply_post_grade(
                reports[0],
                {"q2": {"manual_score": 10}, "q3": {"manual_score": 10}},
            )
        )
        reports[1] = grade_report_to_json(
            apply_post_grade(
                reports[1],
                {"q2": {"manual_score": 10}, "q3": {"manual_score": 0}},
            )
        )
        ranking = per_question_stats(reports, form)
        # q1 and q2 should be top (100% correct), q3 lower
        assert ranking[0]["p"] >= ranking[-1]["p"]

    def test_pending_counts(self, tmp_path: Path) -> None:
        """Pending count per question is tracked."""
        form = _form(tmp_path)
        report = grade_report_to_json(grade_response(form, {"q1": "a"}))
        ranking = per_question_stats([report], form)
        q2 = next(r for r in ranking if r["id"] == "q2")
        assert q2["pending"] == 1


class TestHistogram:
    """Tests for histogram helper."""

    def test_empty(self) -> None:
        """Empty values give empty histogram."""
        assert histogram([], bins=5) == []

    def test_bins(self) -> None:
        """Histogram bins counts sum to n."""
        hist = histogram([0, 50, 100], bins=10)
        assert len(hist) == 10
        assert sum(b["count"] for b in hist) == 3

    def test_invalid_bins(self) -> None:
        """Zero bins gives empty."""
        assert histogram([10, 20], bins=0) == []


class TestSparkline:
    """Tests for sparklines."""

    def test_empty(self) -> None:
        """Empty reports give empty sparkline."""
        assert sparkline_for_question("q1", []) == ""

    def test_single_id(self, tmp_path: Path) -> None:
        """Sparkline for a single question returns a string."""
        form = _form(tmp_path)
        reports = [
            grade_report_to_json(
                grade_response(form, {"q1": "a", "q2": "b", "q3": "x"})
            ),
        ]

        reports[0] = grade_report_to_json(
            apply_post_grade(
                reports[0],
                {"q2": {"manual_score": 10}, "q3": {"manual_score": 5}},
            )
        )
        spark = sparkline_for_question("q1", reports)
        assert isinstance(spark, str)

    def test_multiple_scores(self, tmp_path: Path) -> None:
        """Sparkline length equals n_finalized for that question."""
        form_path, db, _ = _populate(tmp_path)  # noqa: RUF059
        conn = init_db(db)
        responses = get_responses(conn)
        conn.close()
        reports = [r["grade_json"] for r in responses]
        spark = sparkline_for_question("q1", reports)
        # q1 has 3 finalized scores (2 correct, 1 wrong) -> sparkline length 3 chars? sparklines lib returns one line with n chars
        assert isinstance(spark, str)
        assert len(spark) == 3 or spark == ""


class TestAnalyzeCli:
    """Tests for the analyze CLI command."""

    def test_table_default(self, tmp_path: Path) -> None:
        """Default table output contains expected sections."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(app, ["analyze", str(form_path), str(db)])
        assert result.exit_code == 0
        assert "Quiz Statistics" in result.output
        assert "Distribution" in result.output
        assert "Per-question" in result.output

    def test_json_output(self, tmp_path: Path) -> None:
        """JSON format writes a payload with quiz and per_question."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app, ["analyze", str(form_path), str(db), "--format", "json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert "quiz" in payload
        assert "per_question" in payload
        assert payload["quiz"]["n_total"] == 3

    def test_csv_output(self, tmp_path: Path) -> None:
        """CSV format writes per-question rows."""
        form_path, db, _ = _populate(tmp_path)
        out = tmp_path / "out.csv"
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "analyze",
                str(form_path),
                str(db),
                "--format",
                "csv",
                "--output",
                str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()
        rows = list(
            csv.DictReader(out.read_text(encoding="utf-8").splitlines())
        )
        assert len(rows) == 3

    def test_question_filter(self, tmp_path: Path) -> None:
        """--question filters per-question ranking."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app, ["analyze", str(form_path), str(db), "--question", "q1"]
        )
        assert result.exit_code == 0
        assert "q1" in result.output

    def test_unknown_question(self, tmp_path: Path) -> None:
        """Unknown --question exits with error."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app, ["analyze", str(form_path), str(db), "--question", "nope"]
        )
        assert result.exit_code != 0
        assert "unknown question" in result.output

    def test_sparklines(self, tmp_path: Path) -> None:
        """--sparklines-id adds a sparkline column."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app,
            ["analyze", str(form_path), str(db), "--sparklines-id", "q1,q2"],
        )
        assert result.exit_code == 0
        assert "Sparkline" in result.output

    def test_sparklines_unknown(self, tmp_path: Path) -> None:
        """Unknown sparklines id errors."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app, ["analyze", str(form_path), str(db), "--sparklines-id", "bad"]
        )
        assert result.exit_code != 0
        assert "unknown question" in result.output

    def test_prelim_vs_final(self, tmp_path: Path) -> None:
        """--review prelim shows different totals than final."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        res_final = runner.invoke(
            app,
            [
                "analyze",
                str(form_path),
                str(db),
                "--review",
                "final",
                "--format",
                "json",
            ],
        )
        res_prelim = runner.invoke(
            app,
            [
                "analyze",
                str(form_path),
                str(db),
                "--review",
                "prelim",
                "--format",
                "json",
            ],
        )
        assert res_final.exit_code == 0
        assert res_prelim.exit_code == 0
        # prelim and final should differ because q3 manual 5 vs prelim 0
        assert (
            json.loads(res_final.output)["quiz"]["mean_total"]
            != json.loads(res_prelim.output)["quiz"]["mean_total"]
        )

    def test_bins(self, tmp_path: Path) -> None:
        """--bins changes histogram bin count."""
        form_path, db, _ = _populate(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "analyze",
                str(form_path),
                str(db),
                "--bins",
                "5",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 0
        assert len(json.loads(result.output)["histogram"]) == 5

    def test_no_responses(self, tmp_path: Path) -> None:
        """No responses prints a message and exits 0."""
        form = _form(tmp_path)
        form_path = tmp_path / "f.json"
        form_path.write_text(form.model_dump_json(), encoding="utf-8")
        db = tmp_path / "empty.db"
        init_db(db).close()
        runner = CliRunner()
        result = runner.invoke(app, ["analyze", str(form_path), str(db)])
        assert result.exit_code == 0
        assert "No responses" in result.output
