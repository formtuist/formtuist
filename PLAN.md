# Plan for Implementing Formtuitous

This is a plan for building Formtuitous, a tool
that lets you:

1. Specify a form (e.g., a survey or a quiz) in JSON format.

1. Automatically generate a TUI representation

There are the technologies employed in Formtuitous:

- Python
- uv
- rich
- textual
- textual-serve
- pytest for test suite execution
- pyrefly, ty, mypy, and zuban for LSP and or type checking
- hypothesis for property-based testing
