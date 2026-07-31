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

### `--version` — Show version information

```bash
uvx formtuitous --version
```

Prints the formtuitous version and the versions of the main dependencies
(pydantic, textual, rich, etc.), extracted dynamically. Exits cleanly.

### `check` — Validate a form JSON file

```bash
uvx formtuitous check examples/survey.json
```

Parses and validates the form definition, then prints a summary:

- Form name and description
- Question count (required vs optional)
- Graded questions and auto-grade status

Exits with code `0` if valid, `1` if errors are found.

### `schema` — Show the enforced JSON schema

```bash
uvx formtuitous schema
```

Prints the JSON schema that formtuitous enforces, with syntax highlighting.
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
uvx formtuitous schema --theme ansi_light

# Save the schema for use in editors or CI
uvx formtuitous schema --output schema.json
```

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
| `--database-name` | Name of the database file | `responses.db` |

**Examples:**

```bash
# Local TUI, custom database directory
uvx formtuitous display examples/quiz.json --db-dir ~/survey-data

# Separate databases per form (same directory)
uvx formtuitous display examples/attendance.json --database-name attendance.db
uvx formtuitous display examples/quiz.json --database-name quiz.db
```

### `serve` — Serve a form as a web app

```bash
uvx formtuitous serve examples/survey.json
```

Serves the form as a web application via textual-serve. Each visitor gets
their own TUI instance in the browser.

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--host` | Host address for the web server | `0.0.0.0` |
| `--port` | Port for the web server | `8000` |
| `--db-dir` | Directory for the responses database | `~/.local/share/formtuitous/` |
| `--database-name` | Name of the database file | `responses.db` |

**Examples:**

```bash
# Serve on the default address and port
uvx formtuitous serve examples/survey.json

# Serve on a specific address and port (e.g., via NetBird)
uvx formtuitous serve examples/quiz.json --host 100.xx.xx.xx --port 9000

# Save responses to a dedicated database
uvx formtuitous serve examples/attendance.json --database-name attendance.db
```

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
2. On submit, formtuitous calls the GitHub REST API
   (`GET https://api.github.com/user`) with the token as a Bearer header.
3. The token is validated — if it is invalid, submission is **blocked**.
4. On success, the person's GitHub username and profile URL are stored on
   the response row. The raw token itself is **never** persisted.

Authentication is disabled by default (`auth` is `null`). It can be combined
with the `anonymous` config flag, though note that `anonymous` only controls
whether identifying questions are shown — authenticated rows always record
the GitHub identity.

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
    "show_progress_bar": true,
    "anonymous": false,
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
| `allow_multiple_submissions` | boolean | `true` | Allow the same person to submit more than once |
| `show_progress_bar` | boolean | `true` | Show the question progress counter |
| `anonymous` | boolean | `false` | Skip identifying questions |
| `auth` | `"github"` or `null` | `null` | Require a GitHub token to submit |

### Question types

| Type | Widget | Storage |
|---|---|---|
| `short_text` | Single-line `Input` | TEXT |
| `paragraph` | Multi-line `TextArea` | TEXT |
| `multiple_choice` | `RadioSet` | TEXT |
| `checkbox` | `SelectionList` | JSON list |
| `numeric` | `Input` with integer validator | REAL |
| `rating` | `RadioSet` (horizontal) | INTEGER |
| `date` | `Input` with ISO 8601 validation | TEXT |
| `yes_no` | `Switch` | INTEGER (0/1) |

`numeric` and `date` inputs are validated on submit — invalid values block
submission with an error message. Questions may also include optional
`code` blocks (rendered with syntax highlighting), `url` links, and
`image_path` references.

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
(`~/.local/share/formtuitous/` on Linux). Use `--db-dir` to override.
Existing databases are migrated automatically when new columns are added.

Browse saved responses with:

```bash
uvx formtuitous view ~/.local/share/formtuitous/responses.db
```

Or peek with `sqlite3`:

```bash
sqlite3 -header -column ~/.local/share/formtuitous/responses.db \
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
| `all_types.json` | One question of every type |
| `anonymous_poll.json` | Anonymous response poll |

## License

MIT
