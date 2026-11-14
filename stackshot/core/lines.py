"""lines.py: a text cut into its lines at newlines and nowhere else.

`str.splitlines()` also cuts at a vertical tab, a form feed, the file, group and record separators, U+0085, U+2028 and U+2029. JSON leaves U+0085, U+2028
and U+2029 raw inside a string (`ensure_ascii=False`, which the logs and stores here use), so a record that holds one is cut in two by `splitlines()` and
neither half reads. A reader of a one-record-per-line file uses `newline_lines` instead.
"""
from __future__ import annotations


def newline_lines(text: str) -> list[str]:
    """The lines of `text`, cut at "\\n" only. For text with no other line separator this is what `text.splitlines()` returns: no empty last element for a
    trailing newline, and the "\\r" of a "\\r\\n" ending off. A lone "\\r" is no line end here (a record never ends at one: JSON escapes it)."""
    parts = text.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [p[:-1] if p.endswith("\r") else p for p in parts]
