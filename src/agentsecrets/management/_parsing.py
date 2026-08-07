"""Shared CLI output parsing helpers.

The AgentSecrets CLI uses ``lipgloss`` for styled terminal output.  Output
captured via ``subprocess`` may contain ANSI escape codes and Unicode
box-drawing characters from ``lipgloss.RoundedBorder()``.

This module provides helpers to strip ANSI codes and parse lipgloss-rendered
tables so that the management parsers can extract structured data reliably.
"""

from __future__ import annotations

import re

# ANSI escape sequence regex — covers CSI sequences (colours, cursor movement)
# and OSC sequences (hyperlinks, terminal titles).
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\].*?\x1b\\|\x1b\][^\x07]*\x07")


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)


# Unicode box-drawing characters used by lipgloss RoundedBorder:
#   ╭ ╮ ╰ ╯ │ ─ ┼ ├ ┤ ┬ ┴
_TABLE_BORDER_RE = re.compile(r"[╭╮╰╯├┤┬┴┼─]")


def parse_lipgloss_table(output: str) -> list[list[str]]:
    """Parse a lipgloss ``RoundedBorder`` table into rows of string cells.

    Returns a list of rows.  The first row is the header row; subsequent
    rows are data rows.  Each cell value is stripped of leading/trailing
    whitespace.

    Lines that are purely border characters (e.g. ``╭──────┬──────╮``)
    are skipped.  Cell values are split on the ``│`` column separator.
    """
    clean = strip_ansi(output)
    rows: list[list[str]] = []

    for line in clean.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Skip lines that are entirely border (no letters/digits).
        without_borders = _TABLE_BORDER_RE.sub("", stripped).strip()
        if not without_borders:
            continue

        # Lines containing │ are data/header rows.
        if "│" in stripped:
            cells = [c.strip() for c in stripped.split("│")]
            # The leading and trailing │ produce empty first/last cells.
            cells = [c for c in cells if c]
            if cells:
                rows.append(cells)

    return rows
