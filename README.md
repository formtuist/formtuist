# Formtuitous

Create, display, and serve JSON-defined forms, surveys, and quizzes — all from
the terminal or a web browser.

## Installation

```bash
uvx formtuitous
```

Or, if you have cloned this repository, then with `uv` in a local project:

```bash
uv run formtuitous check examples/minimal.json
```

## Usage

### `check` — Validate a form JSON file

```bash
uvx formtuitous check examples/survey.json
```

Parses and validates the form definition, then prints a summary:

- Form name and description
- Question count (required vs optional)
- Graded questions and auto-grade status

Exits with code `0` if valid, `1` if errors are found.

### `display` — Fill out a form in the TUI

```bash
uvx formtuitous display examples/minimal.json
```

Opens a Textual terminal UI where you can fill out and submit the form.
Responses are saved to a SQLite database.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--db-dir` | Directory for the responses database | `~/.local/share/formtuitous/` |
| `--serve` | Serve the form as a web app instead of using the local TUI | off |
| `--host` | Host address for the web server | `0.0.0.0` |
| `--port` | Port for the web server | `8000` |

**Examples:**

```bash
# Local TUI, custom database directory
uvx formtuitous display examples/quiz.json --db-dir ~/survey-data

# Serve as a web app (each visitor gets their own TUI via textual-serve)
uvx formtuitous display examples/survey.json --serve

# Serve on a specific address and port (e.g., via NetBird)
uvx formtuitous display examples/quiz.json --serve --host 100.xx.xx.xx --port 9000
```

**Keyboard shortcuts inside the TUI:**

| Key | Action |
|---|---|
| `Ctrl+S` | Submit the form |
| `Ctrl+J` | Focus the next question |
| `Ctrl+K` | Focus the previous question |
| `Ctrl+F` | Focus the first input |
| `Ctrl+B` | Toggle the sidebar |
| `Ctrl+C` | Quit |

### `view` — Browse responses in a web browser

```bash
uvx formtuitous view ~/.local/share/formtuitous/responses.db
```

Launches [datasette](https://datasette.io/) to let you browse, filter, and
query responses in your browser.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--port` | Port for the datasette web server | `8001` |

**Example:**

```bash
uvx formtuitous view ~/.local/share/formtuitous/responses.db --port 9000
```

### `export` — Export responses (coming soon)

```bash
uvx formtuitous export responses.db
```

### `grade` — Grade responses (coming soon)

```bash
uvx formtuitous grade examples/quiz.json responses.db
```

### `serve` — Legacy serve alias

```bash
uvx formtuitous serve examples/minimal.json
```

Prefer `uvx formtuitous display --serve` instead.

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
    "show_progress_bar": true
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

### Question types

| Type | Widget | Storage |
|---|---|---|
| `short_text` | Single-line `Input` | TEXT |
| `paragraph` | Multi-line `TextArea` | TEXT |
| `multiple_choice` | `RadioSet` | TEXT |
| `checkbox` | `SelectionList` | JSON list |
| `numeric` | `Input` with integer validator | REAL |
| `rating` | `RadioSet` (horizontal) | INTEGER |
| `date` | `Input` with ISO 8601 | TEXT |
| `yes_no` | `Switch` | INTEGER (0/1) |

See `examples/` for complete form definitions.

## Database

Responses are stored in a SQLite database with a single `responses` table:

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER | Auto-incrementing primary key |
| `form_name` | TEXT | Name of the submitted form |
| `submitted_at` | TEXT | ISO 8601 timestamp |
| `answers_json` | TEXT | JSON object of question IDs to answers |

The database is created in the platform-appropriate data directory
(`~/.local/share/formtuitous/` on Linux). Use `--db-dir` to override.

Browse saved responses with:

```bash
uvx formtuitous view ~/.local/share/formtuitous/responses.db
```

Or peek with `sqlite3`:

```bash
sqlite3 -header -column ~/.local/share/formtuitous/responses.db \
  "SELECT id, form_name, submitted_at FROM responses;"
```

## Example forms

The `examples/` directory contains several ready-to-use forms:

| File | Description |
|---|---|
| `minimal.json` | Single-question smoke test |
| `attendance.json` | Daily attendance check-in |
| `survey.json` | Feedback survey with various types |
| `quiz.json` | Auto-graded quiz |
| `all_types.json` | One question of every type |
| `anonymous_poll.json` | Anonymous response poll |

## License

MIT
