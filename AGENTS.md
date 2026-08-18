# AGENTS.md

This document provides guidelines for AI agents contributing to the
**Formtuist** repository.

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
- **Be transparent about mistakes:** Although you should
  avoid making mistakes, when an action overwrites, deletes,
  or damages user data (for example, replacing a database file
  during testing), report it immediately and explicitly: name
  the file, what happened, why, and what is recoverable. Never
  hide damage or wait for the human to discover it.
  Acknowledge the error and offer remediation.
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

- **Cross-platform code:** Source code must run unchanged on macOS,
  Linux, and Windows. Write filesystem logic with `pathlib` and never
  embed path separators in strings; a leading-slash path without a
  drive letter is not absolute on Windows. Normalize any path that
  appears in a stable identifier or output with `Path.as_posix()` so
  results are identical on every platform.
- **Function bodies:** No blank lines within function bodies. Keep code
  contiguous from the function signature to the final `return`.
- **Docstrings:** Single-line docstrings starting with a capital letter and
  ending with a period. Follow this for new files. In existing files, preserve
  the established docstring style.
- **Comments:** Start with a lowercase letter. Preserve existing comments
  during refactoring. The only exception is when the first word is a proper
  noun (e.g., `Formtuist`, `GitHub`) or an identifier that must be
  capitalized (e.g., `GITHUB_ENV`).
- **Sentences in comments:** Use exactly one space between the period and the
  following sentence.
- **No backticks in comments:** Do not use backticks in comments, docstrings,
  or any prose inside source files. Backticks are reserved for Markdown
  formatting in `.md` files only. Refer to identifiers plainly
  (e.g., "transformers" not "`transformers`").
- **Imports:** Group in this order: standard library, third-party, local.
  Use absolute imports (`from formtuist.module import <name>`). Place all
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

- Source code lives in `src/formtuist/`.
- Tests live in `tests/` with structure mirroring the source modules.
- Use `uv` for dependency management, virtual environments, and task running.
- Supports Python `>=3.12, <4.0` on macOS, Linux, and Windows.
- Uses Pydantic models for data validation and JSON serialization.

## Testing Requirements

All tests must follow these standards:

- **Cross-platform tests:** Tests must pass unchanged on macOS, Linux,
  and Windows. Never assert hardcoded POSIX-style paths; derive the
  expected string from the same `Path` object under test (for example,
  `str(db_path)` instead of a `/custom/...` literal) and remember that
  leading-slash paths without a drive letter are not absolute on
  Windows. Use platform-neutral fixtures such as `tmp_path`.
- Tests are Python functions and therefore follow all code requirements above.
- Test names start with `test_` and are descriptive.
- Group tests by the function or module they exercise.
- Order tests logically for readability.
- Tests must be independent — runnable in random order without side effects.
- Tests must pass on local machines and in CI on macOS, Linux, and Windows.
- Aim for full function, statement, and branch coverage (minimum 95%).
- Property-based tests using `hypothesis` must be marked with
  `@pytest.mark.propertybased`.
- Tests must not produce console output.

## Web Interface Testing Workflow

When the `textual-serve` web interface has a layout or rendering bug (for
example, content cut off at the bottom of the page), verify the fix in a
real browser before reporting completion. Unit tests cannot catch
browser-only problems because the web page is generated from the HTML
template at `src/formtuist/templates/app_index.html` and then laid out
by browser CSS engines. Run all commands in this section from the
repository root.

### Start the server

Run the server in the background on a fixed port and confirm it is up:

```bash
nohup uv run formtuist serve examples/attendance.json --port 8020 \
  > /tmp/formtuist-serve.log 2>&1 &
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8020/
```

Use `pkill -f "formtuist serve"` before restarting the server after a
fix.

### Inspect the served HTML

The page is rendered from a Jinja template. The `serve` command passes
`templates_path` pointing at `src/formtuist/templates/`, so the served
HTML comes from `app_index.html` in that directory. Compare it against
the upstream textual-serve template at
`.venv/lib/python3.14/site-packages/textual_serve/templates/app_index.html`
and fetch the served page with `curl -s http://127.0.0.1:8020/`.

