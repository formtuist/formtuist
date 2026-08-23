"""Pydantic models for validating JSON form definitions."""

import re
from enum import Enum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


class AuthProvider(str, Enum):
    """The identity providers that a form can require."""

    GITHUB = "github"


# question type identifiers used by the widget factory at runtime; the
# Literal annotations below must stay literal values for type checkers
QUESTION_TYPE_SHORT_TEXT = "short_text"
QUESTION_TYPE_PARAGRAPH = "paragraph"
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_CHECKBOX = "checkbox"
QUESTION_TYPE_NUMERIC = "numeric"
QUESTION_TYPE_RATING = "rating"
QUESTION_TYPE_DATE = "date"
QUESTION_TYPE_YES_NO = "yes_no"

# grading modes for questions that have a correct answer
GRADING_TYPE_EXACT = "exact"
GRADING_TYPE_REGEX = "regex"
GRADING_TYPE_CONTAINS = "contains"

# review modes for post-grading of responses
REVIEW_NONE = "none"
REVIEW_PERMITTED = "permitted"
REVIEW_REQUIRED = "required"
REVIEW_FIELD = "review"
REVIEW_LITERAL = Literal["none", "permitted", "required"]

# a single-submission form must identify repeat users to block them
SINGLE_SUBMISSION_REQUIRES_AUTH_ERROR = (
    "allow_multiple_submissions is false but auth is not set: "
    "single-submission forms require a GitHub auth provider so that "
    "duplicate submissions can be blocked by identity"
)


class FormConfig(BaseModel):
    """Configuration options for a form."""

    randomize_questions: bool = False
    auto_grade: bool = False
    allow_multiple_submissions: bool = True
    auth: AuthProvider | None = None

    # without an auth provider there is no identity to check, so the
    # single-submission promise cannot be kept and the form must be rejected
    @model_validator(mode="after")
    def _single_submission_requires_auth(self) -> "FormConfig":
        """Require an auth provider when resubmission is forbidden."""
        if not self.allow_multiple_submissions and self.auth is None:
            raise ValueError(SINGLE_SUBMISSION_REQUIRES_AUTH_ERROR)
        return self


# validation context key carrying the base directory for code files
CODE_DIR_CONTEXT_KEY = "code_dir"

# encoding used when loading code from referenced files
CODE_ENCODING = "utf-8"


class CodeBlock(BaseModel):
    """A source code snippet displayed alongside a question."""

    language: str
    content: str | None = None
    file: str | None = None

    # a code block is either written inline or loaded from a file
    @model_validator(mode="after")
    def _load_content(self, info: ValidationInfo) -> "CodeBlock":
        """Load file-based code, or require exactly one source."""
        if self.file is not None:
            if self.content is not None:
                raise ValueError("provide either content or file, not both")
            candidate = self._code_path(info)
            try:
                self.content = candidate.read_text(encoding=CODE_ENCODING)
            except OSError as error:
                raise ValueError(
                    f"cannot read code file {candidate}: {error}"
                ) from error
        elif self.content is None:
            raise ValueError("provide exactly one of content or file")
        return self

    def _code_path(self, info: ValidationInfo) -> Path:
        """Resolve a file reference against the code base directory."""
        candidate = Path(self.file or "")
        if candidate.is_absolute():
            return candidate
        base = Path.cwd()
        if info.context is not None:
            code_dir = info.context.get(CODE_DIR_CONTEXT_KEY)
            if code_dir is not None:
                base = Path(code_dir)
        return base / candidate


# a code answer may be a single block or several acceptable segments
CodeAnswer = str | CodeBlock | list[CodeBlock]


# validate that an accepts pattern compiles as a regular expression
GRADING_LITERAL = Literal["exact", "regex", "contains"]


