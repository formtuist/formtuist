# Build Plan for Formtuist

This document records all the steps required to build Formtuist, a JSON-defined
form/survey/quiz tool with a Textual TUI, web serving, and response management.

______________________________________________________________________

## 1. Project Setup

### 1.1 Initialize Python Project with `uv`

- Run `uv init --package formtuist` to scaffold a modern Python package.
- This creates `pyproject.toml`, `src/formtuist/`, and the basic package
  structure.

### 1.2 Configure `pyproject.toml`

**Philosophy:** Quality gates (type checkers, linters, formatters) must be
integrated and active **before** any application code is written. The project
is configured from the first commit so that every module is created under
strict tooling.

Structure inspired by `gatorgrade`:

```toml
[project]
name = "formtuist"
version = "0.1.0"
description = "Formtuist — JSON-defined forms for terminal and web."
requires-python = ">=3.10,<4.0"
readme = "README.md"
dependencies = [
    "pydantic>=2.0.0",
    "textual>=1.0.0",
    "textual-serve>=1.1.0",
    "rich>=13.0.0",
    "datasette>=0.64.0",
    "click>=8.0.0",
]

[project.scripts]
formtuist = "formtuist.cli:main"

[dependency-groups]
dev = [
    "taskipy>=1.10.1,<2",
    "pytest>=8.0.0,<10",
    "pytest-cov>=6.0.0,<7",
    "pytest-sugar>=1.0.0,<2",
    "pytest-randomly>=3.12.0,<4",
    "pytest-clarity>=1.0.1,<2",
    "pytest-xdist>=3.8.0",
    "hypothesis>=6.155.2",
    "pydocstyle>=6.1.1,<7",
    "mypy>=1.11.2,<2",
    "ty>=0.0.8",
    "pyrefly>=1.0.0",
    "zuban>=0.7.2",
    "ruff>=0.15.15",
    "rumdl>=0.2.4",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**Application dependencies:**

- `pydantic` — JSON form schema validation
- `textual` — TUI framework
- `textual-serve` — web serving of Textual apps
- `rich` — rendering and formatting
- `datasette` — response browsing
- `click` — CLI entry point

**Development dependencies:**

- `taskipy` — task runner inside `pyproject.toml`
- `pytest` + `pytest-cov` + `pytest-sugar` + `pytest-randomly` +
  `pytest-clarity` + `pytest-xdist` — test execution
- `hypothesis` — property-based testing
- `mypy`, `ty`, `pyrefly`, `zuban` — parallel type checking
- `ruff` — linting and formatting
- `rumdl` — markdown linting
- `pydocstyle` — docstring conventions

### 1.3 Tool Configuration (All in `pyproject.toml`)

These sections are added alongside the dependencies and are enforced from the
first module:

**`[tool.taskipy.variables]`** — reusable path and command fragments:

- `project = "formtuist"`
- `tests = "tests"`
- `coveragefailunder = "95"`
- `ruff-check-command`, `ruff-format-command`, `mypy-command`, `ty-command`,
  `pyrefly-command`, `zuban-command`, `rumdl-command`

**`[tool.taskipy.tasks]`** — tasks that compose the variables:

- `all` → `task check && task test && task test-coverage-check`
- `check` → `task lint && task typecheck`
- `lint` → `task ruff-format && task ruff-check && task rumdl-check`
- `typecheck` → `task mypy && task ty && task pyrefly && task zuban`
- `ruff-check` → `ruff check {project} {tests}`
- `ruff-format` → `ruff format --check {project} {tests}`
- `format-fix` → `ruff format {project} {tests}`
- `rumdl-check` → `rumdl check`
- `rumdl-fix` → `rumdl fmt`
- `mypy` → `mypy {project}`
- `ty` → `ty check {project} {tests}`
- `pyrefly` → `pyrefly check {project} {tests}`
- `zuban` → `zuban check {project} {tests}`
- `test` → `pytest -x -s -vv`
- `test-parallel` → `pytest -x -s -vv -n auto -p no:sugar`
- `test-silent` → `pytest -x --show-capture=no -n auto`
- `test-coverage` → `pytest -s --cov=formtuist
--cov-branch --cov-fail-under={coveragefailunder}
--cov-report=term-missing tests/`
- `test-propertybased` → `pytest -x -s -vv -m propertybased`
- `test-not-propertybased` → `pytest -x -s -vv -m 'not propertybased'`
- `display` → `uv run formtuist display`
- `serve` → `uv run formtuist serve`
- `check-form` → `uv run formtuist check`

**`[tool.ruff]`** — line-length 79, select `E`, `D`, `I`, `F`, `PL`, `Q`,
`RUF`, `W`, `T201`; ignore `D203`, `D213`, `E501`.

**`[tool.mypy]`** — `disallow_untyped_defs = true`, `warn_return_any = true`,
`warn_unused_configs = true`, `ignore_missing_imports = true`.

**`[tool.pyrefly]`** — `preset = "legacy"`, `ignore-missing-imports = ["*"]`.

**`[tool.coverage.run]`** — `source = ["formtuist"]`, `branch = true`,
omit `tests/*` and `**/__init__.py`.

**`[tool.coverage.report]`** — `fail_under = 95`, `show_missing = true`,
`precision = 2`.

**`[tool.pytest.ini_options]`** — markers: `propertybased` for Hypothesis
tests.

### 1.4 Quality Gates — Active From the First Module

**Rule:** No `.py` file is committed to the repository until it passes:

1. `ruff format --check` (formatting)
1. `ruff check` (linting)
1. `mypy`, `ty`, `pyrefly`, `zuban` (all four type checkers)

This means the build order is:

1. `uv init --package formtuist`
1. Write `pyproject.toml` with all tool configs
1. Run `task lint` and `task typecheck` against the empty package to confirm
   the toolchain is wired correctly
1. Only then write `src/formtuist/__init__.py`, `schema.py`, etc.

Every new module added to the project must satisfy the four type checkers
before the PR / commit is considered valid.

### 1.5 Directory Structure

```text
formtuist/
├── pyproject.toml
├── README.md
├── PLAN.md
├── BUILD.md
├── src/
│   └── formtuist/
│       ├── __init__.py
│       ├── cli.py              # Click-based CLI entry point
│       ├── schema.py           # Pydantic models for form JSON
│       ├── parser.py           # JSON validation and parsing
│       ├── database.py         # SQLite storage layer
│       ├── exporter.py         # CSV / JSON / SQLite export
│       ├── grader.py           # Auto-grading logic
│       ├── tui/
│       │   ├── __init__.py
│       │   ├── app.py          # Main Textual App
│       │   ├── screens.py      # Welcome / Form / Submit / Grade screens
│       │   ├── widgets.py      # Question widgets (custom containers)
│       │   └── styles.tcss     # Textual CSS stylesheet
│       └── server.py           # textual-serve wrapper
├── tests/
│   ├── __init__.py
│   ├── test_schema.py
│   ├── test_parser.py
│   ├── test_database.py
│   ├── test_exporter.py
│   ├── test_grader.py
│   └── conftest.py
└── examples/
    ├── attendance.json
    ├── quiz.json
    └── survey.json
