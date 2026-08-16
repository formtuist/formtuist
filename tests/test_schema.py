"""Tests for the form JSON schema validation."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from formtuist.parser import parse_form
from formtuist.schema import (
    AuthProvider,
    CheckboxQuestion,
    CodeBlock,
    DateQuestion,
    FormConfig,
    FormDefinition,
    MultipleChoiceQuestion,
    NumericQuestion,
    NumericRange,
    ParagraphQuestion,
    RatingQuestion,
    ShortTextQuestion,
    YesNoQuestion,
)

VALID_MINIMAL = {
    "name": "Minimal Form",
    "questions": [
        {"id": "q1", "text": "Test?", "type": "short_text"},
    ],
}

EXPECTED_CHOICE_COUNT_MULTIPLE = 3
EXPECTED_CHOICE_COUNT_CHECKBOX = 2
EXPECTED_SEGMENT_COUNT = 2
EXPECTED_POINTS = 10
EXPECTED_RANGE_MAX = 120
EXPECTED_RATING_MAX = 5
EXPECTED_ALL_TYPES_COUNT = 8

VALID_ALL_TYPES = {
    "name": "All Types Form",
    "questions": [
        {"id": "s", "text": "Short?", "type": "short_text"},
        {"id": "p", "text": "Paragraph?", "type": "paragraph"},
        {
            "id": "m",
            "text": "Choice?",
            "type": "multiple_choice",
            "choices": ["A", "B", "C"],
        },
        {
            "id": "c",
            "text": "Check?",
            "type": "checkbox",
            "choices": ["X", "Y"],
        },
        {"id": "n", "text": "Number?", "type": "numeric"},
        {
            "id": "r",
            "text": "Rate?",
            "type": "rating",
            "min": 1,
            "max": 5,
            "labels": ["Bad", "Good"],
        },
        {"id": "d", "text": "Date?", "type": "date"},
        {"id": "y", "text": "YesNo?", "type": "yes_no"},
    ],
}


class TestFormConfig:
    """Tests for the FormConfig model."""

    def test_default_config(self) -> None:
        """Config uses sensible defaults when not provided."""
        config = FormConfig()
        assert config.randomize_questions is False
        assert config.auto_grade is False
        assert config.allow_multiple_submissions is True
        assert config.auth is None

    def test_auth_default_disabled(self) -> None:
        """Auth is disabled (None) by default."""
        config = FormConfig()
        assert config.auth is None

    def test_auth_github_enabled(self) -> None:
        """Auth can be set to github."""
        config = FormConfig(auth=AuthProvider.GITHUB)
        assert config.auth == "github"

    def test_auth_rejects_unknown_provider(self) -> None:
        """Auth rejects providers other than github."""
        with pytest.raises(ValidationError):
            FormConfig.model_validate({"auth": "gitlab"})


class TestQuestionModels:
    """Tests for individual question type models."""

    def test_short_text_defaults(self) -> None:
        """ShortTextQuestion has sensible defaults."""
        q = ShortTextQuestion(id="q", text="Name?", type="short_text")
        assert q.required is False
        assert q.correct_answer is None
        assert q.points == 0
        assert q.grading_type is None

    def test_paragraph_with_grading(self) -> None:
        """ParagraphQuestion accepts grading fields."""
        q = ParagraphQuestion(
            id="q",
            text="Essay?",
            type="paragraph",
            correct_answer="answer",
            points=10,
            grading_type="contains",
        )
        assert q.correct_answer == "answer"
        assert q.points == EXPECTED_POINTS
        assert q.grading_type == "contains"

    def test_multiple_choice_valid(self) -> None:
        """MultipleChoiceQuestion accepts valid choices."""
        q = MultipleChoiceQuestion(
            id="q",
            text="Pick one?",
            type="multiple_choice",
            choices=["Alpha", "Beta", "Gamma"],
        )
        assert len(q.choices) == EXPECTED_CHOICE_COUNT_MULTIPLE

    def test_multiple_choice_too_few_choices(self) -> None:
        """MultipleChoiceQuestion rejects fewer than 2 choices."""
        with pytest.raises(ValidationError):
            MultipleChoiceQuestion(
                id="q",
                text="Pick?",
                type="multiple_choice",
                choices=["Only"],
            )

    def test_checkbox_valid(self) -> None:
        """CheckboxQuestion accepts valid choices."""
        q = CheckboxQuestion(
            id="q",
            text="Select?",
            type="checkbox",
            choices=["A", "B"],
        )
        assert len(q.choices) == EXPECTED_CHOICE_COUNT_CHECKBOX

    def test_checkbox_empty_choices(self) -> None:
        """CheckboxQuestion rejects empty choices list."""
        with pytest.raises(ValidationError):
            CheckboxQuestion(
                id="q",
                text="Select?",
                type="checkbox",
                choices=[],
            )

    def test_numeric_with_range_answer(self) -> None:
        """NumericQuestion accepts a range dict as correct_answer."""
        q = NumericQuestion(
            id="q",
            text="Age?",
            type="numeric",
            correct_answer=NumericRange(min=0, max=120),
        )
        assert q.correct_answer is not None
        assert isinstance(q.correct_answer, NumericRange)
        assert q.correct_answer.min == 0
        assert q.correct_answer.max == EXPECTED_RANGE_MAX

    def test_rating_valid(self) -> None:
        """RatingQuestion accepts valid min/max/labels."""
        q = RatingQuestion(
            id="q",
            text="Rate?",
            type="rating",
            min=1,
            max=5,
            labels=["Poor", "Fair", "Good", "Very Good", "Excellent"],
        )
        assert q.min == 1
        assert q.max == EXPECTED_RATING_MAX

    def test_rating_min_equals_max(self) -> None:
        """RatingQuestion rejects min equal to max."""
        with pytest.raises(ValidationError):
            RatingQuestion(
                id="q",
                text="Rate?",
                type="rating",
                min=3,
                max=3,
                labels=["A", "B", "C"],
            )

    def test_date_defaults(self) -> None:
        """DateQuestion requires only id, text, and type."""
        q = DateQuestion(id="q", text="Date?", type="date")
        assert q.required is False

    def test_yes_no_defaults(self) -> None:
        """YesNoQuestion requires only id, text, and type."""
        q = YesNoQuestion(id="q", text="Yes?", type="yes_no")
        assert q.required is False

    def test_randomize_defaults_to_true(self) -> None:
        """Questions randomize by default."""
        q = ShortTextQuestion(id="q", text="Name?", type="short_text")
        assert q.randomize is True

    def test_randomize_can_be_disabled(self) -> None:
        """A question can opt out of randomization."""
        q = ShortTextQuestion(
            id="q", text="Name?", type="short_text", randomize=False
        )
        assert q.randomize is False

    def test_accepts_defaults_to_none(self) -> None:
        """The accepts pattern is optional."""
        q = ShortTextQuestion(id="q", text="Name?", type="short_text")
        assert q.accepts is None

    def test_accepts_rejects_invalid_regex(self) -> None:
        """An accepts pattern must be a usable regex."""
        with pytest.raises(ValidationError):
            ShortTextQuestion(
                id="q",
                text="Name?",
                type="short_text",
                accepts="[unclosed",
            )

    def test_correct_answer_as_code_block(self) -> None:
        """correct_answer accepts a single code block."""
        q = ShortTextQuestion(
            id="q",
            text="Code?",
            type="short_text",
            correct_answer=CodeBlock(language="python", content="x = 1"),
        )
        assert isinstance(q.correct_answer, CodeBlock)
        assert q.correct_answer.content == "x = 1"

    def test_correct_answer_as_code_blocks(self) -> None:
        """correct_answer accepts a list of code blocks."""
        q = ParagraphQuestion(
            id="q",
            text="Code?",
            type="paragraph",
            correct_answer=[
                CodeBlock(language="python", content="x = 1"),
                CodeBlock(language="python", content="x = 2"),
            ],
        )
        assert isinstance(q.correct_answer, list)
        assert len(q.correct_answer) == EXPECTED_SEGMENT_COUNT

    def test_correct_answer_dicts_coerce(self) -> None:
        """JSON dicts coerce into CodeBlock instances."""
        q = ShortTextQuestion.model_validate(
            {
                "id": "q",
                "text": "Code?",
                "type": "short_text",
                "correct_answer": [
                    {"language": "python", "content": "x = 1"},
                    {"language": "python", "content": "x = 2"},
                ],
            }
        )
        assert isinstance(q.correct_answer, list)
        assert len(q.correct_answer) == EXPECTED_SEGMENT_COUNT

    def test_code_block_requires_exactly_one_source(self) -> None:
        """A code block needs exactly one of content or file."""
        with pytest.raises(ValidationError):
            CodeBlock(language="python")
        with pytest.raises(ValidationError):
            CodeBlock(language="python", content="x = 1", file="a.py")

    def test_accepts_requires_regex_grading(self) -> None:
        """An accepts pattern requires regex grading."""
        with pytest.raises(ValidationError):
            ShortTextQuestion(
                id="q",
                text="Lambda?",
                type="short_text",
                correct_answer="lambda x: x * x",
                accepts=r"^lambda",
                grading_type="contains",
            )

    def test_regex_grading_requires_pattern(self) -> None:
        """Regex grading needs accepts or a string correct_answer."""
        with pytest.raises(ValidationError):
            ShortTextQuestion(
                id="q",
                text="Code?",
                type="short_text",
                correct_answer=CodeBlock(language="python", content="x = 1"),
                grading_type="regex",
            )

    def test_regex_string_pattern_must_compile(self) -> None:
        """A string correct_answer used as a regex must compile."""
        with pytest.raises(ValidationError):
            ShortTextQuestion(
                id="q",
                text="Start?",
                type="short_text",
                correct_answer="[unclosed",
                grading_type="regex",
            )

    def test_paragraph_accepts_with_regex_is_clean(self) -> None:
        """A paragraph with accepts and regex grading is valid."""
        q = ParagraphQuestion(
            id="q",
            text="T?",
            type="paragraph",
            correct_answer="lambda x: x * x",
            accepts=r"^lambda",
            grading_type="regex",
        )
        assert q.accepts == r"^lambda"

    def test_multiple_choice_answer_must_be_a_choice(self) -> None:
        """A multiple_choice correct answer must be selectable."""
        with pytest.raises(ValidationError):
            MultipleChoiceQuestion(
                id="q",
                text="Pick?",
                type="multiple_choice",
                choices=["tuple", "str"],
                correct_answer="tupel",
            )

    def test_checkbox_answers_must_be_choices(self) -> None:
        """Every checkbox correct answer must be selectable."""
        with pytest.raises(ValidationError):
            CheckboxQuestion(
                id="q",
                text="Pick?",
                type="checkbox",
                choices=["tuple", "str"],
                correct_answer=["tuple", "tupel"],
            )


class TestFormDefinition:
    """Tests for the top-level FormDefinition model."""

    def test_valid_minimal(self) -> None:
        """Minimal valid form parses correctly."""
        form = FormDefinition.model_validate(VALID_MINIMAL)
        assert form.name == "Minimal Form"
        assert form.description == ""
        assert len(form.questions) == 1

    def test_valid_all_types(self) -> None:
        """Form with all 8 question types parses correctly."""
        form = FormDefinition.model_validate(VALID_ALL_TYPES)
        assert len(form.questions) == EXPECTED_ALL_TYPES_COUNT

    def test_duplicate_question_ids(self) -> None:
        """Duplicate question ids raise ValidationError."""
        data = {
            "name": "Duplicates",
            "questions": [
                {"id": "dup", "text": "First?", "type": "short_text"},
                {"id": "dup", "text": "Second?", "type": "short_text"},
            ],
        }
        with pytest.raises(
            ValidationError, match="question ids must be unique"
        ):
            FormDefinition.model_validate(data)

    def test_invalid_question_type(self) -> None:
        """Unknown question type raises ValidationError."""
        data = {
            "name": "Bad",
            "questions": [
                {"id": "q", "text": "?", "type": "slider"},
            ],
        }
        with pytest.raises(ValidationError):
            FormDefinition.model_validate(data)

    def test_missing_name(self) -> None:
        """Missing required name field raises ValidationError."""
        data = {
            "questions": [
                {"id": "q", "text": "?", "type": "short_text"},
            ],
        }
        with pytest.raises(ValidationError):
            FormDefinition.model_validate(data)

    def test_empty_questions(self) -> None:
        """Empty questions list is valid but unusual."""
        form = FormDefinition.model_validate(
            {"name": "Empty", "questions": []}
        )
        assert len(form.questions) == 0

    def test_json_round_trip(self) -> None:
        """A FormDefinition serializes and deserializes losslessly."""
        form = FormDefinition.model_validate(VALID_MINIMAL)
        raw = form.model_dump_json()
        restored = FormDefinition.model_validate_json(raw)
        assert restored.name == form.name
        assert len(restored.questions) == len(form.questions)

    def test_pinned_question_parses(self) -> None:
        """FormDefinition accepts questions that opt out of randomization."""
        form = FormDefinition.model_validate(
            {
                "name": "Pinned",
                "questions": [
                    {"id": "a", "text": "A?", "type": "short_text"},
                    {
                        "id": "b",
                        "text": "B?",
                        "type": "short_text",
                        "randomize": False,
                    },
                ],
            }
        )
        assert form.questions[0].randomize is True
        assert form.questions[1].randomize is False

    def test_auto_grade_requires_graded_question(self) -> None:
        """Auto-grading needs at least one question with an answer key."""
        with pytest.raises(ValidationError):
            FormDefinition.model_validate(
                {
                    "name": "Trap",
                    "config": {"auto_grade": True},
                    "questions": [
                        {"id": "q", "text": "?", "type": "short_text"},
                    ],
                }
            )


class TestFormConfigInForm:
    """Tests for FormConfig embedded in FormDefinition."""

    def test_custom_config(self) -> None:
        """Form accepts a custom config."""
        data = {
            "name": "Custom",
            "config": {
                "randomize_questions": True,
                "auto_grade": True,
                "allow_multiple_submissions": False,
            },
            "questions": [
                {
                    "id": "q",
                    "text": "?",
                    "type": "short_text",
                    "correct_answer": "yes",
                    "points": 5,
                    "grading_type": "exact",
                },
            ],
        }
        form = FormDefinition.model_validate(data)
        assert form.config.randomize_questions is True
        assert form.config.auto_grade is True
        assert form.config.allow_multiple_submissions is False

    def test_default_config_in_form(self) -> None:
        """Form uses default config when none is provided."""
        form = FormDefinition.model_validate(VALID_MINIMAL)
        assert form.config.randomize_questions is False


class TestExampleForms:
    """Tests that all valid example JSON files parse correctly."""

    EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples"

    @pytest.mark.parametrize(
        "filename",
        [
            "all_types.json",
            "anonymous_poll.json",
            "attendance.json",
            "authenticated.json",
            "minimal.json",
            "minimal_auth.json",
            "quiz.json",
            "survey.json",
        ],
    )
    def test_example_validates(self, filename: str) -> None:
        """Each valid example form file validates without errors."""
        path = self.EXAMPLE_DIR / filename
        form = parse_form(path)
        assert form.name
        assert len(form.questions) > 0


class TestInvalidExampleForms:
    """Tests that all invalid example JSON files raise ValidationError."""

    EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "examples"

    @pytest.mark.parametrize(
        "filename",
        [
            "invalid_accepts_not_regex.json",
            "invalid_auto_grade_no_answers.json",
            "invalid_checkbox_answer_not_a_choice.json",
            "invalid_checkbox_no_choices.json",
            "invalid_correct_answer_not_a_choice.json",
            "invalid_duplicate_ids.json",
            "invalid_multiple_choice_one_choice.json",
            "invalid_rating_max_less_than_min.json",
            "invalid_regex_bad_pattern.json",
            "invalid_regex_no_pattern.json",
            "invalid_unknown_question_type.json",
        ],
    )
    def test_invalid_example_raises(self, filename: str) -> None:
        """Each invalid example form file raises ValidationError."""
        path = self.EXAMPLE_DIR / filename
        raw = path.read_text(encoding="utf-8")
        with pytest.raises(ValidationError):
            FormDefinition.model_validate_json(raw)


class TestQuizShowcase:
    """Tests that the quiz example showcases the formtuist format."""

    QUIZ_PATH = (
        Path(__file__).resolve().parent.parent / "examples" / "quiz.json"
    )

    # gradeable question types expected in the showcase quiz
    EXPECTED_GRADEABLE_TYPES = frozenset(
        {"short_text", "paragraph", "multiple_choice", "checkbox", "numeric"}
    )

    # grading modes expected in the showcase quiz
    EXPECTED_GRADING_MODES = frozenset({"exact", "regex", "contains"})

    # canonical answer the regex grading pattern must accept and reject
    CANONICAL_LAMBDA = "lambda x: x * x"
    WRONG_LAMBDA = "lambda x: x + x"

    def _quiz(self) -> FormDefinition:
        """Load and validate the quiz example file."""
        return parse_form(self.QUIZ_PATH)

    def test_gradeable_types_present(self) -> None:
        """The quiz uses every gradeable question type."""
        quiz = self._quiz()
        types = {question.type for question in quiz.questions}
        assert self.EXPECTED_GRADEABLE_TYPES <= types

    def test_grading_modes_present(self) -> None:
        """The quiz uses exact, regex, and contains grading."""
        quiz = self._quiz()
        modes = {
            getattr(question, "grading_type", None)
            for question in quiz.questions
        }
        assert self.EXPECTED_GRADING_MODES <= modes

    def test_checkbox_has_list_answer(self) -> None:
        """The checkbox question grades a list of correct choices."""
        quiz = self._quiz()
        checkbox = next(q for q in quiz.questions if q.type == "checkbox")
        answer = getattr(checkbox, "correct_answer", None)
        assert isinstance(answer, list)

    def test_code_and_url_media_present(self) -> None:
        """The quiz displays code blocks and a reference URL."""
        quiz = self._quiz()
        assert any(q.code is not None for q in quiz.questions)
        assert any(q.url is not None for q in quiz.questions)

    def test_regex_answer_matches_canonical_solution(self) -> None:
        """The accepts pattern accepts the canonical lambda answer."""
        quiz = self._quiz()
        regex_question = next(
            q
            for q in quiz.questions
            if getattr(q, "grading_type", None) == "regex"
        )
        pattern = getattr(regex_question, "accepts", None)
        assert isinstance(pattern, str)
        assert re.search(pattern, self.CANONICAL_LAMBDA) is not None
        assert re.search(pattern, self.WRONG_LAMBDA) is None

    def test_code_answer_is_readable(self) -> None:
        """The regex question shows readable code, not a pattern."""
        quiz = self._quiz()
        regex_question = next(
            q
            for q in quiz.questions
            if getattr(q, "grading_type", None) == "regex"
        )
        answer = getattr(regex_question, "correct_answer", None)
        assert isinstance(answer, list)
        contents = [(block.content or "").strip() for block in answer]
        assert "lambda x: x * x" in contents
        assert not any("^lambda" in content for content in contents)

    def test_confidence_question_is_pinned(self) -> None:
        """The confidence rating opts out of randomization."""
        quiz = self._quiz()
        confidence = next(q for q in quiz.questions if q.type == "rating")
        assert confidence.randomize is False
        assert quiz.questions[-1] is confidence