def _validate_regex_fields(
    accepts: str | None,
    grading_type: GRADING_LITERAL | None,
    correct_answer: CodeAnswer | None,
) -> None:
    """Raise when accepts or regex grading fields are misconfigured."""
    if accepts is not None and grading_type != GRADING_TYPE_REGEX:
        raise ValueError("accepts requires grading_type to be regex")
    if grading_type == GRADING_TYPE_REGEX:
        pattern = accepts
        if pattern is None and isinstance(correct_answer, str):
            pattern = correct_answer
        if pattern is None:
            raise ValueError(
                "regex grading requires accepts or a string correct_answer"
            )
        try:
            re.compile(pattern)
        except re.error as error:
            raise ValueError(
                f"regex pattern does not compile: {error}"
            ) from error


def _validate_accepts(v: str | None) -> str | None:
    """Return the pattern when it compiles, otherwise raise a ValueError."""
    if v is not None:
        try:
            re.compile(v)
        except re.error as error:
            raise ValueError(
                f"accepts is not a valid regex: {error}"
            ) from error
    return v


class _QuestionBase(BaseModel):
    """Base fields shared by all question types."""

    id: str
    text: str
    required: bool = False
    # when false, the question keeps its file position during randomization
    randomize: bool = True
    # when true, a choice question's options render in shuffled order
    randomize_choices: bool = False
    code: CodeBlock | None = None
    image_path: str | None = None
    url: str | None = None
    review: REVIEW_LITERAL = REVIEW_NONE  # type: ignore[assignment]

    # permitted requires a correct answer; required may be manual
    @model_validator(mode="after")
    def _review_requires_correct_answer(self) -> "_QuestionBase":
        """Validate review mode against correct_answer presence."""
        review = getattr(self, "review", REVIEW_NONE)
        correct = getattr(self, "correct_answer", None)
        if review == REVIEW_PERMITTED and correct is None:
            raise ValueError("review permitted requires a correct_answer")
        return self


class ShortTextQuestion(_QuestionBase):
    """A single-line text input question."""

    type: Literal["short_text"]
    correct_answer: CodeAnswer | None = None
    accepts: str | None = None
    points: int = 0
    grading_type: GRADING_LITERAL | None = None

    # ensure an accepts pattern is a usable regular expression
    @field_validator("accepts")
    @classmethod
    def _accepts_is_valid_regex(cls, v: str | None) -> str | None:
        """Validate that an accepts pattern compiles as a regex."""
        return _validate_accepts(v)

    # ensure accepts and regex grading agree with each other
    @model_validator(mode="after")
    def _regex_fields_valid(self) -> "ShortTextQuestion":
        """Validate the accepts and regex grading configuration."""
        _validate_regex_fields(
            self.accepts, self.grading_type, self.correct_answer
        )
        return self


class ParagraphQuestion(_QuestionBase):
    """A multi-line text input question."""

    type: Literal["paragraph"]
    correct_answer: CodeAnswer | None = None
    accepts: str | None = None
    points: int = 0
    grading_type: GRADING_LITERAL | None = None

    # ensure an accepts pattern is a usable regular expression
    @field_validator("accepts")
    @classmethod
    def _accepts_is_valid_regex(cls, v: str | None) -> str | None:
        """Validate that an accepts pattern compiles as a regex."""
        return _validate_accepts(v)

    # ensure accepts and regex grading agree with each other
    @model_validator(mode="after")
    def _regex_fields_valid(self) -> "ParagraphQuestion":
        """Validate the accepts and regex grading configuration."""
        _validate_regex_fields(
            self.accepts, self.grading_type, self.correct_answer
        )
        return self


MIN_CHOICES_FOR_MULTIPLE_CHOICE = 2


class MultipleChoiceQuestion(_QuestionBase):
    """A single-select multiple choice question."""

    type: Literal["multiple_choice"]
    choices: list[str]
    correct_answer: str | None = None
    points: int = 0
    grading_type: Literal["exact"] | None = "exact"

    # ensure at least two choices exist for a meaningful selection
    @field_validator("choices")
    @classmethod
    def _choices_min_two(cls, v: list[str]) -> list[str]:
        """Validate at least 2 choices are provided."""
        if len(v) < MIN_CHOICES_FOR_MULTIPLE_CHOICE:
            raise ValueError("multiple_choice requires at least 2 choices")
        return v

    # the correct answer must always be selectable
    @model_validator(mode="after")
    def _correct_answer_in_choices(self) -> "MultipleChoiceQuestion":
        """Validate that the correct answer is one of the choices."""
        if (
            self.correct_answer is not None
            and self.correct_answer not in self.choices
        ):
            raise ValueError("correct_answer must be one of the choices")
        return self


