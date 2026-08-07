"""Regression tests for the AsyncAgentSecrets client lifecycle.

Phase 2 introduced a dedicated async client whose primary API is
``await client.call(...)`` (not ``async_call``). These tests lock down the
contract, mirroring ``test_client_lifecycle.py`` for the sync client:

* ``aclose()`` marks the client closed, clears ``_auth``, and is idempotent
* after ``aclose()``, every operation raises ``RuntimeError``
* ``__aenter__`` returns self and guards against reuse
* ``__aexit__`` calls ``aclose()``
* ``call`` / ``spawn`` are coroutines delegating to the async engine
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentsecrets import AsyncAgentSecrets

URL = "https://api.stripe.com/v1/balance"


@pytest.fixture
def mock_auth():
    """Patch `resolve` to avoid spawning a real proxy."""
    with patch("agentsecrets.client.resolve") as mock_resolve:
        mock_resolve.return_value = MagicMock(port=8765, project="test")
        yield mock_resolve


class TestAclose:
    """aclose() behavior."""

    async def test_aclose_sets_is_closed_flag(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        assert not client._is_closed

        await client.aclose()

        assert client._is_closed

    async def test_aclose_clears_auth(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        with patch("agentsecrets.client._async_call", new=AsyncMock()):
            await client.call(URL, bearer="KEY")
        assert client._auth is not None

        await client.aclose()

        assert client._auth is None

    async def test_aclose_is_idempotent(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()
        await client.aclose()  # Should not raise

        assert client._is_closed


class TestReuseAfterAclose:
    """All operations raise RuntimeError after aclose()."""

    async def test_call_after_aclose_raises(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()

        with pytest.raises(RuntimeError) as excinfo:
            await client.call(URL, bearer="KEY")
        assert "Cannot use AgentSecrets client after close()" in str(excinfo.value)

    async def test_async_call_after_aclose_raises(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()

        with pytest.raises(RuntimeError):
            await client.async_call(URL, bearer="KEY")

    async def test_spawn_after_aclose_raises(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()

        with pytest.raises(RuntimeError):
            await client.spawn(["echo", "hello"])

    async def test_spawn_async_after_aclose_raises(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()

        with pytest.raises(RuntimeError):
            await client.spawn_async(["echo", "hello"])

    async def test_status_after_aclose_raises(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()

        with pytest.raises(RuntimeError):
            client.status()
class TestAsyncContextManager:
    """`async with` behavior."""

    async def test_aenter_returns_self(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        async with client as entered:
            assert entered is client

    async def test_aexit_closes_client(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        async with client:
            assert not client._is_closed
        assert client._is_closed

    async def test_aenter_after_aclose_raises(self, mock_auth) -> None:
        client = AsyncAgentSecrets(auto_start=False)
        await client.aclose()

        with pytest.raises(RuntimeError) as excinfo:
            async with client:
                pass
        assert "Cannot use AgentSecrets client after close()" in str(excinfo.value)

    async def test_operations_work_inside_context(self, mock_auth) -> None:
        with patch("agentsecrets.client._async_call", new=AsyncMock()) as mock_call:
            async with AsyncAgentSecrets(auto_start=False) as client:
                await client.call(URL, bearer="KEY")
        mock_call.assert_awaited_once()


class TestAsyncDelegation:
    """call/spawn are coroutines delegating to the async engine."""

    async def test_call_delegates_to_async_engine(self, mock_auth) -> None:
        with patch("agentsecrets.client._async_call", new=AsyncMock()) as mock_call:
            client = AsyncAgentSecrets(auto_start=False)
            await client.call(URL, bearer="STRIPE_KEY")

        mock_call.assert_awaited_once()
        # port comes from resolved auth; url is the first positional after port
        args, kwargs = mock_call.await_args
        assert args[0] == 8765
        assert args[1] == URL
        assert kwargs["bearer"] == "STRIPE_KEY"

    async def test_call_resolves_agent_identity(self, mock_auth) -> None:
        with patch("agentsecrets.client._async_call", new=AsyncMock()) as mock_call:
            client = AsyncAgentSecrets(auto_start=False)
            await client.call(URL, agent_id="billing-bot")

        _, kwargs = mock_call.await_args
        assert kwargs["agent_id"] == "billing-bot"
        assert kwargs["agent_token"] == "BILLING-BOT_TOKEN"

    async def test_spawn_delegates_to_async_engine(self, mock_auth) -> None:
        with patch("agentsecrets.client._spawn_async", new=AsyncMock()) as mock_spawn:
            client = AsyncAgentSecrets(auto_start=False)
            await client.spawn(["echo", "hi"], capture=False)

        mock_spawn.assert_awaited_once()
        args, kwargs = mock_spawn.await_args
        assert args[0] == ["echo", "hi"]
        assert kwargs["capture"] is False