```

______________________________________________________________________

## 2. JSON Form Schema

### 2.1 Top-Level Structure

```json
{
  "name": "CS 101 Attendance",
  "description": "Daily attendance check-in",
  "config": {
    "randomize_questions": false,
    "auto_grade": false,
    "allow_multiple_submissions": true,
    "show_progress_bar": true
  },
  "questions": [
    {
      "id": "name",
      "text": "What is your full name?",
      "type": "short_text",
      "required": true
    },
    {
      "id": "mood",
      "text": "How are you feeling today?",
      "type": "rating",
      "required": false,
      "min": 1,
      "max": 5,
      "labels": ["Awful", "Bad", "Okay", "Good", "Great"]
    }
  ]
}
```

### 2.2 Question Types (v1)

| Type | Textual Widget(s) | Storage Type |
|---|---|---|
| `short_text` | `Input` | `TEXT` |
| `paragraph` | `TextArea` | `TEXT` |
| `multiple_choice` | `RadioSet` | `TEXT` (selected label) |
| `checkbox` | `SelectionList` | `JSON` (list of selected) |
| `numeric` | `Input` + `Integer` validator | `REAL` |
| `rating` | `RadioSet` (horizontal) or `Select` | `INTEGER` |
| `date` | `Input` + date validator | `TEXT` (ISO 8601) |
| `yes_no` | `Switch` or `Checkbox` | `INTEGER` (0/1) |

Each question accepts a `randomize` field that defaults to `true`. When
`config.randomize_questions` is enabled, a question with `randomize` set
to `false` keeps its exact file position while the remaining questions
are shuffled into the other positions. This suits questions that only
make sense at a fixed point, such as a closing confidence rating.

### 2.3 Grading Fields

Each question may optionally include:

```json
{
  "correct_answer": "...",
  "points": 10,
  "grading_type": "exact" | "regex" | "contains"
}
```

- For `multiple_choice`: `correct_answer` is the index or label of the correct
  option.
- For `checkbox`: `correct_answer` is a list of correct indices/labels.
- For `numeric`: `correct_answer` is a number (exact match) or a dict with
  `min`/`max` for range grading.
- For `yes_no`: `correct_answer` is a boolean (`true` or `false`) that is
  compared directly against the Switch value the student submits.
- For `short_text`/`paragraph`: `grading_type` selects exact, regex, or
  substring matching. `correct_answer` may be a plain string, a code block,
  or a list of code blocks when several answers are acceptable. An optional
  `accepts` regex holds a tolerant pattern used only for grading when
  `grading_type` is `regex`; it is never shown to students.

### 2.4 Extra Media Fields

Each question may optionally include:

```json
{
  "code": {
    "language": "python",
    "content": "def hello(): ..."
  },
  "image_path": "./diagram.png",
  "url": "https://example.com/reference"
}
```

A code block may instead reference a file that holds the source code, so
multi-line snippets can be pasted with real formatting and no escape
characters. Relative file paths resolve against the form file's directory,
or against the `--code-dir` option when it is given:

```json
{
  "code": {
    "language": "python",
    "file": "answers/snippet.py"
  }
}
```

Each block provides exactly one of `content` or `file`.

- `code` renders via Textual's `Markdown` widget with fenced code blocks.
- `image_path` is resolved relative to the form JSON file's directory.
- `url` renders as a clickable `Link` widget.

Media rendering details (terminal vs. web, `textual-image`, Sixel) are
discussed in section 4.2a below.

______________________________________________________________________

## 3. Core Modules

### 3.1 `schema.py` — Pydantic Data Models

All form JSON is validated through **Pydantic** before any rendering or storage
occurs. This provides:

- Type-safe parsing of the entire form definition
- Clear, line-oriented error messages when JSON is malformed
- Runtime validation of question IDs (unique), choice lists (non-empty),
  rating ranges (`min` < `max`), and grading fields
- Autogenerated JSON schema that can be used by editors for autocomplete

Build typed Pydantic models for:

- `FormConfig`
- `Question` (discriminated union by `type`)
- `CodeBlock`
- `FormDefinition`

Use `Literal` types for question types and grading modes. Use Pydantic
`Field(validators=...)` or custom `@field_validator` methods for cross-field
checks (e.g., ensure `checkbox` questions have at least one choice, ensure
`correct_answer` is present when `auto_grade` is enabled).

**Concrete model sketch:**

```python
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Annotated

