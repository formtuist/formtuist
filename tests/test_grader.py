"""Tests for the auto-grading logic."""

from typing import Literal

from formtuitous.grader import (
    BREAKDOWN_ANSWER_KEY,
    BREAKDOWN_CORRECT_ANSWER_KEY,
    BREAKDOWN_CORRECT_KEY,
    BREAKDOWN_ID_KEY,
    BREAKDOWN_KEY,
    BREAKDOWN_SCORE_KEY,
    MAX_KEY,
    PERCENTAGE_KEY,
    TOTAL_KEY,
    _grade_question,
    grade_response,
)
from formtuitous.schema import (
    CheckboxQuestion,
    CodeBlock,
    FormDefinition,
    MultipleChoiceQuestion,
    NumericQuestion,
    NumericRange,
    ParagraphQuestion,
    RatingQuestion,
    ShortTextQuestion,
    YesNoQuestion,
)

EXPECTED_POINTS = 10
EXPECTED_PARAGRAPH_POINTS = 15
EXPECTED_TOTAL_FULL = 20
EXPECTED_TOTAL_PARTIAL = 10
EXPECTED_PERCENT_FULL = 100
EXPECTED_PERCENT_PARTIAL = 50
EXPECTED_PARTIAL_CREDIT = 5
EXPECTED_SUPERSET_CREDIT = 8
EXPECTED_GRADED_COUNT = 2


def _short_text(
    grading_type: Literal["exact", "regex", "contains"] | None = "exact",
    correct_answer: str = "answer",
) -> ShortTextQuestion:
    """Build a short_text question for grading tests."""
    return ShortTextQuestion(
        id="q",
        text="Question?",
        type="short_text",
        correct_answer=correct_answer,
        points=EXPECTED_POINTS,
        grading_type=grading_type,
    )