class CheckboxQuestion(_QuestionBase):
    """A multi-select checkbox question."""

    type: Literal["checkbox"]
    choices: list[str]
    correct_answer: list[str] | None = None
    points: int = 0
    grading_type: Literal["exact"] | None = "exact"

    # ensure at least one checkbox option is defined
    @field_validator("choices")
    @classmethod
    def _choices_min_one(cls, v: list[str]) -> list[str]:
        """Validate at least 1 choice is provided."""
        if len(v) < 1:
            raise ValueError("checkbox requires at least 1 choice")
        return v

    # every correct answer must always be selectable
    @model_validator(mode="after")
    def _correct_answers_in_choices(self) -> "CheckboxQuestion":
        """Validate that every correct answer is one of the choices."""
        if self.correct_answer is not None:
            missing = set(self.correct_answer) - set(self.choices)
            if missing:
                raise ValueError(
                    "correct_answer includes choices that do not exist: "
                    f"{sorted(missing)}"
                )
        return self


class NumericRange(BaseModel):
    """A numeric range for grading answers by min/max bounds."""

    min: float
    max: float


class NumericQuestion(_QuestionBase):
    """A numeric input question with optional range grading."""

    type: Literal["numeric"]
    correct_answer: float | NumericRange | None = None
    points: int = 0
    grading_type: Literal["exact"] | None = "exact"


class RatingQuestion(_QuestionBase):
    """A rating scale question with min, max, and labelled options."""

    type: Literal["rating"]
    min: int
    max: int
    labels: list[str]

    # cross-field check: max must be strictly greater than min
    @model_validator(mode="after")
    def _min_less_than_max(self) -> "RatingQuestion":
        """Validate rating min is strictly less than max."""
        if self.max <= self.min:
            raise ValueError("rating max must be greater than min")
        return self


class DateQuestion(_QuestionBase):
    """A date input question expecting ISO 8601 format."""

    type: Literal["date"]


class YesNoQuestion(_QuestionBase):
    """A yes or no question using a binary switch."""

    type: Literal["yes_no"]
    correct_answer: bool | None = None
    points: int = 0
    grading_type: Literal["exact"] | None = "exact"


# discriminated union: selects the correct model class based on the type field
Question = Annotated[
    ShortTextQuestion
    | ParagraphQuestion
    | MultipleChoiceQuestion
    | CheckboxQuestion
    | NumericQuestion
    | RatingQuestion
    | DateQuestion
    | YesNoQuestion,
    Field(discriminator="type"),
]


class FormDefinition(BaseModel):
    """Top-level form definition containing metadata, config, and questions."""

    name: str
    version: str | None = None
    description: str = ""
    config: FormConfig = Field(default_factory=FormConfig)
    questions: list[Question]

    # prevent two questions from sharing the same identifier
    @field_validator("questions")
    @classmethod
    def _ids_unique(cls, v: list[Question]) -> list[Question]:
        """Validate all question ids are unique."""
        ids = [q.id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return v

    # auto-grading needs at least one question with a correct answer
    @model_validator(mode="after")
    def _auto_grade_has_graded_question(self) -> "FormDefinition":
        """Validate that auto-grading has questions to grade."""
        if self.config.auto_grade:
            graded = [
                question
                for question in self.questions
                if getattr(question, "correct_answer", None) is not None
                or getattr(question, "review", REVIEW_NONE) == REVIEW_REQUIRED
            ]
            if not graded:
                raise ValueError(
                    "auto_grade is enabled but no question has a correct_answer"
                )
        return self