class ShortTextQuestion(BaseModel):
    id: str
    text: str
    type: Literal["short_text"]
    required: bool = False

class MultipleChoiceQuestion(BaseModel):
    id: str
    text: str
    type: Literal["multiple_choice"]
    required: bool = False
    choices: list[str]
    correct_answer: str | None = None
    points: int = 0
    grading_type: Literal["exact"] = "exact"

    @field_validator("choices")
    @classmethod
    def choices_not_empty(cls, v: list[str]) -> list[str]:
        if len(v) < 2:
            raise ValueError("multiple_choice requires at least 2 choices")
        return v

# ... one model per question type ...

Question = Annotated[
    ShortTextQuestion
    | MultipleChoiceQuestion
    | CheckboxQuestion
    | NumericQuestion
    | RatingQuestion
    | DateQuestion
    | YesNoQuestion
    | ParagraphQuestion,
    Field(discriminator="type"),
]

class FormDefinition(BaseModel):
    name: str
    description: str = ""
    config: FormConfig = Field(default_factory=FormConfig)
    questions: list[Question]

    @field_validator("questions")
    @classmethod
    def ids_unique(cls, v: list[Question]) -> list[Question]:
        ids = [q.id for q in v]
        if len(ids) != len(set(ids)):
            raise ValueError("question ids must be unique")
        return v
```

Key Pydantic pattern: `Annotated[... , Field(discriminator="type")]` creates
a tagged union. Validation automatically selects the right subclass based on
the `type` field value.

### 3.2 `parser.py` — JSON Validation & Parsing

- Load raw JSON from file path.
- Parse and validate against Pydantic `FormDefinition` using
  `FormDefinition.model_validate_json()`.
- Catch `ValidationError` and pretty-print errors with JSON path references
  (e.g., `questions[2].choices: field required`).
- Resolve relative `image_path` values to absolute paths.
- Return a structured `FormDefinition` object that the rest of the application
  can trust is well-formed.

### 3.3 `database.py` — SQLite Storage

Design a SQLite schema:

```sql
CREATE TABLE responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    form_name TEXT NOT NULL,
    submitted_at TEXT NOT NULL,  -- ISO 8601
    answers_json TEXT NOT NULL,  -- JSON object mapping question_id -> answer
    grade_json TEXT              -- JSON grade snapshot (auto-graded forms)
);
```

`answers_json` holds only the raw answers. `grade_json` is a nullable
column that holds a JSON-safe copy of the grade report for submissions to
auto-graded forms, snapshotted at submit time (see sections 3.5 and 5.6).
Both columns are added to older databases by `_ensure_extra_columns()`.

**Concurrency safeguard — WAL mode is mandatory.**
Since `textual-serve` launches a **separate subprocess per student**, every
subprocess opens its own `sqlite3.Connection` to the same database file.
SQLite's default `journal_mode=DELETE` serializes writers and can throw
`OperationalError: database is locked` if the busy timeout is too short.

`init_db()` **must** run these pragmas on every connection:

```python
conn.execute("PRAGMA journal_mode=WAL;")
conn.execute("PRAGMA busy_timeout = 30000;")  # 30 seconds
```

WAL mode allows readers to proceed while a writer commits, and multiple
writers block each other only briefly. This is essential when 25 students
submit a timed quiz within a 10-second window.

Functions needed:

- `init_db(db_path: Path) -> sqlite3.Connection` — runs WAL + busy_timeout
- `save_response(conn, form_name: str, answers: dict) -> int`
- `update_response_grade(conn, response_id: int, grade: dict) -> None`
- `get_responses(conn, form_name: str | None) -> list[dict]`
- `get_response_count(conn, form_name: str) -> int`

`save_response` accepts an optional `grade` keyword argument holding a
JSON-safe report snapshot; `update_response_grade` overwrites the snapshot
for an existing row (used by `grade --recompute`).

### 3.4 `exporter.py` — Export Formats

- `export_to_jsonl(responses, output_path)`
- `export_to_csv(responses, output_path)`
- `export_to_sqlite(responses, output_path)` (for `datasette view`)

### 3.5 `grader.py` — Auto-Grading

- `grade_response(form_definition, answers) -> dict`
- Returns per-question score, total score, and feedback.
- Handle each `grading_type` (`exact`, `regex`, `contains`).
- Support partial credit for `checkbox` questions (e.g., proportion correct).

**Concrete grading logic sketch:**

```python
def grade_response(form: FormDefinition, answers: dict[str, Any]) -> dict:
    results = []
    total = 0
    max_total = 0
    for q in form.questions:
        if q.correct_answer is None:
            continue  # not a graded question
        score, max_score = _grade_question(q, answers.get(q.id))
        results.append({"id": q.id, "score": score, "max": max_score})
        total += score
        max_total += max_score
    return {
        "total": total,
        "max": max_total,
        "percentage": (total / max_total * 100) if max_total else 0,
        "breakdown": results,
    }
