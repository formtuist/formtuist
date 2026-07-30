# Build Plan for Formtuitous

This document records all the steps required to build Formtuitous, a JSON-defined
form/survey/quiz tool with a Textual TUI, web serving, and response management.

______________________________________________________________________

## 1. Project Setup

### 1.1 Initialize Python Project with `uv`

- Run `uv init --package formtuitous` to scaffold a modern Python package.
- This creates `pyproject.toml`, `src/formtuitous/`, and the basic package
  structure.

### 1.2 Configure `pyproject.toml`

**Philosophy:** Quality gates (type checkers, linters, formatters) must be
integrated and active **before** any application code is written. The project
is configured from the first commit so that every module is created under
strict tooling.

Structure inspired by `gatorgrade`:

```toml
[project]
name = "formtuitous"
version = "0.1.0"
description = "Formtuitous — JSON-defined forms for terminal and web."
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
formtuitous = "formtuitous.cli:main"

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

- `project = "formtuitous"`
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
- `test-coverage` → `pytest -s --cov=formtuitous --cov-branch --cov-fail-under={coveragefailunder} --cov-report=term-missing tests/`
- `test-propertybased` → `pytest -x -s -vv -m propertybased`
- `test-not-propertybased` → `pytest -x -s -vv -m 'not propertybased'`
- `display` → `uv run formtuitous display`
- `serve` → `uv run formtuitous serve`
- `check-form` → `uv run formtuitous check`

**`[tool.ruff]`** — line-length 79, select `E`, `D`, `I`, `F`, `PL`, `Q`,
`RUF`, `W`, `T201`; ignore `D203`, `D213`, `E501`.

**`[tool.mypy]`** — `disallow_untyped_defs = true`, `warn_return_any = true`,
`warn_unused_configs = true`, `ignore_missing_imports = true`.

**`[tool.pyrefly]`** — `preset = "legacy"`, `ignore-missing-imports = ["*"]`.

**`[tool.coverage.run]`** — `source = ["formtuitous"]`, `branch = true`,
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

1. `uv init --package formtuitous`
1. Write `pyproject.toml` with all tool configs
1. Run `task lint` and `task typecheck` against the empty package to confirm
   the toolchain is wired correctly
1. Only then write `src/formtuitous/__init__.py`, `schema.py`, etc.

Every new module added to the project must satisfy the four type checkers
before the PR / commit is considered valid.

### 1.3 Directory Structure

```
formtuitous/
├── pyproject.toml
├── README.md
├── PLAN.md
├── BUILD.md
├── src/
│   └── formtuitous/
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
- For `short_text`/`paragraph`: `grading_type` selects exact, regex, or
  substring matching.

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

- `code` renders via Textual's `Markdown` widget with fenced code blocks.
- `image_path` is resolved relative to the form JSON file's directory.
- `url` renders as a clickable `Link` widget.

**Image rendering — `textual-image` evaluation:**
`textual-image` (https://github.com/lnqs/textual-image) provides Textual
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
    answers_json TEXT NOT NULL   -- JSON object mapping question_id -> answer
);
```

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
- `get_responses(conn, form_name: str | None) -> list[dict]`
- `get_response_count(conn, form_name: str) -> int`

### 3.4 `exporter.py` — Export Formats

- `export_to_jsonl(responses, output_path)`
- `export_to_csv(responses, output_path)`
- `export_to_sqlite(responses, output_path)` (for `datasette view`)

### 3.5 `grader.py` — Auto-Grading

- `grade_response(form_definition, answers) -> dict`
- Returns per-question score, total score, and feedback.
- Handle each `grading_type` (`exact`, `regex`, `contains`).
- Support partial credit for `checkbox` questions (e.g., proportion correct).

______________________________________________________________________

## 3.5 TUI Architecture Decision — Plain Textual Widgets

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
  required for Formtuitous v1.
- Media display (code blocks with syntax highlighting, image hints,
  clickable URLs) needs fine-grained layout control that `textual-wtf`'s
  `layout()` helpers cannot easily accommodate.
- One fewer third-party dependency reduces maintenance risk.

**The pipeline is therefore:**

```
JSON form → Pydantic validation → Custom widgets.py → FormScreen compose()
```

`Pydantic` remains the mandatory first validation gate. The TUI layer is
responsible only for rendering and data collection, never for schema
validation.

______________________________________________________________________

## 4. TUI Implementation (Textual)

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

### 4.3 TUI Layout Design

**Goal:** Simple, clear, single-column scrolling layout.

```
+--------------------------------------------------+
|  󰋼 Formtuitous — CS 101 Attendance          1/3   |
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

## 5. CLI Commands

### 5.1 `check <form.json>`

1. Parse and validate JSON against schema.
1. Report errors with line numbers if invalid.
1. Print summary: question count, required vs optional, grading enabled?

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

### 5.6 `grade <form.json> <responses.db> [--output <path>]`

1. Load form definition (with `correct_answer` fields).
1. Load all responses from DB.
1. Run `grader.grade_response()` on each.
1. Output a grade report (TUI table or CSV/JSON).

______________________________________________________________________

## 6. Web Serving Architecture

### 6.1 How `textual-serve` Fits

- `textual-serve` launches a **new subprocess per visitor** via WebSocket.
- This means 30 students hitting the URL = 30 independent `formtuitous display`
  processes.
- Each process has its own SQLite connection. SQLite handles concurrent reads
  well; writes may block briefly but are safe.

### 6.2 Wrapper Command

The `Server` command will be something like:

```python
from textual_serve.server import Server

cmd = f"formtuitous display {form_path} --db {db_path}"
server = Server(cmd, host=host, port=port, title=form_name)
server.serve()
```

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

- Run `formtuitous check` against all `examples/*.json`.
- Run `formtuitous display` in headless mode and verify DB write.

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
- Date field

______________________________________________________________________

## 9. Priorities for Proof-of-Concept

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
- Randomized question order

______________________________________________________________________

## 10. Known Similar Tools (Research Notes)

The following tools overlap with Formtuitous but do **not** match the exact
combination of JSON-defined + Textual TUI + web-serve + SQLite + datasette:

| Tool | Overlap | Difference |
|---|---|---|
| `tui-forms` | TUI forms from JSONSchema | No web serving, no SQLite, no grading |
| `textual-forms` | Dynamic forms in Textual | No JSON input, no web serving |
| `fstui` | Form generation from Pydantic | No JSON editor workflow, no web serving |
| SurveyJS | JSON-defined forms | Web-only (JS), no TUI |
| Formbricks | Open-source surveys | Web-only, heavy infrastructure |
| LimeSurvey | Mature survey platform | PHP/web, not TUI-first |

Formtuitous is unique in targeting the **terminal-first, JSON-edited, professor
workflow** with trivial web deployment via `textual-serve`.

______________________________________________________________________

## 11. Open Questions to Resolve During Build

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

*This build plan is a living document. Update it as decisions change during
implementation.*
