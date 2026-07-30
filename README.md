# Formtuitous

Formtuitous is a JSON-defined form, survey, and quiz tool with a Textual TUI,
web serving, and response management.

## Overview

Define your forms as JSON files, then use the terminal UI or a web browser to
fill them out. Export responses to CSV, JSON, or SQLite.

## Quick Start

```bash
uv run formtuitous check examples/survey.json
uv run formtuitous display examples/survey.json
uv run formtuitous serve examples/survey.json
```

## License

MIT