```

The report is converted into a JSON-safe snapshot for storage with
`grade_report_to_json()`, which turns `NumericRange` and `CodeBlock`
values into plain dicts and records a `graded_at` timestamp.

```python
def _grade_question(q, answer):
    if q.type == "multiple_choice":
        return (q.points, q.points) if answer == q.correct_answer else (0, q.points)
    elif q.type == "checkbox":
        correct = set(q.correct_answer)
        given = set(answer) if answer else set()
        if not correct:
            return (0, q.points)
        score = len(correct & given) / len(correct | given) * q.points
        return (round(score), q.points)
    elif q.type == "numeric" and isinstance(q.correct_answer, dict):
        # range grading
        if q.correct_answer["min"] <= answer <= q.correct_answer["max"]:
            return (q.points, q.points)
        return (0, q.points)
    elif q.grading_type == "regex":
        import re
        correct = re.search(q.correct_answer, str(answer))
        return (q.points, q.points) if correct else (0, q.points)
    elif q.grading_type == "contains":
        correct = q.correct_answer in str(answer)
        return (q.points, q.points) if correct else (0, q.points)
    else:  # exact
        exact = str(answer) == str(q.correct_answer)
        return (q.points, q.points) if exact else (0, q.points)
```

______________________________________________________________________

## 3.6 TUI Architecture Decision — Plain Textual Widgets

**Decision:** Build the TUI using **plain Textual widgets**, not
`textual-wtf`.

**Rationale:**

- All required question types are covered by built-in Textual widgets:
  `Input`, `TextArea`, `RadioSet`, `SelectionList`, `Switch`, `Select`.
- Since forms are defined in JSON (not Python classes), adopting
  `textual-wtf` would require a **dynamic class-generation layer** that
  constructs `textual-wtf.Form` subclasses at runtime. This adds
  indirection without reducing boilerplate.
- `textual-wtf` lacks first-class support for `RadioSet` (visible options),
  `SelectionList` (multi-select), rating scales, and date entry — all
  required for Formtuist v1.
- Media display (code blocks with syntax highlighting, image hints,
  clickable URLs) needs fine-grained layout control that `textual-wtf`'s
  `layout()` helpers cannot easily accommodate.
- One fewer third-party dependency reduces maintenance risk.

**The pipeline is therefore:**

```text
JSON form → Pydantic validation → Custom widgets.py → FormScreen compose()
```

`Pydantic` remains the mandatory first validation gate. The TUI layer is
responsible only for rendering and data collection, never for schema
validation.

______________________________________________________________________

## 4. TUI Implementation (Textual)

### 4.0 Target Platform — Laptop-Only

**Scope constraint:** Formtuist is designed for students filling out forms
on **laptops or desktop computers**. It is **not** targeting phones, tablets,
or other mobile devices.

**Why this matters:**

- The TUI assumes a keyboard (Tab, Enter, Ctrl+S) and a terminal-sized
  viewport. These are laptop-native interactions.
- The `textual-serve` web mode renders an `xterm.js` terminal emulator in the
  browser. This is usable on a laptop with a keyboard and a reasonably wide
  screen. On a phone, a terminal emulator is cramped and frustrating.
- Keyboard shortcuts (`^s` to submit, arrow keys for `RadioSet`) are core to
  the experience and do not translate to touch interfaces.
- Images rendered via `textual-image` (Sixel / TGP / Unicode fallback) are
  sized for terminal cells, not responsive mobile viewports.

**Consequence:** The TUI layout, web-serving expectations, and UX copy can
all assume a laptop user. No responsive design, no touch targets, no mobile
viewport testing is required for v1.

### 4.1 Widget Selection per Question Type

| Question Type | Primary Widget | Supporting Widgets |
|---|---|---|
| `short_text` | `Input` | `Label` (question text) |
| `paragraph` | `TextArea` | `Label` |
| `multiple_choice` | `RadioSet` | `Label`, `RadioButton` |
| `checkbox` | `SelectionList` | `Label` |
| `numeric` | `Input` + validator | `Label` |
| `rating` | `RadioSet` (or `Select`) | `Label` |
| `date` | `Input` + validator | `Label` |
| `yes_no` | `Switch` | `Label` |

### 4.2 Custom Widget: `QuestionContainer`

Create a composite widget that wraps each question:

```python
class QuestionContainer(Static):
    """Displays a question, its media, and its input widget."""
