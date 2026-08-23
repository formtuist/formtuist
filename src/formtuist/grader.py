"""Auto-grading logic for quizzes with correct answers."""

import re
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from formtuist.schema import (
    GRADING_TYPE_CONTAINS,
    GRADING_TYPE_REGEX,
    REVIEW_REQUIRED,
    CheckboxQuestion,
    CodeBlock,
    FormDefinition,
    MultipleChoiceQuestion,
    NumericQuestion,
    NumericRange,
    ParagraphQuestion,
    Question,
    ShortTextQuestion,
    YesNoQuestion,
)

# report keys for the grade response
TOTAL_KEY = "total"
MAX_KEY = "max"
PERCENTAGE_KEY = "percentage"
BREAKDOWN_KEY = "breakdown"

# final keys for post-graded reports
TOTAL_FINAL_KEY = "total_final"
PERCENTAGE_FINAL_KEY = "percentage_final"

# keys for the JSON-safe forms of numeric ranges and code blocks
RANGE_MIN_KEY = "min"
RANGE_MAX_KEY = "max"
CODE_CONTENT_KEY = "content"

# keys for a single graded question entry in the breakdown
BREAKDOWN_ID_KEY = "id"
BREAKDOWN_TEXT_KEY = "text"
BREAKDOWN_ANSWER_KEY = "answer"
BREAKDOWN_CORRECT_ANSWER_KEY = "correct_answer"
BREAKDOWN_SCORE_KEY = "score"
BREAKDOWN_MAX_KEY = "max"
BREAKDOWN_CORRECT_KEY = "correct"
BREAKDOWN_LANGUAGE_KEY = "language"

# review keys for manual post-grading
PRELIM_SCORE_KEY = "prelim_score"
MANUAL_SCORE_KEY = "manual_score"
FINAL_SCORE_KEY = "final_score"
NEEDS_REVIEW_KEY = "needs_review"
REVIEWED_BY_KEY = "reviewed_by"
REVIEWED_AT_KEY = "reviewed_at"
COMMENT_KEY = "comment"

# rounding precision for the percentage score
PERCENTAGE_DIGITS = 2

# timestamp key added to the stored grade snapshot
GRADED_AT_KEY = "graded_at"


def has_gradeable_questions(form: FormDefinition) -> bool:
    """Return whether any question has a correct answer to grade."""
    return any(
        getattr(question, "correct_answer", None) is not None
        or getattr(question, "review", "none") == REVIEW_REQUIRED
        for question in form.questions
    )


def grade_response(
    form: FormDefinition, answers: dict[str, Any]
) -> dict[str, Any]:
    """Grade a single response and return the score report."""
    total = 0
    max_total = 0
    breakdown: list[dict[str, Any]] = []
    for question in form.questions:
        correct_answer = getattr(question, "correct_answer", None)
        review = getattr(question, "review", "none")
        is_gradeable = correct_answer is not None or review == REVIEW_REQUIRED
        if not is_gradeable:
            continue
        answer = answers.get(question.id)
        # manual questions with no correct answer get prelim 0
        if correct_answer is None and review == REVIEW_REQUIRED:
            score, max_score = 0, getattr(question, "points", 0)
        else:
            score, max_score = _grade_question(question, answer)
        total += score
        max_total += max_score
        code_block = getattr(question, "code", None)
        needs_review = review == REVIEW_REQUIRED
        prelim_score = score
        # final tracks prelim until a manual score is set
        final_score = score
        breakdown.append(
            {
                BREAKDOWN_ID_KEY: question.id,
                BREAKDOWN_TEXT_KEY: question.text,
                BREAKDOWN_ANSWER_KEY: answer,
                BREAKDOWN_CORRECT_ANSWER_KEY: correct_answer,
                BREAKDOWN_SCORE_KEY: score,
                PRELIM_SCORE_KEY: prelim_score,
                MANUAL_SCORE_KEY: None,
                FINAL_SCORE_KEY: final_score,
                BREAKDOWN_MAX_KEY: max_score,
                BREAKDOWN_CORRECT_KEY: score == max_score,
                BREAKDOWN_LANGUAGE_KEY: (
                    code_block.language if code_block is not None else None
                ),
                NEEDS_REVIEW_KEY: needs_review,
                REVIEWED_BY_KEY: None,
                REVIEWED_AT_KEY: None,
                COMMENT_KEY: None,
            }
        )
    percentage = (
        round(total / max_total * 100, PERCENTAGE_DIGITS) if max_total else 0
    )
    total_final = total
    percentage_final = percentage
    return {
        TOTAL_KEY: total,
        MAX_KEY: max_total,
        PERCENTAGE_KEY: percentage,
        TOTAL_FINAL_KEY: total_final,
        PERCENTAGE_FINAL_KEY: percentage_final,
        BREAKDOWN_KEY: breakdown,
    }


