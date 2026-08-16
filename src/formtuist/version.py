"""Single source of truth for the formtuist version number.

This module exists so that both formtuist.cli and
  The value must always match
the version in pyproject.toml.

Use it anywhere you need the version string:

    from formtuist.version import FORMTUIST_VERSION
"""

FORMTUIST_VERSION = "0.1.0"