```

Composition:

- `Label` for question text (bold, wrapped)
- Optional `Static` for code block (with syntax highlighting via Rich)
- Optional `Static` for image path / URL hint
- The input widget appropriate for the question type
- `Rule` (divider) between questions

### 4.2a Image Rendering — `textual-image`

`textual-image` (<https://github.com/lnqs/textual-image>) provides Textual
widgets and Rich renderables that display images via:

- **Terminal Graphics Protocol (TGP)** — Kitty, WezTerm
- **Sixel** — iTerm2, Windows Terminal, VS Code, xterm, foot, konsole, etc.
- **Unicode fallback** — block characters for unsupported terminals

**Terminal mode:** `textual-image` is an excellent fit. Add it as an
optional dependency (`textual-image[textual]`) and use its widget inside
`QuestionContainer` when `image_path` is present.

**Web mode (`textual-serve`):** Plausible but **experimental**.

- `textual-serve` streams ANSI escape codes to an `xterm.js` terminal
  emulator in the browser.
- Modern `xterm.js` does support Sixel.
- `textual-image` embeds image data as Sixel sequences (base64-ish text),
  which travels naturally over the WebSocket as part of the terminal stream.
- **Risk:** Browser performance with large images, xterm.js Sixel bugs, and
  the requirement that the server process can read the image file at the
  resolved absolute path.

**Decision:** Use `textual-image` for the terminal TUI. For the web mode,
document image display as **best-effort / experimental**, with a graceful
fallback to showing the image filename/path as text.

### 4.3 TUI Layout Design

**Goal:** Simple, clear, single-column scrolling layout.

```text
+--------------------------------------------------+
|  󰋼 Formtuist — CS 101 Attendance          1/3   |
+--------------------------------------------------+
|                                                  |
|  ┌─ Question 1 ─────────────────────────────┐   |
|  │ What is your full name?                  │   |
|  │ * Required                               │   |
|  │ [____________________________________]   │   |
|  └─────────────────────────────────────────┘   |
|                                                  |
|  ┌─ Question 2 ─────────────────────────────┐   |
|  │ Rate your understanding:                 │   |
|  │ ( ) 1 - Poor                             │   |
|  │ ( ) 2 - Fair                             │   |
|  │ (*) 3 - Good                             │   |
|  │ ( ) 4 - Excellent                        │   |
|  └─────────────────────────────────────────┘   |
|                                                  |
|  ... (scrollable)                                |
|                                                  |
+--------------------------------------------------+
|  [Submit]                         ^s Submit    |
+--------------------------------------------------+
```

Textual containers to use:

- `ScrollableContainer` (or `VerticalScroll`) for the question list
- `Grid` or `Vertical` layout inside the scroll area
- `Header` and `Footer` for app chrome
- `Button` for submit (also bind `ctrl+s`)

### 4.4 Screens

| Screen | Purpose |
|---|---|
| `WelcomeScreen` | Display form name, description, instructions, "Start" button |
| `FormScreen` | The actual scrolling form with all questions |
| `SubmitScreen` | Confirmation + thank you message after submission |
| `GradeScreen` | Shows score breakdown (used by `grade` command or post-submit) |

### 4.5 TUI CSS (`styles.tcss`)

Define:

- `QuestionContainer` border, padding, margin
- Focus styles for input widgets
- Required question indicator (red asterisk)
- Progress bar styling

______________________________________________________________________

### 4.6 TUI Implementation Details — Buildable Specification

This section closes the ambiguity gaps for an AI agent implementing the TUI.

### 4.6.1 Widget Factory — `make_question_widget()`

`widgets.py` contains a dispatch function that creates the correct input
widget for each `Question` type:

```python
from textual.widgets import (
    Input, TextArea, RadioSet, RadioButton,
    SelectionList, Switch, Select,
)
from textual.validation import Integer, Number

def make_input_widget(question: Question) -> Widget:
    """Return the appropriate input widget for a question."""
    if question.type == "short_text":
        return Input(placeholder="Type your answer...")
    elif question.type == "paragraph":
        return TextArea()
    elif question.type == "multiple_choice":
        return RadioSet(*question.choices)
    elif question.type == "checkbox":
        # SelectionList takes tuples of (label, value, initial_selected)
        return SelectionList(*[(c, c, False) for c in question.choices])
    elif question.type == "numeric":
        return Input(validators=[Integer()])
    elif question.type == "rating":
        # RadioSet for visibility; labels like "1 - Poor"
        return RadioSet(*question.labels)
    elif question.type == "date":
        return Input(placeholder="YYYY-MM-DD")
    elif question.type == "yes_no":
        return Switch()
    else:
        raise ValueError(f"unknown question type: {question.type}")