### Verify the DOM structure with an HTML5 parser

Python's built-in `html.parser` does not model browser parsing rules, so
use `html5lib` to see how a browser would really structure the document.
Run it with `uv run --with` so it is never added to project dependencies:

```bash
uv run --with html5lib python -c "
import html5lib

raw = open('src/formtuist/templates/app_index.html', encoding='utf-8').read()
doc = html5lib.parse(raw)


def walk(node, depth=0):
    print('  ' * depth + str(node.tag).split('}')[-1])
    for child in node:
        walk(child, depth + 1)


walk(doc)
"
```

A healthy page keeps every `link`, `script`, and `style` element inside
`head` and only `div` elements inside `body`. Known trap: stray non-head
elements in the template head (for example, leftover `<rect>` SVG
fragments) make browsers close the head early, move the styles and
scripts into the body, and render any leftover text as a line that pushes
the `100vh`-tall terminal below the viewport fold. That is how the
keyboard-shortcut footer ended up cut off.

### Measure the page layout in a real browser

Use Playwright through `uv run --with` with the system Chromium. The
Playwright-downloaded browser in `~/.cache/ms-playwright` can fail on this
machine with `error while loading shared libraries: libglib-2.0.so.0`, so
resolve the system browser first:

```bash
readlink -f /etc/profiles/per-user/gkapfham/bin/chromium
```

Then write a measurement script such as:

```python
import asyncio
import json

from playwright.async_api import async_playwright

# path from the readlink command above
EXE = "/nix/store/.../bin/chromium"


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=EXE)
        page = await browser.new_page(viewport={"width": 1200, "height": 800})
        await page.goto("http://127.0.0.1:8020/")
        await page.wait_for_timeout(4000)
        metrics = await page.evaluate("""() => {
            const term = document.getElementById('terminal');
            const r = term.getBoundingClientRect();
            return {
                viewportH: window.innerHeight,
                docH: document.documentElement.scrollHeight,
                termTop: r.top,
                termBottom: r.bottom,
                bodyChildren: [...document.body.children].map(e => e.tagName),
            };
        }""")
        print(json.dumps(metrics, indent=2))
        await page.screenshot(path="/tmp/formtuist_page.png")
        await browser.close()


asyncio.run(main())
```

Run it with `uv run --with playwright python /tmp/measure_footer.py`.

A healthy page reports `docH == viewportH`, `termTop == 0`, and
`termBottom == viewportH`. A page with a cut-off footer reports
`termBottom > viewportH` and `docH > viewportH`, because the bottom row
sits below the fold. Rely on these numbers: the agent model may not be
able to view the screenshot, so still save one for the human reviewer.

### Re-verify after a fix

Edit the template, then restart the server and re-run the measurement
after using `pkill -f "formtuist serve"`. Jinja2 auto-reloads
templates, so a restart is not strictly required, but it is harmless.
The human tester must hard-refresh the browser (Ctrl+Shift+R) because
the browser caches the page. Also confirm the favicon still serves:

```bash
curl -s -o /dev/null -w "%{http_code} %{content_type} %{size_download}B\n" \
  http://127.0.0.1:8020/favicon.png
```

Finish by running `uv run task all`. A browser check complements the
test suite; it never replaces it.

## Making Changes

1. **Understand:** Thoroughly understand the request and the relevant
   codebase. Use available tools to explore files.
1. **Plan:** Formulate a clear plan before making changes. Consult `BUILD.md`
   for architecture decisions.
1. **Implement:** Make small, incremental changes.
1. **Verify:** Run `uv run task all` to ensure correctness and style
   compliance.
1. **Commit:** The human developer commits the changes.
1. **Rules:** Follow all rules in this file and in `BUILD.md`.
1. **Report, don't close the TODO:** When finished, summarize completed
   tasks, how you completed them, challenges faced, how you overcame them,
   and the rules you followed. Leave the TODO open — only the user closes it.
1. **Wait for confirmation:** After reporting completion, wait for the user to
   confirm before starting the next TODO.
