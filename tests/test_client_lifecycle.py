"""Regression tests for AgentSecrets client lifecycle management.

Phase 2 added proper resource cleanup via `close()` and context managers.
These tests lock down the contract:

* `close()` marks the client as closed and clears `_auth`
* After `close()`, all operations raise `RuntimeError` with a clear message
* `__enter__` returns self and guards against reuse
* `__exit__` calls `close()`
* Closing an already-closed client is idempotent
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentsecrets import AgentSecrets


@pytest.fixture
def mock_auth():
    """Patch `resolve` to avoid spawning a real proxy."""
    with patch("agentsecrets.client.resolve") as mock_resolve:
        mock_resolve.return_value = MagicMock(port=8765, project="test")
        yield mock_resolve


class TestClose:
    """close() behavior."""

    def test_close_sets_is_closed_flag(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        assert not client._is_closed

        client.close()

        assert client._is_closed

    def test_close_clears_auth(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        # Force the optional persistent-proxy warm-up (call() no longer resolves
        # auth under binary delegation, so exercise the warm-up path directly).
        client._ensure_auth()
        assert client._auth is not None

        client.close()

        assert client._auth is None

    def test_close_is_idempotent(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()
        client.close()  # Should not raise

        assert client._is_closed


class TestReuseAfterClose:
    """All operations raise RuntimeError after close()."""

    def test_call_after_close_raises(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()

        with pytest.raises(RuntimeError) as excinfo:
            client.call("https://api.example.com", bearer="KEY")
        assert "Cannot use AgentSecrets client after close()" in str(excinfo.value)

    async def test_async_call_after_close_raises(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()

        with pytest.raises(RuntimeError) as excinfo:
            await client.async_call("https://api.example.com", bearer="KEY")
        assert "Cannot use AgentSecrets client after close()" in str(excinfo.value)

    def test_spawn_after_close_raises(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()

        with pytest.raises(RuntimeError):
            client.spawn(["echo", "hello"])

    async def test_spawn_async_after_close_raises(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()

        with pytest.raises(RuntimeError):
            await client.spawn_async(["echo", "hello"])

    def test_status_after_close_raises(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()

        with pytest.raises(RuntimeError):
            client.status()


class TestContextManager:
    """Context manager protocol."""

    def test_enter_returns_self(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)

        with client as entered:
            assert entered is client

    def test_exit_calls_close(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)

        with client:
            assert not client._is_closed

        assert client._is_closed

    def test_enter_after_close_raises(self, mock_auth) -> None:
        client = AgentSecrets(auto_start=False)
        client.close()

        with pytest.raises(RuntimeError) as excinfo:
            with client:
                pass
        assert "Cannot use AgentSecrets client after close()" in str(excinfo.value)

    def test_operations_work_inside_context(self, mock_auth) -> None:
        """Verify the client is usable within the context manager."""
        client = AgentSecrets(auto_start=False)

        with patch("agentsecrets.client._call") as mock_call:
            mock_call.return_value = MagicMock()

            with client:
                # Should not raise
                client.call("https://api.example.com", bearer="KEY")

            # After exiting, should be closed
            assert client._is_closed