def grade_report_to_json(report: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-safe copy of a grade report for database storage.

    Pydantic models such as NumericRange and CodeBlock are converted to
    plain dicts so the snapshot survives a JSON round trip. A graded_at
    timestamp records when the snapshot was created.
    """
    total_final = report.get(TOTAL_FINAL_KEY, report[TOTAL_KEY])
    perc_final = report.get(PERCENTAGE_FINAL_KEY, report[PERCENTAGE_KEY])
    return {
        TOTAL_KEY: report[TOTAL_KEY],
        MAX_KEY: report[MAX_KEY],
        PERCENTAGE_KEY: report[PERCENTAGE_KEY],
        TOTAL_FINAL_KEY: total_final,
        PERCENTAGE_FINAL_KEY: perc_final,
        BREAKDOWN_KEY: [
            {
                BREAKDOWN_ID_KEY: entry[BREAKDOWN_ID_KEY],
                BREAKDOWN_TEXT_KEY: entry[BREAKDOWN_TEXT_KEY],
                BREAKDOWN_ANSWER_KEY: _json_safe(entry[BREAKDOWN_ANSWER_KEY]),
                BREAKDOWN_CORRECT_ANSWER_KEY: _json_safe(
                    entry[BREAKDOWN_CORRECT_ANSWER_KEY]
                ),
                BREAKDOWN_SCORE_KEY: entry[BREAKDOWN_SCORE_KEY],
                PRELIM_SCORE_KEY: entry.get(
                    PRELIM_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY]
                ),
                MANUAL_SCORE_KEY: entry.get(MANUAL_SCORE_KEY),
                FINAL_SCORE_KEY: entry.get(
                    FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY]
                ),
                BREAKDOWN_MAX_KEY: entry[BREAKDOWN_MAX_KEY],
                BREAKDOWN_CORRECT_KEY: entry[BREAKDOWN_CORRECT_KEY],
                BREAKDOWN_LANGUAGE_KEY: entry[BREAKDOWN_LANGUAGE_KEY],
                NEEDS_REVIEW_KEY: entry.get(NEEDS_REVIEW_KEY, False),
                REVIEWED_BY_KEY: entry.get(REVIEWED_BY_KEY),
                REVIEWED_AT_KEY: entry.get(REVIEWED_AT_KEY),
                COMMENT_KEY: entry.get(COMMENT_KEY),
            }
            for entry in report[BREAKDOWN_KEY]
        ],
        GRADED_AT_KEY: datetime.now(timezone.utc).isoformat(),
    }


def is_pending(report: dict[str, Any]) -> bool:
    """Return whether any required review is still pending."""
    for entry in report.get(BREAKDOWN_KEY, []):
        if entry.get(NEEDS_REVIEW_KEY) and entry.get(MANUAL_SCORE_KEY) is None:
            return True
    return False


def apply_post_grade(
    report: dict[str, Any],
    overrides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a new report with manual scores applied.

    *overrides* maps question id to a dict with
    ``manual_score``, ``comment``, and ``reviewer``.
    Re-applying overwrites the previous manual values; a None
    ``comment`` or ``reviewer`` clears the stored value, and a
    successfully applied score marks the entry no longer pending.
    """
    cloned = deepcopy(report)
    by_id = {entry[BREAKDOWN_ID_KEY]: entry for entry in cloned[BREAKDOWN_KEY]}
    for qid, data in overrides.items():
        entry = by_id.get(qid)
        if entry is None:
            continue
        manual = data.get("manual_score")
        comment = data.get("comment")
        reviewer = data.get("reviewer")
        if manual is not None:
            entry[MANUAL_SCORE_KEY] = int(manual)
            entry[FINAL_SCORE_KEY] = int(manual)
            entry[BREAKDOWN_CORRECT_KEY] = (
                int(manual) == entry[BREAKDOWN_MAX_KEY]
            )
            entry[NEEDS_REVIEW_KEY] = False
        # replace unconditionally so an explicit None clears old values
        entry[COMMENT_KEY] = comment
        entry[REVIEWED_BY_KEY] = reviewer
        entry[REVIEWED_AT_KEY] = datetime.now(timezone.utc).isoformat()
    # recompute totals for final
    total_final = sum(
        entry.get(FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY])
        for entry in cloned[BREAKDOWN_KEY]
    )
    max_total = cloned[MAX_KEY]
    cloned[TOTAL_FINAL_KEY] = total_final
    cloned[PERCENTAGE_FINAL_KEY] = (
        round(total_final / max_total * 100, PERCENTAGE_DIGITS)
        if max_total
        else 0
    )
    return cloned