```

### 4.6.2 `QuestionContainer` — Composite Widget API

````python
from textual.containers import Vertical
from textual.widgets import Label, Static, Rule
from textual.widget import Widget

class QuestionContainer(Vertical):
    """Wraps a question: text, optional media, input widget, divider."""

    def __init__(self, question: Question) -> None:
        self.question = question
        super().__init__()

    def compose(self) -> ComposeResult:
        # Question text (bold, wrapped)
        required_marker = " [red]*[/red]" if self.question.required else ""
        yield Label(f"[bold]{self.question.text}[/bold]{required_marker}")

        # Optional code block
        if self.question.code:
            code_text = f"```{self.question.code.language}\n{self.question.code.content}\n```"
            yield Static(code_text)  # Rich markdown-like rendering via Static

        # Optional image
        if self.question.image_path:
            # Terminal: textual-image widget. Web: falls back to text path.
            yield Static(f"[Image: {self.question.image_path}]")

        # Optional URL
        if self.question.url:
            yield Static(f"[@click=app.open_url('{self.question.url}')]Reference[/]")

        # The actual input widget
        self.input_widget = make_input_widget(self.question)
        yield self.input_widget

        # Divider between questions
        yield Rule()

    def get_answer(self) -> Any:
        """Extract the answer value from the input widget."""
        w = self.input_widget
        if isinstance(w, Input):
            return w.value
        elif isinstance(w, TextArea):
            return w.text
        elif isinstance(w, RadioSet):
            # pressed_button may be None if nothing selected
            return w.pressed_button.label if w.pressed_button else None
        elif isinstance(w, SelectionList):
            return [w.get_option_at_index(i).prompt for i in w.selected_indices]
        elif isinstance(w, Switch):
            return w.value
        else:
            return None

    def set_error(self, message: str) -> None:
        """Show a validation error next to the question."""
        # Add a red error label; remove it when fixed
        self.error_label = Label(f"[red]{message}[/red]")
        self.mount(self.error_label, after=self.input_widget)

    def clear_error(self) -> None:
        """Remove any validation error label."""
        if hasattr(self, "error_label"):
            self.error_label.remove()
            delattr(self, "error_label")
````

### 4.6.3 `FormScreen` — State, Compose, Submit

```python
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label

class FormScreen(Screen):
    BINDINGS = [
        ("ctrl+s", "submit", "Submit"),
    ]

    def __init__(self, form: FormDefinition, db_path: Path) -> None:
        self.form = form
        self.db_path = db_path
        self.question_containers: list[QuestionContainer] = []
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            yield Label(f"[bold]{self.form.name}[/bold]")
            if self.form.description:
                yield Label(self.form.description)
            for question in self.form.questions:
                container = QuestionContainer(question)
                self.question_containers.append(container)
                yield container
            yield Button("Submit", id="submit", variant="primary")
        yield Footer()

    def action_submit(self) -> None:
        """Validate, collect answers, save to DB, push SubmitScreen."""
        answers: dict[str, Any] = {}
        valid = True
        for qc in self.question_containers:
            answer = qc.get_answer()
            qc.clear_error()
            if qc.question.required and (answer is None or answer == ""):
                qc.set_error("This question is required.")
                valid = False
            answers[qc.question.id] = answer

        if not valid:
            self.notify("Please fix the errors above.", severity="error")
            return

        # Save to SQLite
        conn = init_db(self.db_path)
        save_response(conn, self.form.name, answers)
        conn.close()

        # Show confirmation
        self.app.push_screen(SubmitScreen())
```

### 4.6.4 Screen Transition Flow

```text
WelcomeScreen  --[Start button]-->  FormScreen
  --[Ctrl+S or Submit]-->  SubmitScreen
```

If `form.config.auto_grade` is true, `SubmitScreen` shows the score and
a review of every question the student answered incorrectly, including
the student's answer and the correct answer. When all answers are
correct, it shows an all-correct message instead. The same report is
persisted as a JSON-safe snapshot in the response row's `grade_json`
column so the recorded score is immutable and matches what the student
saw; the `grade` command reports it later (see section 5.6).

### 4.6.5 Data Passing — `FormApp` Constructor

```python
from textual.app import App

class FormApp(App):
    CSS_PATH = "styles.tcss"

    def __init__(self, form: FormDefinition, db_path: Path) -> None:
        self.form = form
        self.db_path = db_path
        super().__init__()

    def on_mount(self) -> None:
        self.push_screen(WelcomeScreen(self.form, self.db_path))
