<div align="center">
  <img alt="Formtuist logo" src="https://raw.githubusercontent.com/formtuist/formtuist/main/.github/images/Formtuist-Logo.png" width="90%">
</div>

# Formtuist

Create, display, and serve JSON-defined forms, surveys, and quizzes --- all
from the terminal or a web browser!

## Overview

Formtuist is a tool for building the kinds of forms a teacher creates for
their classes: surveys, quizzes, and attendance sheets. You write a form as a
JSON file in your normal editor, then fill it out in the terminal or serve it
in a browser with textual-serve. It also is not a generic JSON Schema renderer.
Instead, Formtuist enforces a specific, Google-Forms-style structure, which
is what makes GitHub authentication and quiz grading possible. Responses land
in a SQLite database that you can inspect with `sqlite3` or `datasette`.

## Installation

```bash
uvx formtuist
```

Or, if you have cloned this repository, then with `uv` in a local project:

```bash
uv run formtuist check examples/minimal.json
```

## Usage

### `--version` — Show version information

```bash
uvx formtuist --version
```

Prints the formtuist version and the versions of the main dependencies
(pydantic, textual, rich, etc.), extracted dynamically. Exits cleanly.

### `check` — Validate a form JSON file

```bash
uvx formtuist check examples/survey.json
```

Parses and validates the form definition, then prints a summary:

- Form name and description
- Question count (required vs optional)
- Graded questions and auto-grade status

Validation also rejects common authoring traps, such as auto-grading
enabled with no graded questions, regex grading with a missing or
broken pattern, an `accepts` pattern set without regex grading, and
correct answers that are not among a question's choices. The
`examples/invalid_*.json` files demonstrate each trap.

Exits with code `0` if valid, `1` if errors are found.

### `schema` — Show the enforced JSON schema

```bash
uvx formtuist schema
```

Prints the JSON schema that formtuist enforces, with syntax highlighting.
The schema is generated directly from the Pydantic models, so it always
reflects exactly what `check` validates against. This is useful when a form
file does not validate — compare it against the schema to find the mismatch.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--theme` | Pygments theme for syntax highlighting | `ansi_dark` |
| `--output` / `-o` | Save the schema to a JSON file instead of printing | — |

**Examples:**

```bash
# Print the schema with a light theme
uvx formtuist schema --theme ansi_light

# Save the schema for use in editors or CI
uvx formtuist schema --output schema.json
```

### `display` — Fill out a form in the TUI

```bash
uvx formtuist display examples/minimal.json
```

Opens a Textual terminal UI where you can fill out and submit the form.
Responses are saved to a SQLite database.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--db-dir` | Directory for the responses database | `~/.local/share/formtuist/` |
| `--database-name` | Name of the database file | `responses.db` |

**Examples:**

```bash
# Local TUI, custom database directory
uvx formtuist display examples/quiz.json --db-dir ~/survey-data

# Separate databases per form (same directory)
uvx formtuist display examples/attendance.json --database-name attendance.db
uvx formtuist display examples/quiz.json --database-name quiz.db
```

### `serve` — Serve a form as a web app

```bash
uvx formtuist serve examples/survey.json
```

Serves the form as a web application via textual-serve. Each visitor gets
their own TUI instance in the browser.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--host` | Host address for the web server | `0.0.0.0` |
| `--port` | Port for the web server | `8000` |
| `--db-dir` | Directory for the responses database | `~/.local/share/formtuist/` |
| `--database-name` | Name of the database file | `responses.db` |

**Examples:**

```bash
# Serve on the default address and port
uvx formtuist serve examples/survey.json

# Serve on a specific address and port (e.g., via NetBird)
uvx formtuist serve examples/quiz.json --host 100.xx.xx.xx --port 9000

