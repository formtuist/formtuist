# AGENTS.md

This document provides guidelines for AI agents contributing to the
**Formtuitous** repository.

## Overview of Instructions

- **Always use `uv`:** This project uses `uv` for all dependency management,
  virtual environments, and task running. Do not use `pip`, `venv`, or
  `poetry` directly. Commands like `uv sync`, `uv run`, and `uv add` are the
  only correct workflow.
- **Follow all guidelines:** This document contains the complete set of
  guidelines for this project. You must follow them strictly. For build
  architecture and implementation details, consult `BUILD.md` and `PLAN.md` at
  the repository root.
- **Verify your changes:** Before declaring any task complete, you must run all
  linters and tests to ensure correctness and style compliance. The canonical
  verification command is `uv run task all`.
- **Line width:** Python source code must respect **79 characters** (enforced
  by `ruff`). Markdown and other prose files should wrap at **80 characters**.
- **Permission to run commands:** You have permission to run all commands in
  this file to verify their functionality.
- **Incremental changes:** Make small, incremental changes. This makes review
  easier and catches errors early.
- **Communicate clearly:** When you propose changes, explain what you have
  done and why.
- **Create and follow a TODO list:** Always create a TODO list and then follow
  it. Do not stop until the tools you call confirm that all tasks in the list
  are completed.
- **Do not close the TODO:** Only the user closes the TODO. The agent must
  never mark a TODO as closed or call update_goal with status complete. The
  agent reports completion and waits for the user to confirm and close.

## Notification Instructions

- The user has given permission to use `notify-send` to signal task completion
  or request feedback. Example:

  ```bash
  notify-send "Question from Coding Agent" \
    "Please clarify how to complete the testing task."
  ```

- Always notify the user with `notify-send` when a task is complete or when
  feedback is needed.

- When working inside a Zellij session, use the `zjstatus::notify` pipe
  protocol. The full two-step pattern is:

  ```bash
  # Step 1: Send the notification (displays for show_interval seconds)
  timeout 2 zellij pipe -- \
    "zjstatus::notify::󰵰 Task complete. " 2>/dev/null

  # Step 2: After the interval expires, force a re-render to clear it
  timeout 8 bash -c \
    "sleep 6 && zellij pipe -- 'zjstatus::pipe::clear:: '" 2>/dev/null || true
  ```

  The `sleep` duration must be at least `show_interval + 1` seconds.
  The trailing space in the notify message is required.

## Build, Lint, and Test Commands

These commands are defined via **taskipy** in `pyproject.toml` and executed
through `uv run task <name>`:

- **Run all verification:** `uv run task all`
- **Run all linters:** `uv run task lint`
- **Format check:** `uv run task ruff-format`
- **Format fix:** `uv run task format-fix`
- **Lint check:** `uv run task ruff-check`
- **Type check (all):** `uv run task typecheck`
- **Individual type checkers:** `uv run task mypy`, `uv run task ty`,
  `uv run task pyrefly`, `uv run task zuban`
- **Test suite:** `uv run task test`
- **Test with coverage:** `uv run task test-coverage`
- **Test variants:** `uv run task test-silent`,
  `uv run task test-not-propertybased`, `uv run task test-propertybased`
- **Markdown lint:** `uv run task rumdl-check`
- **Markdown fix:** `uv run task rumdl-fix`
- **Run a single test:**
  `uv run pytest tests/test_file.py::test_function -x -s -vv`

## Code Requirements

All Python code must follow these standards:

- **Function bodies:** No blank lines within function bodies. Keep code
  contiguous from the function signature to the final `return`.
- **Docstrings:** Single-line docstrings starting with a capital letter and
  ending with a period. Follow this for new files. In existing files, preserve
  the established docstring style.
- **Comments:** Start with a lowercase letter. Preserve existing comments
  during refactoring. The only exception is when the first word is a proper
  noun (e.g., `Formtuitous`, `GitHub`) or an identifier that must be
  capitalized (e.g., `GITHUB_ENV`).
- **Sentences in comments:** Use exactly one space between the period and the
  following sentence.
- **No backticks in comments:** Do not use backticks in comments, docstrings,
  or any prose inside source files. Backticks are reserved for Markdown
  formatting in `.md` files only. Refer to identifiers plainly
  (e.g., "transformers" not "`transformers`").
- **Imports:** Group in this order: standard library, third-party, local.
  Use absolute imports (`from formtuitous.module import <name>`). Place all
  imports at the top of the file. Never place imports inside functions or
  classes.
- **Formatting:** `ruff format` enforces line length 79. Use trailing commas.
  Run via `uv run task format-fix`.
- **Types:** All functions must have type hints for parameters and return
  values.
- **Naming:** `snake_case` for functions and variables, `PascalCase` for
  classes, `UPPER_SNAKE_CASE` for constants.
- **Constants over literals:** All hard-coded strings, integers, and floats
  must be extracted into named constants at the top of the module. Use the
  constant everywhere, never the raw literal.
- **File operations:** Use `pathlib.Path` for all filesystem operations. Never
  use string paths.
- **Error handling:** Raise specific exception types, not generic `Exception`.
  Provide meaningful error messages.

## Project Structure Requirements

- Source code lives in `src/formtuitous/`.
- Tests live in `tests/` with structure mirroring the source modules.
- Use `uv` for dependency management, virtual environments, and task running.
- Supports Python `>=3.10, <4.0` on macOS, Linux, and Windows.
- Uses Pydantic models for data validation and JSON serialization.

## Testing Requirements

All tests must follow these standards:

- Tests are Python functions and therefore follow all code requirements above.
- Test names start with `test_` and are descriptive.
- Group tests by the function or module they exercise.
- Order tests logically for readability.
- Tests must be independent — runnable in random order without side effects.
- Tests must pass on local machines and in CI.
- Aim for full function, statement, and branch coverage (minimum 95%).
- Property-based tests using `hypothesis` must be marked with
  `@pytest.mark.propertybased`.
- Tests must not produce console output.

## Making Changes

1. **Understand:** Thoroughly understand the request and the relevant
   codebase. Use available tools to explore files.
2. **Plan:** Formulate a clear plan before making changes. Consult `BUILD.md`
   for architecture decisions.
3. **Implement:** Make small, incremental changes.
4. **Verify:** Run `uv run task all` to ensure correctness and style
   compliance.
5. **Commit:** The human developer commits the changes.
6. **Rules:** Follow all rules in this file and in `BUILD.md`.
7. **Report, don't close the TODO:** When finished, summarize completed
   tasks, how you completed them, challenges faced, how you overcame them,
   and the rules you followed. Leave the TODO open — only the user closes it.
8. **Wait for confirmation:** After reporting completion, wait for the user to
   confirm before starting the next TODO.
