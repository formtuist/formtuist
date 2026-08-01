"""Pydantic models for validating JSON form definitions."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class FormConfig(BaseModel):
    """Configuration options for a form."""

    randomize_questions: bool = False
    auto_grade: bool = False
    allow_multiple_submissions: bool = True
    anonymous: bool = False
    auth: Literal["github"] | None = None


class CodeBlock(BaseModel):
    """A source code snippet displayed alongside a question."""

    language: str
    content: str


class _QuestionBase(BaseModel):
    """Base fields shared by all question types."""

    id: str
    text: str
    required: bool = False
    code: CodeBlock | None = None
    image_path: str | None = None
    url: str | None = None


class ShortTextQuestion(_QuestionBase):
    """A single-line text input question."""

    type: Literal["short_text"]
    correct_answer: str | None = None
    points: int = 0
    grading_type: Literal["exact", "regex", "contains"] | None = None


class ParagraphQuestion(_QuestionBase):
    """A multi-line text input question."""

    type: Literal["paragraph"]
    correct_answer: str | None = None
    points: int = 0
    grading_type: Literal["exact", "regex", "contains"] | None = None


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
