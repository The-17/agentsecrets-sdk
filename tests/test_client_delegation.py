"""Regression tests for the client's agent-identity resolution.

``AgentSecrets.call()`` / ``async_call()`` resolve an effective agent id and
token before delegating to the low-level ``call()``.  This logic (client.py
lines 142-158) is currently untested and easy to break.  These tests lock it
down by patching ``resolve`` (so no proxy is needed) and ``_call`` (so no
network happens), then asserting the exact ``agent_id`` / ``agent_token``
passed through.

Resolution rules being locked:
* precedence: explicit ``agent`` arg > ``agent_id`` arg > constructor ``agent``
* a string agent becomes ``agent_id`` verbatim
* an object with ``.name`` contributes its name as ``agent_id``
* when no token is supplied, one is synthesised as ``f"{ID.upper()}_TOKEN"``
* an explicit token (arg or constructor) is never overwritten
* with no agent at all, both ``agent_id`` and ``agent_token`` are ``None``
* all other call parameters pass straight through
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentsecrets import AgentSecrets
from agentsecrets.agent import Agent
from agentsecrets.auth import AuthContext

URL = "https://api.stripe.com/v1/balance"


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):
    """Patch auth resolution and the low-level sync/async call functions."""
    # Keep constructor env-driven environment switching from shelling out.
    monkeypatch.delenv("AGENTSECRETS_ENV", raising=False)
    monkeypatch.delenv("AS_ENV", raising=False)

    auth = AuthContext(port=8765, project="payments", method="proxy")
    sentinel = object()
    mock_call = MagicMock(return_value=sentinel)
    mock_async_call = AsyncMock(return_value=sentinel)

    with patch("agentsecrets.client.resolve", return_value=auth), patch(
        "agentsecrets.client._call", mock_call
    ), patch("agentsecrets.client._async_call", mock_async_call):
        yield mock_call, mock_async_call, sentinel


class TestAgentResolutionSync:
    """Agent-identity resolution on the synchronous ``call()`` path."""

    def test_string_agent_synthesises_token(self, patched) -> None:
        mock_call, _, sentinel = patched

        result = AgentSecrets().call(URL, agent="claude-worker")

        assert result is sentinel
        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] == "claude-worker"
        assert kwargs["agent_token"] == "CLAUDE-WORKER_TOKEN"

    def test_explicit_token_not_overwritten(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets().call(URL, agent="claude-worker", agent_token="real-secret-token")

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] == "claude-worker"
        assert kwargs["agent_token"] == "real-secret-token"

    def test_agent_object_uses_name(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets().call(URL, agent=Agent(name="billing-bot"))

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] == "billing-bot"
        assert kwargs["agent_token"] == "BILLING-BOT_TOKEN"

    def test_agent_id_arg_is_treated_as_agent(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets().call(URL, agent_id="svc-account")

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] == "svc-account"
        assert kwargs["agent_token"] == "SVC-ACCOUNT_TOKEN"

    def test_constructor_agent_used_as_fallback(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets(agent="ctor-agent").call(URL)

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] == "ctor-agent"
        assert kwargs["agent_token"] == "CTOR-AGENT_TOKEN"

    def test_call_arg_overrides_constructor_agent(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets(agent="ctor-agent").call(URL, agent="call-agent")

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] == "call-agent"

    def test_constructor_token_used_when_no_call_token(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets(agent="a", agent_token="ctor-token").call(URL)

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_token"] == "ctor-token"

    def test_no_agent_yields_none(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets().call(URL, bearer="STRIPE_KEY")

        kwargs = mock_call.call_args.kwargs
        assert kwargs["agent_id"] is None
        assert kwargs["agent_token"] is None

    def test_all_params_pass_through(self, patched) -> None:
        mock_call, _, _ = patched

        AgentSecrets().call(
            URL,
            method="POST",
            body={"amount": 1000},
            bearer="STRIPE_KEY",
            header={"X-Org": "ORG_KEY"},
            timeout=12.5,
        )

        args = mock_call.call_args.args
        kwargs = mock_call.call_args.kwargs
        # Under binary delegation the URL is the first positional argument;
        # there is no proxy port on the call path anymore.
        assert args[0] == URL
        assert kwargs["method"] == "POST"
        assert kwargs["body"] == {"amount": 1000}
        assert kwargs["bearer"] == "STRIPE_KEY"
        assert kwargs["header"] == {"X-Org": "ORG_KEY"}
        assert kwargs["timeout"] == 12.5


class TestAgentResolutionAsync:
    """The async path applies identical resolution rules."""

    async def test_async_string_agent_synthesises_token(self, patched) -> None:
        _, mock_async_call, sentinel = patched

        result = await AgentSecrets().async_call(URL, agent="async-agent")

        assert result is sentinel
        kwargs = mock_async_call.call_args.kwargs
        assert kwargs["agent_id"] == "async-agent"
        assert kwargs["agent_token"] == "ASYNC-AGENT_TOKEN"

    async def test_async_no_agent_yields_none(self, patched) -> None:
        _, mock_async_call, _ = patched

        await AgentSecrets().async_call(URL, bearer="OPENAI_KEY")

        kwargs = mock_async_call.call_args.kwargs
        assert kwargs["agent_id"] is None
        assert kwargs["agent_token"] is None
