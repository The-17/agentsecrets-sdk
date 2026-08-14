"""Internal CLI subprocess runner.

All management operations shell out to the ``agentsecrets`` binary.
This module provides the single, shared wrapper that every management
sub-client uses — keeping subprocess handling in one place (DRY).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from .errors import CLIError
from .proxy import find_binary


@dataclass(frozen=True)
class CLIResult:
    """Raw output from a CLI invocation."""

    exit_code: int
    stdout: str
    stderr: str


def run(
    *args: str,
    capture: bool = True,
    timeout: float = 30.0,
) -> CLIResult:
    """Run ``agentsecrets <args>`` and return the output.

    Raises
    ------
    CLINotFound
        If the binary is not on PATH.
    CLIError
        If the command exits with a non-zero code.
    """
    binary = find_binary()
    full_cmd = [binary, *args]

    try:
        result = subprocess.run(
            full_cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )  # noqa: S603
    except subprocess.TimeoutExpired:
        raise CLIError(" ".join(args), -1, "Command timed out")

    if result.returncode != 0:
        raise CLIError(" ".join(args), result.returncode, result.stderr or "")

    return CLIResult(
        exit_code=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )


def run_json(*args: str, timeout: float = 30.0, fallback_parser: Callable[[str], dict[str, Any] | list[Any]] | None = None) -> dict[str, Any] | list[Any]:
    """Run a CLI command with --output json if available, else fallback parser."""
    # Try JSON first
    try:
        result = run(*args, "--output", "json", timeout=timeout)
        return json.loads(result.stdout)  # type: ignore[no-any-return]
    except CLIError as e:
        # If "--output json" flag not recognized, fallback to text parsing
        if fallback_parser and "unknown flag" in e.stderr.lower():
            result = run(*args, timeout=timeout)
            return fallback_parser(result.stdout)
        raise
