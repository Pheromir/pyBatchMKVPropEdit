"""Regular expressions typed by the user or read from a preset.

They run with the `regex` package and a time limit. A pattern with catastrophic backtracking, such as
`^(a|aa)+$`, would otherwise freeze the program: the standard `re` module cannot be interrupted. Matching
ignores case everywhere.
"""

from __future__ import annotations

import regex

TIMEOUT = 0.25  # seconds per search; normal patterns need microseconds
FLAGS = regex.IGNORECASE | regex.VERSION0  # VERSION0: the same syntax as the standard `re` module

error = regex.error


class RegexTimeout(Exception):
    """A search took longer than TIMEOUT and was stopped."""


def compile_error(pattern: str) -> str:
    """Why the pattern cannot be used, or "" if it is fine."""
    try:
        regex.compile(pattern, FLAGS)
    except regex.error as e:
        return str(e)
    return ""


def search(pattern: str, text: str):
    """regex.search with the time limit; raises regex.error for an invalid pattern and RegexTimeout."""
    try:
        return regex.search(pattern, text, FLAGS, timeout=TIMEOUT)
    except TimeoutError as e:
        raise RegexTimeout(pattern) from e


def group_count(pattern: str) -> int:
    return regex.compile(pattern, FLAGS).groups