```

The `display` CLI command creates `FormApp(form, db_path)` and calls
`app.run()`.

______________________________________________________________________

## 5. CLI Commands

### 5.1 `check <form.json>`

1. Parse and validate JSON against schema.
1. Report errors with line numbers if invalid.
1. Print summary: question count, required vs optional, grading enabled?
1. Model validation also rejects authoring traps: `auto_grade` enabled
   with no graded questions, `regex` grading with a missing or broken
   pattern, `accepts` set without `regex` grading, and `correct_answer`
   values that are not among a question's choices. The
   `examples/invalid_*.json` files demonstrate each trap.

### 5.2 `display <form.json> [--db <responses.db>]`

1. Parse form JSON.
1. Initialize/connect to SQLite DB.
1. Launch Textual app (`FormScreen`).
1. On submit, validate required fields.
1. Save response to DB.
1. Show `SubmitScreen`.

### 5.3 `serve <form.json> [--host <host>] [--port <port>] [--db <responses.db>]`

1. Parse form JSON.
1. Build a small wrapper script that calls `display` with the given args.
1. Launch `textual_serve.Server` with the wrapper command.
1. Server spawns an independent subprocess per visitor — safe for concurrent
   classroom use.

### 5.4 `export <responses.db> --format {csv,json,sqlite} --output <path>`

1. Query all responses from DB.
1. Convert to target format.
1. Write to output path.

### 5.5 `view <responses.db> [--datasette-args ...]`

1. Check that `datasette` is installed.
1. Launch `datasette serve <responses.db>` with optional args.
1. Print URL to console.

### 5.6 `grade <form.json> <responses.db> [--recompute]`

1. Load form definition (with `correct_answer` fields).
1. Load all responses from DB.
1. For each response, report the stored `grade_json` snapshot when
   present; responses without a snapshot (older databases,
   non-auto-graded forms) are graded on the fly with
   `grader.grade_response()`.
1. Output a grade report table with per-question and total scores.

`--recompute` re-grades every response with the current form and writes
the fresh snapshots back to the database. This is the tool to use after
correcting a question or point value: run it once to refresh all stored
grades, otherwise editing the form never changes recorded scores.

______________________________________________________________________

## 6. Web Serving Architecture

### 6.1 How `textual-serve` Fits

- `textual-serve` launches a **new subprocess per visitor** via WebSocket.
- This means 30 students hitting the URL = 30 independent `formtuist display`
  processes.
- Each process has its own SQLite connection. SQLite handles concurrent reads
  well; writes may block briefly but are safe.

### 6.2 Wrapper Command — `server.py`

`server.py` is a thin Click command that wraps `textual-serve`:

```python
from textual_serve.server import Server

@click.command()
@click.argument("form_path", type=click.Path(exists=True))
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000)
@click.option("--db", default="responses.db")
def serve(form_path: str, host: str, port: int, db: str) -> None:
    form = parse_form(Path(form_path))
    cmd = f"formtuist display {form_path} --db {db}"
    server = Server(
        cmd,
        host=host,
        port=port,
        title=form.name,
    )
    click.echo(f"Serving {form.name} at http://{host}:{port}")
    server.serve()
