"""Single source of truth for the formtuitous version number.

This module exists so that both formtuitous.cli and
  The value must always match
the version in pyproject.toml.

Use it anywhere you need the version string:

    from formtuitous.version import FORMTUITOUS_VERSION
"""

FORMTUITOUS_VERSION = "0.1.0"