def finalize_report(report: dict[str, Any]) -> dict[str, Any]:
    """Recompute final totals from existing manual scores."""
    cloned = deepcopy(report)
    for entry in cloned[BREAKDOWN_KEY]:
        if entry.get(MANUAL_SCORE_KEY) is not None:
            entry[FINAL_SCORE_KEY] = entry[MANUAL_SCORE_KEY]
            entry[NEEDS_REVIEW_KEY] = False
        else:
            entry[FINAL_SCORE_KEY] = entry.get(
                PRELIM_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY]
            )
        # correct reflects final
        entry[BREAKDOWN_CORRECT_KEY] = (
            entry[FINAL_SCORE_KEY] == entry[BREAKDOWN_MAX_KEY]
        )
    total_final = sum(
        entry[FINAL_SCORE_KEY] for entry in cloned[BREAKDOWN_KEY]
    )
    max_total = cloned[MAX_KEY]
    cloned[TOTAL_FINAL_KEY] = total_final
    cloned[PERCENTAGE_FINAL_KEY] = (
        round(total_final / max_total * 100, PERCENTAGE_DIGITS)
        if max_total
        else 0
    )
    return cloned


def refresh_prelim(
    old_report: dict[str, Any],
    form: FormDefinition,
    answers: dict[str, Any],
) -> dict[str, Any]:
    """Recompute prelim scores while preserving manual decisions."""
    fresh = grade_response(form, answers)
    # carry manual fields from old report
    old_by_id = {
        entry[BREAKDOWN_ID_KEY]: entry
        for entry in old_report.get(BREAKDOWN_KEY, [])
    }
    for entry in fresh[BREAKDOWN_KEY]:
        old = old_by_id.get(entry[BREAKDOWN_ID_KEY])
        if old is not None and old.get(MANUAL_SCORE_KEY) is not None:
            entry[MANUAL_SCORE_KEY] = old[MANUAL_SCORE_KEY]
            entry[FINAL_SCORE_KEY] = old[MANUAL_SCORE_KEY]
            entry[COMMENT_KEY] = old.get(COMMENT_KEY)
            entry[REVIEWED_BY_KEY] = old.get(REVIEWED_BY_KEY)
            entry[REVIEWED_AT_KEY] = old.get(REVIEWED_AT_KEY)
            entry[NEEDS_REVIEW_KEY] = False
            entry[BREAKDOWN_CORRECT_KEY] = (
                entry[FINAL_SCORE_KEY] == entry[BREAKDOWN_MAX_KEY]
            )
    # recompute final totals after merge
    total_final = sum(
        entry.get(FINAL_SCORE_KEY, entry[BREAKDOWN_SCORE_KEY])
        for entry in fresh[BREAKDOWN_KEY]
    )
    max_total = fresh[MAX_KEY]
    fresh[TOTAL_FINAL_KEY] = total_final
    fresh[PERCENTAGE_FINAL_KEY] = (
        round(total_final / max_total * 100, PERCENTAGE_DIGITS)
        if max_total
        else 0
    )
    # preserve graded_at? will be overwritten by grade_report_to_json
    return fresh