```

Key points:

- The command string is exactly what a user would type in a shell.
- `textual-serve` spawns a new Python process running that command for every
  visitor.
- The form JSON is parsed once in the server process only to get the title.
- Each visitor's subprocess does its own form parsing and DB writes.
- `--public-url` can be passed if behind a reverse proxy (e.g., Cloudflare
  tunnel).

### 6.3 Public URL Support

- If behind a Cloudflare tunnel, pass `--public-url` or set the
  `public_url` kwarg on `Server` so Textual generates correct shareable links.

______________________________________________________________________

## 7. Testing Strategy

### 7.1 Unit Tests

- `test_schema.py`: Validate that valid JSON passes and invalid JSON raises.
- `test_parser.py`: Test image path resolution, error messages.
- `test_database.py`: Test CRUD, concurrent writes, isolation.
- `test_exporter.py`: Round-trip export → re-import checks.
- `test_grader.py`: Test exact, regex, contains, range, and partial credit.

### 7.2 Property-Based Tests (Hypothesis)

- Generate random valid `FormDefinition` objects and ensure serialization
  round-trips.
- Generate random answer dicts and ensure grading never crashes.

### 7.3 TUI Tests (Textual Pilot)

- Use `textual.pilot` to simulate key presses and widget interactions.
- Test that Tab moves focus, Submit saves to DB, required validation fires.

### 7.4 Integration Tests

- Run `formtuist check` against all `examples/*.json`.
- Run `formtuist display` in headless mode and verify DB write.

### 7.5 Direct-Test Coverage Checkers

Two companion scripts answer the question "how much of the package is
directly tested?" Both write the same JSON report schema (functions
keyed by `file:name:line`, a summary, and per-category lists) so their
results can be diffed directly:

- `scripts/tsc_treesitter.py` (run `uv run task test-coverage-check`):
  the tree-sitter baseline. It parses CSTs and matches test-suite call
  names against source function names, so a call like `screen.compose()`
  credits every function named `compose`.
- `scripts/tsc_trailmark.py` (run `uv run task test-coverage-check-trailmark`):
  the trailmark implementation. It parses the whole project into a code
  graph with `QueryEngine.from_graph` and credits a function only when a
  test reaches it through a resolved call edge, or when an unresolved
  call name matches exactly one source function. Ambiguous names such as
  `compose` (four definitions) are never given blanket credit; instead
  every candidate is marked unresolved (possibly tested), and unresolved
  functions are excluded from the directly-tested percentage so they are
  not held against the threshold.

`uv run task test-coverage-compare` prints a side-by-side summary of
`tsc-treesitter.json` and `tsc-trailmark.json` plus every per-function status
disagreement. Both checks fail when the directly tested percentage
falls below `directtestedfailunder` (75) in `pyproject.toml`, and both
are part of `task all`.

______________________________________________________________________

## 8. Example Forms (for `examples/`)

### 8.1 `attendance.json`

- Name (short_text, required)
- Present? (yes_no, required)
- Mood (rating, optional)

### 8.2 `quiz.json`

- Multiple choice with `correct_answer`
- Short answer with `correct_answer` + `grading_type: "contains"`
- Numeric with `correct_answer` range

### 8.3 `survey.json`

- Paragraph feedback
- Checkbox (select all that apply)

### 8.4 `method_invocation_quiz.json`

- A graded quiz about how method calls in Python are resolved to the
  definitions they invoke, based on `answers/trailmark_demo.py`
- Multiple choice, checkbox, short text (regex), yes/no, numeric, and
  paragraph-adjacent questions, plus a confidence rating
- Embeds the demo program via `answers/trailmark_demo.py`
- Date field

### 8.5 `yes_no_quiz.json`

- A short auto-graded quiz where every question is a `yes_no` question
  with a `correct_answer` of `true` or `false` and a `points` value
- Demonstrates automatic true/false grading against the Switch answer

______________________________________________________________________

## 9. Known Similar Tools (Research Notes)

The following tools overlap with Formtuist but do **not** match the exact
combination of JSON-defined + Textual TUI + web-serve + SQLite + datasette:

| Tool | Overlap | Difference |
|---|---|---|
| `tui-forms` | TUI forms from JSONSchema | No web serving, no SQLite, no grading |
| `textual-forms` | Dynamic forms in Textual | No JSON input, no web serving |
| `fstui` | Form generation from Pydantic | No JSON editor workflow, no web serving |
| SurveyJS | JSON-defined forms | Web-only (JS), no TUI |
| Formbricks | Open-source surveys | Web-only, heavy infrastructure |
| LimeSurvey | Mature survey platform | PHP/web, not TUI-first |

Formtuist is unique in targeting the **terminal-first, JSON-edited, professor
workflow** with trivial web deployment via `textual-serve`.

______________________________________________________________________

## 10. Open Questions to Resolve During Build

1. Should `rating` use a horizontal `RadioSet` or a `Select` dropdown?
   - Recommendation: `RadioSet` for visibility of all options at once.
1. How should image paths work when served via `textual-serve` on a remote
   machine?
   - Images referenced by URL work everywhere. Local paths require the image to
     exist on the server. Consider adding a `--assets-dir` flag.
   - `textual-image` handles local image rendering in the terminal; web mode
     is experimental Sixel-over-xterm.js.
1. Should responses include a unique submission ID shown to the student?
   - Useful for "I submitted, here's my proof." Add a `submission_id` UUID.
1. Should there be an `anonymous` mode that does not collect names?
   - Add `config.anonymous` flag; if true, skip name field or do not store
     identifying info.

______________________________________________________________________

## 11. Risk Assessment Summary

### Highest Risk: Image Display in Web Mode

- `textual-image` works beautifully in native terminals (TGP/Sixel/Unicode
  fallback).
- Through `textual-serve` → xterm.js, it depends on Sixel support in the
  browser terminal emulator. Performance and compatibility are unverified.
- **Mitigation:** Ship images as terminal-first, web-experimental, with a
  text-path fallback.

### High Risk: SQLite Locking Under Classroom Load

- 25+ concurrent subprocesses writing to one SQLite file can hit lock errors
  if WAL mode and busy_timeout are not configured.
- **Mitigation:** `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=30000`
  are mandatory in `init_db()`. This is a one-line fix but must not be
  forgotten.

### Moderate Risk: Grading Logic Edge Cases

- `correct_answer` has different semantics per question type (string, list,
  number, regex). Partial credit for checkboxes is easy to get wrong.
- **Mitigation:** Exhaustive unit tests for every `grading_type` before any
  release.

### Low Risk: Datasette with JSON-Blob Schema

- Answers are stored as one JSON blob per response. Datasette will show raw
  JSON unless a flattened view is added.
- **Mitigation:** Add a helper that creates a `responses_flat` view or a
  temporary flattened table before running `datasette serve`.

______________________________________________________________________

## 12. Priorities for Proof-of-Concept

To get a usable proof-of-concept quickly:

1. **Schema + Parser**: Define the JSON schema and validate it.
1. **SQLite DB**: Create `database.py` with `save_response`.
1. **Basic TUI**: A single `FormScreen` using `VerticalScroll` + `Input` +
   `RadioSet` + `Button`. No custom widgets yet — just compose directly.
1. **`display` command**: Wire CLI → parser → TUI → DB.
1. **`serve` command**: Wrap `display` in `textual-serve.Server`.
1. **`check` command**: Validate JSON and print summary.

Defer to later:

- Code block syntax highlighting in TUI
- Image display
- `grade` command
- `export` command
- `view` command
- Custom `QuestionContainer` widget
- Progress bar

______________________________________________________________________

*This build plan is a living document. Update it as decisions change during
implementation.*