class TestGradeText:
    """Tests for grading text answers."""

    def test_exact_match(self) -> None:
        """Exact grading gives full credit for an exact answer."""
        assert _grade_question(_short_text(), "answer") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_exact_mismatch(self) -> None:
        """Exact grading gives zero for a different answer."""
        assert _grade_question(_short_text(), "wrong") == (
            0,
            EXPECTED_POINTS,
        )

    def test_exact_is_case_sensitive(self) -> None:
        """Exact grading matches case-sensitively."""
        assert _grade_question(_short_text(), "Answer") == (
            0,
            EXPECTED_POINTS,
        )

    def test_missing_grading_type_falls_back_to_exact(self) -> None:
        """A missing grading type falls back to exact matching."""
        assert _grade_question(_short_text(grading_type=None), "answer") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_no_answer_scores_zero(self) -> None:
        """A missing answer scores zero."""
        assert _grade_question(_short_text(), None) == (0, EXPECTED_POINTS)

    def test_missing_correct_answer_scores_zero(self) -> None:
        """A text question without a correct answer scores zero."""
        question = ShortTextQuestion(
            id="q",
            text="Question?",
            type="short_text",
            points=EXPECTED_POINTS,
        )
        assert _grade_question(question, "anything") == (
            0,
            EXPECTED_POINTS,
        )

    def test_regex_match(self) -> None:
        """Regex grading accepts a matching answer."""
        question = _short_text(
            grading_type="regex", correct_answer=r"^lambda\s+\w+\s*:"
        )
        assert _grade_question(question, "lambda x: x * x") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_regex_mismatch(self) -> None:
        """Regex grading rejects a non-matching answer."""
        question = _short_text(grading_type="regex", correct_answer=r"^lambda")
        assert _grade_question(question, "def square():") == (
            0,
            EXPECTED_POINTS,
        )

    def test_contains_match(self) -> None:
        """Contains grading accepts an answer with the key phrase."""
        question = _short_text(grading_type="contains", correct_answer="None")
        assert _grade_question(question, "The value was None") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_contains_mismatch(self) -> None:
        """Contains grading rejects an answer without the key phrase."""
        question = _short_text(grading_type="contains", correct_answer="None")
        assert _grade_question(question, "The value was missing") == (
            0,
            EXPECTED_POINTS,
        )

    def test_paragraph_question(self) -> None:
        """Paragraph questions grade like short_text questions."""
        question = ParagraphQuestion(
            id="q",
            text="Essay?",
            type="paragraph",
            correct_answer="immutable",
            points=EXPECTED_PARAGRAPH_POINTS,
            grading_type="contains",
        )
        assert _grade_question(question, "tuples are immutable") == (
            EXPECTED_PARAGRAPH_POINTS,
            EXPECTED_PARAGRAPH_POINTS,
        )

    def test_regex_uses_accepts(self) -> None:
        """Regex grading prefers the accepts pattern."""
        question = ShortTextQuestion(
            id="q",
            text="Lambda?",
            type="short_text",
            correct_answer="lambda x: x * x",
            accepts=r"^lambda\s+\w+\s*:",
            points=EXPECTED_POINTS,
            grading_type="regex",
        )
        assert _grade_question(question, "lambda y: y * y") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )
        assert _grade_question(question, "def f(): pass") == (
            0,
            EXPECTED_POINTS,
        )

    def test_regex_falls_back_to_correct_answer(self) -> None:
        """Regex grading uses correct_answer when accepts is absent."""
        question = ShortTextQuestion(
            id="q",
            text="Start?",
            type="short_text",
            correct_answer=r"^start",
            points=EXPECTED_POINTS,
            grading_type="regex",
        )
        assert _grade_question(question, "start here") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_regex_without_pattern_scores_zero(self) -> None:
        """Regex grading with a code answer and no accepts scores zero."""
        question = ShortTextQuestion(
            id="q",
            text="Code?",
            type="short_text",
            correct_answer=CodeBlock(language="python", content="x = 1"),
            points=EXPECTED_POINTS,
            grading_type="regex",
        )
        assert _grade_question(question, "x = 1") == (0, EXPECTED_POINTS)

    def test_exact_code_block_match(self) -> None:
        """Exact grading matches code block content, ignoring whitespace."""
        question = ShortTextQuestion(
            id="q",
            text="Code?",
            type="short_text",
            correct_answer=CodeBlock(
                language="python", content="lambda x: x * x"
            ),
            points=EXPECTED_POINTS,
            grading_type="exact",
        )
        assert _grade_question(question, "lambda x: x * x") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )
        assert _grade_question(question, "lambda x: x + x") == (
            0,
            EXPECTED_POINTS,
        )

    def test_exact_list_any_match(self) -> None:
        """Exact grading accepts any code segment in a list."""
        question = ShortTextQuestion(
            id="q",
            text="Code?",
            type="short_text",
            correct_answer=[
                CodeBlock(language="python", content="lambda x: x * x"),
                CodeBlock(language="python", content="lambda x: x ** 2"),
            ],
            points=EXPECTED_POINTS,
            grading_type="exact",
        )
        assert _grade_question(question, "lambda x: x ** 2") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )
        assert _grade_question(question, "lambda x: x + x") == (
            0,
            EXPECTED_POINTS,
        )

    def test_contains_list_any_match(self) -> None:
        """Contains grading accepts any code segment in a list."""
        question = ParagraphQuestion(
            id="q",
            text="Explain?",
            type="paragraph",
            correct_answer=[
                CodeBlock(language="python", content="immutable"),
                CodeBlock(language="python", content="cannot change"),
            ],
            points=EXPECTED_POINTS,
            grading_type="contains",
        )
        assert _grade_question(question, "tuples are immutable") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )
        assert _grade_question(question, "tuples change freely") == (
            0,
            EXPECTED_POINTS,
        )


class TestGradeMultipleChoice:
    """Tests for grading multiple choice answers."""

    def _question(self) -> MultipleChoiceQuestion:
        """Build a multiple choice question with a correct label."""
        return MultipleChoiceQuestion(
            id="q",
            text="Pick?",
            type="multiple_choice",
            choices=["alpha", "beta", "gamma"],
            correct_answer="beta",
            points=EXPECTED_POINTS,
            grading_type="exact",
        )

    def test_correct_label(self) -> None:
        """Selecting the correct label scores full credit."""
        assert _grade_question(self._question(), "beta") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_wrong_label(self) -> None:
        """Selecting a wrong label scores zero."""
        assert _grade_question(self._question(), "alpha") == (
            0,
            EXPECTED_POINTS,
        )

    def test_no_selection(self) -> None:
        """Not selecting anything scores zero."""
        assert _grade_question(self._question(), None) == (
            0,
            EXPECTED_POINTS,
        )