# Save responses to a dedicated database
uvx formtuist serve examples/attendance.json --database-name attendance.db
```

### `publish` — Publish a form through a bitbang URL

```bash
uvx formtuist publish examples/survey.json
```

Starts the local textual-serve application and publishes it through the
peer-to-peer [bitbang](https://github.com/joeychua/bitbang) WebRTC tunnel.
The command prints a URL and QR code that can be opened from another browser
without port forwarding or a public server. The local textual-serve process
continues running until the bitbang session is stopped.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--host` | Local host address for textual-serve | `127.0.0.1` |
| `--port` | Local port for textual-serve | `8000` |
| `--signaling` | Bitbang signaling server | `bitba.ng` |
| `--pin` | Optional access PIN | — |
| `--ephemeral` | Use a new temporary bitbang identity | off |
| `--db-dir` | Directory for the responses database | platform default |
| `--database-name` | Name of the responses database | `responses.db` |

For example, publish a quiz with a temporary identity and PIN:

```bash
uvx formtuist publish examples/quiz.json --ephemeral --pin 1234
```

### `view` — Browse responses in a web browser

```bash
uvx formtuist view ~/.local/share/formtuist/responses.db
```

Launches [datasette](https://datasette.io/) to let you browse, filter, and
query responses in your browser.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--port` | Port for the datasette web server | `8001` |

**Example:**

```bash
uvx formtuist view ~/.local/share/formtuist/responses.db --port 9000
```

### `export` — Export responses

```bash
uvx formtuist export ~/.local/share/formtuist/responses.db \
  --format csv --output responses.csv
```

Exports every response in the database (or just one form's responses with
`--form-name`) to a flat file. The default `csv` format is handy for a
spreadsheet, `json` writes a single JSON array, `jsonl` writes one JSON
object per line, and `sqlite` writes a flat `responses_flat` table that
`view`/datasette can browse directly.

Every format shares the same flat row shape: the response id, form name,
submitted timestamp, GitHub identity, and the stored grade totals (`total`,
`max`, `percentage`), followed by one column per question id. Missing
answers and grades are empty cells in CSV, `null` in JSON, and NULL in
SQLite. List answers (checkboxes) are JSON-encoded in CSV and SQLite cells
and stay native arrays in JSON.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--output` / `-o` | Output file path (required) | — |
| `--format` | `csv`, `json`, `jsonl`, or `sqlite` | `csv` |
| `--form-name` | Only export responses for this form | all forms |

**Examples:**

```bash
# CSV for a spreadsheet (the default format)
uvx formtuist export responses.db --output responses.csv

# A JSON array for other tools
uvx formtuist export responses.db --format json --output responses.json

# JSON-lines for streaming or line-oriented tools
uvx formtuist export responses.db --format jsonl --output responses.jsonl

# A flat SQLite table that datasette can browse
uvx formtuist export responses.db --format sqlite --output flat.db
uvx formtuist view flat.db

# Only the responses for one form in a shared database
uvx formtuist export responses.db --format csv --form-name "CS 101 Quiz" \
  --output cs101.csv
```

The grade columns come from the snapshot stored at submit time, so exports
never change retroactively when the form file is edited.

### `grade` — Report grades for a quiz

```bash
uvx formtuist grade examples/quiz.json responses.db
```

Prints a per-question score table with one row per response. When a response
was submitted to an auto-graded form, the score snapshot recorded at submit
time is reported as-is, so grades never change retroactively when the form
file is edited. Responses without a stored snapshot (older databases,
non-auto-graded forms) are graded on the fly.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--recompute` | Re-grade every response with the current form and update the stored snapshots | `false` |

**Example:**

```bash
uvx formtuist grade examples/quiz.json responses.db --recompute
```

## Keyboard shortcuts

Inside the form TUI:

| Key | Action |
|---|---|
| `Ctrl+S` | Submit the form |
| `Ctrl+J` | Focus the next question |
| `Ctrl+K` | Focus the previous question |
| `Ctrl+F` | Focus the first input (or the auth token field) |
| `Ctrl+B` | Toggle the sidebar |
| `Ctrl+C` | Quit |
| `Ctrl+P` | Open the command palette |

The left sidebar shows an abbreviated list of the questions and highlights
the one you are currently answering. A counter at the bottom shows
`Question X / Y`.

## Authentication

Forms can require the person filling them out to prove their identity with a
GitHub token (e.g., the output of `gh auth token`). Set this in the form
config:

```json
{
  "name": "Authenticated Form",
  "config": {
    "auth": "github"
  },
  "questions": [
    {
      "id": "feedback",
      "text": "What do you think?",
      "type": "paragraph",
      "required": true
    }
  ]
}
```

When `auth` is set to `github`:

1. The TUI shows a masked GitHub token field at the top of the form.
1. On submit, formtuist calls the GitHub REST API
   (`GET https://api.github.com/user`) with the token as a Bearer header.
1. The token is validated — if it is invalid, submission is **blocked**.
1. On success, the person's GitHub username and profile URL are stored on
   the response row. The raw token itself is **never** persisted.

Authentication is disabled by default (`auth` is `null`), which means the
form is anonymous by definition. When `auth` is `"github"`, the response row
always records the identity of the person who submitted.

A single-submission form (`allow_multiple_submissions: false`) requires an
`auth` provider. Without an identity, formtuist cannot tell one person's
second submission from two people's firsts, so the definition is rejected at
parse time. Anonymous forms should keep `allow_multiple_submissions` at its
default of `true`.

Single-submission enforcement is scoped per attempt: each run of a form
receives its own `attempt_id`, stored on every response row, and the
tools check for duplicates within that attempt only. The `serve` command
hands one shared `attempt_id` to every browser session of a run, while a
direct `display` run uses a per-run id. This means the same database can be
reused for many runs of the same form without blocking returning students;
someone who already submitted in a prior run may submit again in a new one.

## Form JSON format

Forms are defined as JSON files. Here is a minimal example:

```json
{
  "name": "My Form",
  "description": "An example form.",
  "config": {
    "randomize_questions": false,
    "auto_grade": false,
    "allow_multiple_submissions": true,
    "auth": null
  },
  "questions": [
    {
      "id": "name",
      "text": "What is your full name?",
      "type": "short_text",
      "required": true
    }
  ]
}
```

### Config options

| Field | Type | Default | Description |
|---|---|---|---|
| `randomize_questions` | boolean | `false` | Show questions in random order |
| `auto_grade` | boolean | `false` | Grade submissions automatically |
| `allow_multiple_submissions` | boolean | `true` | Allow repeats; when `false`, `auth` must be set so duplicates can be blocked |
| `auth` | `"github"` or `null` | `null` | Require a GitHub token to submit; `null` means anonymous |

### Question types

| Type | Widget | Storage |
|---|---|---|
| `short_text` | Single-line `Input` | TEXT |
| `paragraph` | Multi-line `TextArea` | TEXT |
| `multiple_choice` | `RadioSet` | TEXT |
| `checkbox` | `SelectionList` | JSON list |
| `numeric` | `Input` with integer validator | REAL |
| `rating` | `RadioSet` (horizontal) | INTEGER |
| `date` | `DatePicker` with a visual calendar | TEXT |
| `yes_no` | `Switch` | INTEGER (0/1) |

`numeric` inputs are validated on submit — invalid values block
submission with an error message. `date` answers are chosen from a
visual calendar picker, so a malformed date cannot be typed. In an
auto-graded form, a `yes_no` question
can carry a boolean `correct_answer` (`true` or `false`) and a `points` value,
so true/false quiz questions are scored automatically. Questions may also
include optional `code` blocks (rendered with syntax highlighting), `url`
links, and `image_path` references.

Code blocks may be written inline (`content`) or reference a file that
holds the source code (`file`) — handy for multi-line snippets, which
keep their real formatting and need no escape characters. Relative file
paths resolve against the form file's directory, or against `--code-dir`
when that option is given. Text answers may also accept several code
segments: `correct_answer` may be a string, one code block, or a list of
code blocks; an optional `accepts` regex provides tolerant grading
without ever being shown to students.

When `randomize_questions` is enabled, every question is shuffled by
default. Set `"randomize": false` on a question to keep it at its file
position while the other questions shuffle around it — useful for a
closing question such as a confidence rating.

See `examples/` for complete form definitions.

## Database

Responses are stored in a SQLite database with a single `responses` table:

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-incrementing primary key |
| `form_name` | TEXT | Name of the submitted form |
| `submitted_at` | TEXT | ISO 8601 timestamp |
| `answers_json` | TEXT | JSON object of question IDs to answers |
| `github_username` | TEXT | GitHub username (when auth is enabled) |
| `github_url` | TEXT | GitHub profile URL (when auth is enabled) |

The database is created in the platform-appropriate data directory
(`~/.local/share/formtuist/` on Linux). Use `--db-dir` to override.
Existing databases are migrated automatically when new columns are added.

Browse saved responses with:

```bash
uvx formtuist view ~/.local/share/formtuist/responses.db
```

Or peek with `sqlite3`:

```bash
sqlite3 -header -column ~/.local/share/formtuist/responses.db \
  "SELECT id, form_name, github_username, submitted_at FROM responses;"
```

## Example forms

The `examples/` directory contains several ready-to-use forms:

| File | Description |
|---|---|
| `minimal.json` | Single-question smoke test |
| `minimal_auth.json` | Single-question form with GitHub auth enabled |
| `authenticated.json` | Comprehensive form with GitHub auth and all question types |
| `attendance.json` | Daily attendance check-in |
| `survey.json` | Feedback survey with various types |
| `quiz.json` | Auto-graded quiz |
| `method_invocation_quiz.json` | Auto-graded quiz about Python method resolution |
| `yes_no_quiz.json` | Auto-graded true/false quiz (all yes_no questions) |
| `all_types.json` | One question of every type |
| `anonymous_poll.json` | Anonymous response poll |

## Comparison with similar tools

Formtuist is not the only tool that renders forms in the terminal. Here is
how it compares to related projects.

### `tui-forms` — generic JSON Schema forms

[tui-forms](https://github.com/collective/tui-forms) takes a JSON Schema
description of *any* form and renders it as a TUI. It is a general-purpose
renderer: describe the fields, get a form.

Formtuist is deliberately different: instead of accepting arbitrary JSON
Schema, it enforces a **specific, curated schema** designed for surveys,
quizzes, and attendance — the kinds of forms you would build with Google
Forms. That fixed schema is what makes the higher-level features possible:

- **Authentication** — require a GitHub token to verify who submitted
- **Structured storage** — responses saved to a SQLite database with
  identity columns
- **Auto-grading** — quizzes with correct answers and partial credit
- **Web serving** — `textual-serve` gives every visitor their own TUI in a
  browser
- **Response browsing** — launch datasette to explore submissions

In short: `tui-forms` renders *any* schema; Formtuist gives *one* schema
and all the features a form system needs.

### Other related tools

| Tool | Overlap | Difference from Formtuist |
|---|---|---|
| [textual-forms](https://github.com/rhymiz/textual-forms) | Dynamic forms in Textual | No JSON input, no web serving, no storage |
| [textual-wtf](https://github.com/holdenweb/textual-wtf) | Declarative forms for Textual | Python-class forms, no JSON schema, no web serving |
| [fstui](https://github.com/HYChou0515/fstui) | Forms generated from Pydantic | No JSON editor workflow, no web serving |
| [richforms](https://pypi.org/project/richforms/) | Pydantic models into Rich terminal forms | No JSON schema, no web serving, no storage |
| [pydantic-studio](https://github.com/invoker-bot/pydantic-studio) | Interactive Pydantic editors | Config-focused, no survey features |
| [SurveyJS](https://surveyjs.io/) | JSON-defined forms | Web-only (JavaScript), no TUI |
| [Formbricks](https://formbricks.com/) | Open-source surveys | Web-only, heavier infrastructure |
| [LimeSurvey](https://www.limesurvey.org/) | Mature survey platform | PHP/web, not terminal-first |

What distinguishes Formtuist is that it treats the form as a project
artifact. The form definition lives in a JSON file in your repository, the
responses live in a SQLite database on your machine, and the identity of the
person who submitted is verified with a GitHub token. None of the tools
above combine all of these pieces.

## License

MIT
