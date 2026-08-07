"""Regression tests for ``spawn()`` / ``spawn_async()`` process wrapping.

The SDK wraps ``agentsecrets env -- <command>`` to inject secrets as env vars
into child processes.  These tests lock down the subprocess contract so the
delegation to the CLI is not broken during refactor:

* ``find_binary()`` locates ``agentsecrets`` on PATH or raises ``CLINotFound``
* the full command is ``[binary, "env", "--"] + user_command``
* ``capture=True`` captures stdout/stderr; ``capture=False`` inherits parent streams
* exit code, stdout, stderr are returned in ``SpawnResult``
* async variant uses ``asyncio.create_subprocess_exec`` + ``wait_for``
* timeout raises ``CLIError`` with descriptive message
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from agentsecrets.errors import CLIError, CLINotFound
from agentsecrets.spawn import spawn, spawn_async


class TestSpawnSync:
    """Synchronous ``spawn()`` behaviour."""

    @patch("agentsecrets.spawn.find_binary", return_value="/usr/local/bin/agentsecrets")
    @patch("agentsecrets.spawn.subprocess.run")
    def test_builds_full_command_with_env_wrapper(
        self, mock_run: Mock, mock_find: Mock
    ) -> None:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        spawn(["node", "server.js"], capture=True)

        mock_find.assert_called_once()
        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == [
            "/usr/local/bin/agentsecrets",
            "env",
            "--",
            "node",
            "server.js",
        ]

    @patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets")
    @patch("agentsecrets.spawn.subprocess.run")
    def test_capture_true_returns_output(self, mock_run: Mock, mock_find: Mock) -> None:
        mock_run.return_value = Mock(
            returncode=0,
            stdout="All migrations complete",
            stderr="Warning: deprecated field",
        )

        result = spawn(["python", "manage.py", "migrate"], capture=True)

        assert result.exit_code == 0
        assert result.stdout == "All migrations complete"
        assert result.stderr == "Warning: deprecated field"
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["capture_output"] is True
        assert call_kwargs["text"] is True

    @patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets")
    @patch("agentsecrets.spawn.subprocess.run")
    def test_capture_false_inherits_streams(self, mock_run: Mock, mock_find: Mock) -> None:
        mock_run.return_value = Mock(returncode=0, stdout=None, stderr=None)

        result = spawn(["stripe", "mcp"], capture=False)

        assert result.exit_code == 0
        assert result.stdout == ""
        assert result.stderr == ""
        call_kwargs = mock_run.call_args[1]
        assert "capture_output" not in call_kwargs
        assert call_kwargs["stdout"] is None
        assert call_kwargs["stderr"] is None

    @patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets")
    @patch("agentsecrets.spawn.subprocess.run")
    def test_nonzero_exit_code_returned(self, mock_run: Mock, mock_find: Mock) -> None:
        mock_run.return_value = Mock(
            returncode=1,
            stdout="",
            stderr="ModuleNotFoundError: No module named 'django'",
        )

        result = spawn(["python", "manage.py", "test"], capture=True)

        assert result.exit_code == 1
        assert "ModuleNotFoundError" in result.stderr

    @patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets")
    @patch("agentsecrets.spawn.subprocess.run")
    def test_timeout_passed_to_subprocess(self, mock_run: Mock, mock_find: Mock) -> None:
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        spawn(["sleep", "1"], capture=True, timeout=5.0)

        assert mock_run.call_args[1]["timeout"] == 5.0

    @patch("agentsecrets.spawn.find_binary", side_effect=CLINotFound())
    def test_binary_not_found_raises_cli_not_found(self, mock_find: Mock) -> None:
        with pytest.raises(CLINotFound):
            spawn(["node", "server.js"])


class TestSpawnAsync:
    """Asynchronous ``spawn_async()`` behaviour (asyncio_mode = auto)."""

    async def test_async_round_trip_with_capture(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"output line\n", b"error line\n"))
        mock_exec = AsyncMock(return_value=mock_proc)

        with patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets"):
            with patch("agentsecrets.spawn.asyncio.create_subprocess_exec", mock_exec):
                result = await spawn_async(["echo", "hello"], capture=True)

        mock_exec.assert_awaited_once()
        assert mock_exec.call_args[0] == ("/bin/agentsecrets", "env", "--", "echo", "hello")
        assert result.exit_code == 0
        assert result.stdout == "output line\n"
        assert result.stderr == "error line\n"

    async def test_async_capture_false_no_pipe(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(None, None))
        mock_exec = AsyncMock(return_value=mock_proc)

        with patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets"):
            with patch("agentsecrets.spawn.asyncio.create_subprocess_exec", mock_exec):
                result = await spawn_async(["stripe", "mcp"], capture=False)

        # capture=False takes the else branch: no stdout/stderr PIPE kwargs.
        assert "stdout" not in mock_exec.call_args[1]
        assert result.stdout == ""
        assert result.stderr == ""

    async def test_async_timeout_raises_cli_error(self) -> None:
        async def raise_timeout() -> tuple[bytes, bytes]:
            raise asyncio.TimeoutError()

        mock_proc = MagicMock()
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock(return_value=None)
        mock_proc.communicate = raise_timeout
        mock_exec = AsyncMock(return_value=mock_proc)

        with patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets"):
            with patch("agentsecrets.spawn.asyncio.create_subprocess_exec", mock_exec):
                with pytest.raises(CLIError) as excinfo:
                    await spawn_async(["sleep", "100"], capture=True, timeout=0.1)

        assert "timed out" in str(excinfo.value).lower()
        mock_proc.kill.assert_called_once()

    async def test_async_nonzero_exit_code(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 127
        mock_proc.communicate = AsyncMock(return_value=(b"", b"command not found\n"))
        mock_exec = AsyncMock(return_value=mock_proc)

        with patch("agentsecrets.spawn.find_binary", return_value="/bin/agentsecrets"):
            with patch("agentsecrets.spawn.asyncio.create_subprocess_exec", mock_exec):
                result = await spawn_async(["nonexistent"], capture=True)

        assert result.exit_code == 127
        assert "command not found" in result.stderr
