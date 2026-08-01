"""Auto-grading logic for quizzes with correct answers."""

import re
from typing import Any

from formtuitous.schema import (
    GRADING_TYPE_CONTAINS,
    GRADING_TYPE_REGEX,
    CheckboxQuestion,
    CodeBlock,
    FormDefinition,
    MultipleChoiceQuestion,
    NumericQuestion,
    NumericRange,
    ParagraphQuestion,
    Question,
    ShortTextQuestion,
)

# report keys for the grade response
TOTAL_KEY = "total"
MAX_KEY = "max"
PERCENTAGE_KEY = "percentage"
BREAKDOWN_KEY = "breakdown"

# keys for a single graded question entry in the breakdown
BREAKDOWN_ID_KEY = "id"
BREAKDOWN_TEXT_KEY = "text"
BREAKDOWN_ANSWER_KEY = "answer"
BREAKDOWN_CORRECT_ANSWER_KEY = "correct_answer"
BREAKDOWN_SCORE_KEY = "score"
BREAKDOWN_MAX_KEY = "max"
BREAKDOWN_CORRECT_KEY = "correct"
BREAKDOWN_LANGUAGE_KEY = "language"

# rounding precision for the percentage score
PERCENTAGE_DIGITS = 2


def grade_response(
    form: FormDefinition, answers: dict[str, Any]
) -> dict[str, Any]:
    """Grade a single response and return the score report."""
    total = 0
    max_total = 0
    breakdown: list[dict[str, Any]] = []
    for question in form.questions:
        correct_answer = getattr(question, "correct_answer", None)
        if correct_answer is None:
            continue
        answer = answers.get(question.id)
        score, max_score = _grade_question(question, answer)
        total += score
        max_total += max_score
        code_block = getattr(question, "code", None)
        breakdown.append(
            {
                BREAKDOWN_ID_KEY: question.id,
                BREAKDOWN_TEXT_KEY: question.text,
                BREAKDOWN_ANSWER_KEY: answer,
                BREAKDOWN_CORRECT_ANSWER_KEY: correct_answer,
                BREAKDOWN_SCORE_KEY: score,
                BREAKDOWN_MAX_KEY: max_score,
                BREAKDOWN_CORRECT_KEY: score == max_score,
                BREAKDOWN_LANGUAGE_KEY: (
                    code_block.language if code_block is not None else None
                ),
            }
        )
    percentage = (
        round(total / max_total * 100, PERCENTAGE_DIGITS) if max_total else 0
    )
    return {
        TOTAL_KEY: total,
        MAX_KEY: max_total,
        PERCENTAGE_KEY: percentage,
        BREAKDOWN_KEY: breakdown,
    }


def _grade_question(question: Question, answer: Any) -> tuple[int, int]:
    """Return the (score, max_score) pair for one graded question."""
    max_score = getattr(question, "points", 0)
    if isinstance(question, MultipleChoiceQuestion):
        if answer == question.correct_answer:
            return (max_score, max_score)
        return (0, max_score)
    if isinstance(question, CheckboxQuestion):
        return _grade_checkbox(question, answer)
    if isinstance(question, NumericQuestion):
        return _grade_numeric(question, answer)
    if isinstance(question, (ShortTextQuestion, ParagraphQuestion)):
        return _grade_text(question, answer)
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
