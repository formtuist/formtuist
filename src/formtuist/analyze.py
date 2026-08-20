"""Statistics helpers for the analyze command."""

import math
import statistics
from typing import Any

from formtuist.grader import (
    BREAKDOWN_ID_KEY,
    BREAKDOWN_MAX_KEY,
    BREAKDOWN_SCORE_KEY,
    FINAL_SCORE_KEY,
    MANUAL_SCORE_KEY,
    NEEDS_REVIEW_KEY,
    PERCENTAGE_FINAL_KEY,
    TOTAL_FINAL_KEY,
    is_pending,
)
from formtuist.schema import FormDefinition

# histogram bin labels
HISTOGRAM_RANGE_LABEL = "{low:g}-{high:g}"


def quiz_stats(
    reports: list[dict[str, Any]], max_points: int
) -> dict[str, Any]:
    """Return quiz-level aggregates over finalized reports."""
    n_total = len(reports)
    finalized = [r for r in reports if not is_pending(r)]
    n_finalized = len(finalized)
    if n_finalized == 0:
        return {
            "n_total": n_total,
            "n_finalized": 0,
            "mean_total": None,
            "median_total": None,
            "mean_percentage": None,
            "median_percentage": None,
            "stdev_total": None,
            "stdev_percentage": None,
            "min_total": None,
            "max_total": None,
            "min_percentage": None,
            "max_percentage": None,
            "q1_total": None,
            "q3_total": None,
            "q1_percentage": None,
            "q3_percentage": None,
            "max_points": max_points,
        }
    totals = [r.get(TOTAL_FINAL_KEY, r["total"]) for r in finalized]
    percentages = [
        r.get(PERCENTAGE_FINAL_KEY, r["percentage"]) for r in finalized
    ]
    return {
        "n_total": n_total,
        "n_finalized": n_finalized,
        "mean_total": statistics.mean(totals),  # type: ignore[arg-type]
        "median_total": statistics.median(totals),  # type: ignore[arg-type]
        "mean_percentage": statistics.mean(percentages),  # type: ignore[arg-type]
        "median_percentage": statistics.median(percentages),  # type: ignore[arg-type]
        "stdev_total": statistics.pstdev(totals)  # type: ignore[arg-type]
        if len(totals) > 1
        else 0.0,
        "stdev_percentage": statistics.pstdev(percentages)  # type: ignore[arg-type]
        if len(percentages) > 1
        else 0.0,
        "min_total": min(totals),  # type: ignore[arg-type]
        "max_total": max(totals),  # type: ignore[arg-type]
        "min_percentage": min(percentages),  # type: ignore[arg-type]
        "max_percentage": max(percentages),  # type: ignore[arg-type]
        "q1_total": _quantile(totals, 0.25),  # type: ignore[arg-type]
        "q3_total": _quantile(totals, 0.75),  # type: ignore[arg-type]
        "q1_percentage": _quantile(percentages, 0.25),  # type: ignore[arg-type]
        "q3_percentage": _quantile(percentages, 0.75),  # type: ignore[arg-type]
        "max_points": max_points,
    }


def per_question_stats(
    reports: list[dict[str, Any]], form: FormDefinition
) -> list[dict[str, Any]]:
    """Return per-question difficulty ranking over finalized reports."""
    from formtuist.exporter import grade_columns  # noqa: PLC0415

    gradeable_ids = grade_columns(reports, form)  # type: ignore[arg-type]
    # fallback to form order when reports empty
    if not gradeable_ids:
        gradeable_ids = [
            q.id  # type: ignore[union-attr]
            for q in form.questions
            if getattr(q, "correct_answer", None) is not None
            or getattr(q, "review", "none") == "required"
        ]
    # map question id to points
    points_by_id: dict[str, int] = {
        q.id: getattr(q, "points", 0)  # type: ignore[union-attr]
        for q in form.questions
        if q.id in gradeable_ids
    }
    result: list[dict[str, Any]] = []
    for qid in gradeable_ids:
        scores: list[int] = []
        correct = 0
        pending = 0
        for report in reports:
            for entry in report.get("breakdown", []):
                if entry.get(BREAKDOWN_ID_KEY) != qid:
                    continue
                is_entry_pending = bool(
                    entry.get(NEEDS_REVIEW_KEY)
                    and entry.get(MANUAL_SCORE_KEY) is None
                )
                if is_entry_pending:
                    pending += 1
                    continue
                final = entry.get(FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY])
                scores.append(int(final))
                if final == entry.get(BREAKDOWN_MAX_KEY):
                    correct += 1
        points = points_by_id.get(qid, 0)
        if scores:
            avg = statistics.mean(scores)
            med = statistics.median(scores)
            p = avg / points if points else 0
            correct_rate = correct / len(scores) if scores else 0
        else:
            avg = 0
            med = 0
            p = 0
            correct_rate = 0
        result.append(
            {
                "id": qid,
                "points": points,
                "avg_final": avg,
                "median_final": med,
                "p": p,
                "difficulty": 1 - p,
                "correct_rate": correct_rate,
                "n_finalized": len(scores),
                "pending": pending,
            }
        )
    # sort easiest first (highest p)
    result.sort(key=lambda d: d["p"], reverse=True)
    return result


def histogram(values: list[float], bins: int = 10) -> list[dict[str, Any]]:
    """Return a binned histogram for percentage values."""
    if not values or bins <= 0:
        return []
    low = 0.0
    high = 100.0
    width = (high - low) / bins
    counts = [0] * bins
    for val in values:
        idx = int((val - low) / width)
        if idx >= bins:
            idx = bins - 1
        idx = max(idx, 0)
        counts[idx] += 1
    result: list[dict[str, Any]] = []
    for i in range(bins):
        bin_low = low + i * width
        bin_high = bin_low + width
        result.append(
            {
                "low": bin_low,
                "high": bin_high,
                "label": HISTOGRAM_RANGE_LABEL.format(
                    low=bin_low, high=bin_high
                ),
                "count": counts[i],
            }
        )
    return result


def sparkline_for_question(
    question_id: str, reports: list[dict[str, Any]]
) -> str:
    """Return a sparkline for one question across finalized reports."""
    scores: list[int] = []
    for report in reports:
        for entry in report.get("breakdown", []):
            if entry.get(BREAKDOWN_ID_KEY) != question_id:
                continue
            is_entry_pending = bool(
                entry.get(NEEDS_REVIEW_KEY)
                and entry.get(MANUAL_SCORE_KEY) is None
            )
            if is_entry_pending:
                continue
            final = entry.get(FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY])
            scores.append(int(final))
    if not scores:
        return ""
    try:
        import sparklines as _sparklines  # noqa: PLC0415

        lines = _sparklines.sparklines(scores)  # type: ignore[operator]
        if lines:
            return str(lines[0])
        return ""
    except Exception:
        # fallback to empty when sparklines not available
        return ""


def _quantile(values: list[float], q: float) -> float:
    """Return the q-th quantile via linear interpolation."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    pos = (n - 1) * q
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return float(sorted_vals[int(pos)])
    lower = sorted_vals[low]
    upper = sorted_vals[high]
    weight = pos - low
    return float(lower * (1 - weight) + upper * weight)
