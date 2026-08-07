"""Process spawning with injected secrets.

Wraps ``agentsecrets env -- <command>`` to launch child processes with
secrets injected as environment variables.  The SDK never touches the
credential values — the CLI handles keychain resolution.
"""

from __future__ import annotations

import asyncio
import subprocess

from .errors import CLIError
from .models import SpawnResult
from .proxy import find_binary


def spawn(
    command: list[str],
    *,
    capture: bool = True,
    timeout: float | None = None,
) -> SpawnResult:
    """Run a command with secrets injected as environment variables.

    Delegates to ``agentsecrets env -- <command>``.

    Parameters
    ----------
    command:
        The command and arguments to run, e.g. ``["node", "server.js"]``.
    capture:
        If ``True`` (default), capture stdout/stderr.  Otherwise, let the
        child inherit the parent's streams.
    timeout:
        Maximum seconds to wait for the process.  ``None`` for no limit.
    """
    binary = find_binary()
    full_cmd = [binary, "env", "--"] + command

    kwargs: dict = {"timeout": timeout}
    if capture:
        kwargs["capture_output"] = True
        kwargs["text"] = True
    else:
        kwargs["stdout"] = None
        kwargs["stderr"] = None

    result = subprocess.run(full_cmd, **kwargs)  # noqa: S603

    return SpawnResult(
        exit_code=result.returncode,
        stdout=result.stdout or "",
        stderr=result.stderr or "",
    )


async def spawn_async(
    command: list[str],
    *,
    capture: bool = True,
    timeout: float | None = None,
) -> SpawnResult:
    """Async variant of :func:`spawn`."""
    binary = find_binary()
    full_cmd = [binary, "env", "--"] + command

    if capture:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    else:
        proc = await asyncio.create_subprocess_exec(*full_cmd)

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CLIError("env -- " + " ".join(command), -1, "Process timed out")

    return SpawnResult(
        exit_code=proc.returncode or 0,
        stdout=(stdout_bytes or b"").decode("utf-8", errors="replace"),
        stderr=(stderr_bytes or b"").decode("utf-8", errors="replace"),
    )