class TestGradeCheckbox:
    """Tests for grading checkbox answers."""

    def _question(self) -> CheckboxQuestion:
        """Build a checkbox question worth ten points."""
        return CheckboxQuestion(
            id="q",
            text="Pick?",
            type="checkbox",
            choices=["a", "b", "c", "d"],
            correct_answer=["a", "b", "c"],
            points=EXPECTED_POINTS,
            grading_type="exact",
        )

    def test_exact_full_credit(self) -> None:
        """Selecting exactly the correct set scores full credit."""
        assert _grade_question(self._question(), ["a", "b", "c"]) == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_no_selection_scores_zero(self) -> None:
        """Selecting nothing scores zero."""
        assert _grade_question(self._question(), []) == (0, EXPECTED_POINTS)

    def test_no_answer_scores_zero(self) -> None:
        """A missing answer scores zero."""
        assert _grade_question(self._question(), None) == (
            0,
            EXPECTED_POINTS,
        )

    def test_partial_credit(self) -> None:
        """A partially correct selection earns Jaccard credit."""
        # intersection {a, b} over union {a, b, c, d} is 2/4 of the points
        assert _grade_question(self._question(), ["a", "b", "d"]) == (
            EXPECTED_PARTIAL_CREDIT,
            EXPECTED_POINTS,
        )

    def test_superset_gets_partial_credit(self) -> None:
        """The correct set plus extras earns partial credit."""
        # intersection {a, b, c} over union {a, b, c, d} is 3/4 * 10 = 7.5
        assert _grade_question(self._question(), ["a", "b", "c", "d"]) == (
            EXPECTED_SUPERSET_CREDIT,
            EXPECTED_POINTS,
        )


class TestGradeNumeric:
    """Tests for grading numeric answers."""

    def _exact(self) -> NumericQuestion:
        """Build a numeric question with an exact answer."""
        return NumericQuestion(
            id="q",
            text="Number?",
            type="numeric",
            correct_answer=2,
            points=EXPECTED_POINTS,
            grading_type="exact",
        )

    def _range(self) -> NumericQuestion:
        """Build a numeric question with a range answer."""
        return NumericQuestion(
            id="q",
            text="Range?",
            type="numeric",
            correct_answer=NumericRange(min=990, max=1010),
            points=EXPECTED_POINTS,
            grading_type="exact",
        )

    def test_exact_match_string_input(self) -> None:
        """A string answer equal to the exact value scores full credit."""
        assert _grade_question(self._exact(), "2") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_exact_mismatch(self) -> None:
        """A different numeric answer scores zero."""
        assert _grade_question(self._exact(), "3") == (0, EXPECTED_POINTS)

    def test_exact_non_numeric(self) -> None:
        """A non-numeric answer scores zero."""
        assert _grade_question(self._exact(), "abc") == (0, EXPECTED_POINTS)

    def test_range_inclusive_bounds(self) -> None:
        """Range grading accepts the inclusive bounds."""
        assert _grade_question(self._range(), "990") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )
        assert _grade_question(self._range(), "1010") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_range_middle_value(self) -> None:
        """Range grading accepts values inside the bounds."""
        assert _grade_question(self._range(), "1000") == (
            EXPECTED_POINTS,
            EXPECTED_POINTS,
        )

    def test_range_outside(self) -> None:
        """Range grading rejects values outside the bounds."""
        assert _grade_question(self._range(), "989") == (0, EXPECTED_POINTS)
        assert _grade_question(self._range(), "1011") == (0, EXPECTED_POINTS)