def _json_safe(value: Any) -> Any:
    """Convert pydantic models in an answer value to plain JSON data."""
    if isinstance(value, NumericRange):
        return {RANGE_MIN_KEY: value.min, RANGE_MAX_KEY: value.max}
    if isinstance(value, CodeBlock):
        return {
            BREAKDOWN_LANGUAGE_KEY: value.language,
            CODE_CONTENT_KEY: value.content or "",
        }
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _grade_question(question: Question, answer: Any) -> tuple[int, int]:
    """Return the (score, max_score) pair for one graded question."""
    max_score = getattr(question, "points", 0)
    if isinstance(question, MultipleChoiceQuestion):
        matched = answer == question.correct_answer
    elif isinstance(question, CheckboxQuestion):
        return _grade_checkbox(question, answer)
    elif isinstance(question, NumericQuestion):
        return _grade_numeric(question, answer)
    elif isinstance(question, (ShortTextQuestion, ParagraphQuestion)):
        return _grade_text(question, answer)
    elif isinstance(question, YesNoQuestion):
        return _grade_yes_no(question, answer)
    else:
        matched = False
    if matched:
        return (max_score, max_score)
    return (0, max_score)


def _grade_checkbox(
    question: CheckboxQuestion, answer: Any
) -> tuple[int, int]:
    """Grade a checkbox answer with Jaccard-style partial credit."""
    max_score = question.points
    correct = set(question.correct_answer or [])
    given = set(answer) if isinstance(answer, (list, set, tuple)) else set()
    if not correct or not given:
        return (0, max_score)
    union = correct | given
    score = len(correct & given) / len(union) * max_score
    return (round(score), max_score)


def _grade_numeric(question: NumericQuestion, answer: Any) -> tuple[int, int]:
    """Grade a numeric answer with exact or range matching."""
    max_score = question.points
    try:
        value = float(answer)
    except (TypeError, ValueError):
        return (0, max_score)
    correct = question.correct_answer
    if isinstance(correct, NumericRange):
        if correct.min <= value <= correct.max:
            return (max_score, max_score)
        return (0, max_score)
    if correct is not None and value == correct:
        return (max_score, max_score)
    return (0, max_score)


def _grade_yes_no(question: YesNoQuestion, answer: Any) -> tuple[int, int]:
    """Grade a true/false answer against a boolean correct answer."""
    max_score = question.points
    if question.correct_answer is None:
        return (0, max_score)
    if answer == question.correct_answer:
        return (max_score, max_score)
    return (0, max_score)


def _grade_text(
    question: ShortTextQuestion | ParagraphQuestion, answer: Any
) -> tuple[int, int]:
    """Grade a text answer with exact, regex, or contains matching."""
    max_score = question.points
    text = str(answer) if answer is not None else ""
    correct = question.correct_answer
    if correct is None:
        return (0, max_score)
    grading_type = question.grading_type
    if grading_type == GRADING_TYPE_REGEX:
        pattern = question.accepts
        if pattern is None and isinstance(correct, str):
            pattern = correct
        if pattern is None:
            return (0, max_score)
        matched = re.search(pattern, text) is not None
    elif grading_type == GRADING_TYPE_CONTAINS:
        matched = _contains_variant(_answer_variants(correct), text)
    else:
        matched = _exact_variant(_answer_variants(correct), text)
    if matched:
        return (max_score, max_score)
    return (0, max_score)


def _answer_variants(correct: str | CodeBlock | list[CodeBlock]) -> list[str]:
    """Return the string variants of a text correct answer."""
    if isinstance(correct, str):
        return [correct]
    if isinstance(correct, CodeBlock):
        return [correct.content or ""]
    return [block.content or "" for block in correct]


def _exact_variant(variants: list[str], text: str) -> bool:
    """Return True when the answer matches any variant exactly."""
    return any(text.strip() == variant.strip() for variant in variants)


def _contains_variant(variants: list[str], text: str) -> bool:
    """Return True when the answer contains any variant phrase."""
    return any(variant in text for variant in variants)