class TestGradeResponse:
    """Tests for grading a full response."""

    def _form(self) -> FormDefinition:
        """Build a mixed form with graded and ungraded questions."""
        return FormDefinition(
            name="Quiz",
            questions=[
                MultipleChoiceQuestion(
                    id="mc",
                    text="Pick?",
                    type="multiple_choice",
                    choices=["a", "b"],
                    correct_answer="a",
                    points=EXPECTED_POINTS,
                    grading_type="exact",
                ),
                ShortTextQuestion(
                    id="text",
                    text="Type?",
                    type="short_text",
                    correct_answer="def",
                    points=EXPECTED_POINTS,
                    grading_type="exact",
                ),
                RatingQuestion(
                    id="rating",
                    text="Rate?",
                    type="rating",
                    min=1,
                    max=5,
                    labels=["1", "2", "3", "4", "5"],
                ),
                YesNoQuestion(id="yesno", text="Yes?", type="yes_no"),
            ],
        )

    def test_full_score(self) -> None:
        """All-correct answers produce a perfect score."""
        form = self._form()
        report = grade_response(form, {"mc": "a", "text": "def"})
        assert report[TOTAL_KEY] == EXPECTED_TOTAL_FULL
        assert report[MAX_KEY] == EXPECTED_TOTAL_FULL
        assert report[PERCENTAGE_KEY] == EXPECTED_PERCENT_FULL

    def test_partial_score(self) -> None:
        """One wrong answer lowers the total and percentage."""
        form = self._form()
        report = grade_response(form, {"mc": "b", "text": "def"})
        assert report[TOTAL_KEY] == EXPECTED_TOTAL_PARTIAL
        assert report[MAX_KEY] == EXPECTED_TOTAL_FULL
        assert report[PERCENTAGE_KEY] == EXPECTED_PERCENT_PARTIAL

    def test_breakdown_covers_only_graded(self) -> None:
        """The breakdown skips questions without correct answers."""
        form = self._form()
        report = grade_response(form, {"mc": "a", "text": "wrong"})
        breakdown = report[BREAKDOWN_KEY]
        assert len(breakdown) == EXPECTED_GRADED_COUNT
        assert {entry[BREAKDOWN_ID_KEY] for entry in breakdown} == {
            "mc",
            "text",
        }

    def test_breakdown_reports_correctness(self) -> None:
        """Each entry reports the answer, correct answer, and score."""
        form = self._form()
        report = grade_response(form, {"mc": "a", "text": "wrong"})
        by_id = {
            entry[BREAKDOWN_ID_KEY]: entry for entry in report[BREAKDOWN_KEY]
        }
        assert by_id["mc"][BREAKDOWN_CORRECT_KEY] is True
        assert by_id["text"][BREAKDOWN_CORRECT_KEY] is False
        assert by_id["mc"][BREAKDOWN_ANSWER_KEY] == "a"
        assert by_id["text"][BREAKDOWN_ANSWER_KEY] == "wrong"
        assert by_id["text"][BREAKDOWN_CORRECT_ANSWER_KEY] == "def"
        assert by_id["text"][BREAKDOWN_SCORE_KEY] == 0

    def test_no_graded_questions(self) -> None:
        """A form without correct answers produces an empty report."""
        form = FormDefinition(
            name="Empty",
            questions=[
                RatingQuestion(
                    id="r",
                    text="Rate?",
                    type="rating",
                    min=1,
                    max=5,
                    labels=["1", "2", "3", "4", "5"],
                ),
            ],
        )
        report = grade_response(form, {"r": 3})
        assert report[TOTAL_KEY] == 0
        assert report[MAX_KEY] == 0
        assert report[PERCENTAGE_KEY] == 0
        assert report[BREAKDOWN_KEY] == []

    def test_unanswered_graded_question_scores_zero(self) -> None:
        """An unanswered graded question appears with a zero score."""
        form = self._form()
        report = grade_response(form, {})
        by_id = {
            entry[BREAKDOWN_ID_KEY]: entry for entry in report[BREAKDOWN_KEY]
        }
        assert by_id["mc"][BREAKDOWN_SCORE_KEY] == 0
        assert by_id["mc"][BREAKDOWN_CORRECT_KEY] is False
        assert by_id["mc"][BREAKDOWN_ANSWER_KEY] is None

    def test_ungradeable_type_scores_zero(self) -> None:
        """Rating questions handed to the grader score zero."""
        question = RatingQuestion(
            id="r",
            text="Rate?",
            type="rating",
            min=1,
            max=5,
            labels=["1", "2", "3", "4", "5"],
        )
        assert _grade_question(question, 3) == (0, 0)
