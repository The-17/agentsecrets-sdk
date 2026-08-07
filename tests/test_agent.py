"""Tests for Agent Identity management and call scoping."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agentsecrets import agent, AgentSecrets, AgentCapabilities, AgentToken, IssuedAgentToken
from agentsecrets._cli import CLIResult
from agentsecrets.agent import Agent
from agentsecrets.call import _build_proxy_headers


class TestAgentParsingAndCli:
    """Verify stdout parsing of CLI tables and register commands."""

    @patch("agentsecrets.agent.run")
    def test_list_agents(self, mock_cli_run: MagicMock) -> None:
        stdout = (
            "AGENT                SCOPE           TOKENS   LAST USED                 REGISTERED\n"
            "coder-agent          workspace       1        never                     2026-06-11\n"
            "prod-agent           my-project      2        2026-06-11 15:04 UTC      2026-06-11\n"
        )
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout=stdout, stderr="")

        agents = agent.list()
        mock_cli_run.assert_called_once_with("agent", "list")

        assert len(agents) == 2
        assert agents[0].name == "coder-agent"
        assert agents[0].project_id is None
        assert agents[0].token_count == 1
        assert agents[0].last_used is None
        assert agents[0].created_at == "2026-06-11"

        assert agents[1].name == "prod-agent"
        assert agents[1].project_id == "my-project"
        assert agents[1].token_count == 2
        assert agents[1].last_used == "2026-06-11 15:04 UTC"

    @patch("agentsecrets.agent.run")
    def test_create_agent(self, mock_cli_run: MagicMock) -> None:
        stdout = (
            "\nAgent registered\n"
            "  Name     test-agent\n"
            "  Scope    my-project\n"
            "  Token    agt_cleartexttoken123\n"
            "  Expires  2026-07-11\n"
        )
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout=stdout, stderr="")

        issued = agent.create(
            "test-agent",
            project="my-project",
            label="test-label",
            expires="30d",
            save_token=True,
        )

        mock_cli_run.assert_called_once_with(
            "agent", "register", "test-agent",
            "--project", "my-project",
            "--label", "test-label",
            "--expires", "30d",
            "--save-token",
        )

        assert isinstance(issued, IssuedAgentToken)
        assert issued.agent.name == "test-agent"
        assert issued.agent.project_id == "my-project"
        assert issued.token == "agt_cleartexttoken123"
        assert issued.expires_at == "2026-07-11"

    @patch("agentsecrets.agent.run")
    def test_delete_agent(self, mock_cli_run: MagicMock) -> None:
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout="", stderr="")

        agent.delete("my-agent", confirm=True)
        mock_cli_run.assert_called_once_with("agent", "delete", "my-agent", "--confirm")

    @patch("agentsecrets.agent.run")
    def test_list_tokens(self, mock_cli_run: MagicMock) -> None:
        stdout = (
            "TOKEN ID             LABEL           EXPIRES         LAST USED                 STATUS\n"
            "tok_123              init-token      2026-07-11      never                     active\n"
            "tok_456              (none)          (none)          2026-06-11 15:00 UTC      revoked\n"
        )
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout=stdout, stderr="")

        tokens = agent.list_tokens("test-agent")
        mock_cli_run.assert_called_once_with("agent", "token", "list", "test-agent")

        assert len(tokens) == 2
        assert tokens[0].id == "tok_123"
        assert tokens[0].agent_id == "test-agent"
        assert tokens[0].label == "init-token"
        assert tokens[0].expires_at == "2026-07-11"
        assert tokens[0].last_used is None
        assert tokens[0].status == "active"

        assert tokens[1].id == "tok_456"
        assert tokens[1].label == ""
        assert tokens[1].expires_at is None
        assert tokens[1].last_used == "2026-06-11 15:00 UTC"
        assert tokens[1].status == "revoked"

    @patch("agentsecrets.agent.run")
    def test_issue_token(self, mock_cli_run: MagicMock) -> None:
        stdout = (
            "\nToken issued\n"
            "  Agent    test-agent\n"
            "  Token    agt_issuedtoken999\n"
            "  Label    new-token-label\n"
            "  Expires  2026-09-11\n"
        )
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout=stdout, stderr="")

        # We also mock agent.get (which runs agent.list) to resolve the agent object inside issue_token
        list_stdout = (
            "AGENT                SCOPE           TOKENS   LAST USED                 REGISTERED\n"
            "test-agent           workspace       1        never                     2026-06-11\n"
        )
        with patch("agentsecrets.agent.list") as mock_list:
            mock_list.return_value = [Agent(name="test-agent")]
            issued = agent.issue_token("test-agent", label="new-token-label", save_token=True)

        mock_cli_run.assert_called_once_with(
            "agent", "token", "issue", "test-agent",
            "--label", "new-token-label",
            "--save-token",
        )
        assert issued.token == "agt_issuedtoken999"
        assert issued.label == "new-token-label"
        assert issued.expires_at == "2026-09-11"

    @patch("agentsecrets.agent.run")
    def test_revoke_token(self, mock_cli_run: MagicMock) -> None:
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout="", stderr="")

        agent.revoke_token("my-agent", "tok_123", confirm=True)
        mock_cli_run.assert_called_once_with(
            "agent", "token", "revoke", "tok_123",
            "--agent", "my-agent",
            "--confirm",
        )

    @patch("agentsecrets.agent.run")
    def test_revoke_all_tokens(self, mock_cli_run: MagicMock) -> None:
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout="", stderr="")

        agent.revoke_all_tokens("my-agent", confirm=True)
        mock_cli_run.assert_called_once_with(
            "agent", "token", "revoke", "--all",
            "--agent", "my-agent",
            "--confirm",
        )

    @patch("agentsecrets.agent.run")
    def test_get_policy(self, mock_cli_run: MagicMock) -> None:
        stdout = (
            "\nAgent Policy for my-agent:\n"
            "  Allowed Secrets: STRIPE_KEY, GITHUB_TOKEN\n"
            "  Denied Secrets:  (none)\n"
        )
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout=stdout, stderr="")

        caps = agent.get_policy("my-agent")
        mock_cli_run.assert_called_once_with("agent", "policy", "get", "my-agent")

        assert isinstance(caps, AgentCapabilities)
        assert caps.allowed_secrets == ["STRIPE_KEY", "GITHUB_TOKEN"]
        assert caps.denied_secrets == []

    @patch("agentsecrets.agent.run")
    def test_set_policy(self, mock_cli_run: MagicMock) -> None:
        mock_cli_run.return_value = CLIResult(exit_code=0, stdout="", stderr="")

        agent.set_policy("my-agent", allow=["STRIPE_KEY"], deny=["GITHUB_TOKEN"])
        mock_cli_run.assert_called_once_with(
            "agent", "policy", "set", "my-agent",
            "--allow", "STRIPE_KEY",
            "--deny", "GITHUB_TOKEN",
        )


class TestAgentHeaderInjection:
    """Verify that agent settings are correctly mapped to proxy headers."""

    def test_build_headers_with_agent_token(self) -> None:
        headers = _build_proxy_headers(
            "https://api.stripe.com/v1/charges",
            agent_id="my-agent",
            agent_token="my-custom-token",
        )
        assert headers["X-AS-Agent-ID"] == "my-agent"
        assert headers["X-AS-Agent-Token"] == "my-custom-token"

    @patch("agentsecrets.client.AgentSecrets._ensure_auth")
    def test_client_call_resolution_explicit_agent_string(self, mock_ensure_auth: MagicMock) -> None:
        mock_ensure_auth.return_value = MagicMock(port=8765)
        client = AgentSecrets(auto_start=False)
        with patch("agentsecrets.client._call") as mock_call:
            mock_call.return_value = MagicMock()
            client.call("https://api.stripe.com", agent="my-agent-str")

            assert mock_call.call_count == 1
            _, kwargs = mock_call.call_args
            assert kwargs["agent_id"] == "my-agent-str"
            assert kwargs["agent_token"] == "MY-AGENT-STR_TOKEN"

    @patch("agentsecrets.client.AgentSecrets._ensure_auth")
    def test_client_call_resolution_explicit_agent_object(self, mock_ensure_auth: MagicMock) -> None:
        mock_ensure_auth.return_value = MagicMock(port=8765)
        client = AgentSecrets(auto_start=False)
        my_agent = Agent(name="my-custom-agent")

        with patch("agentsecrets.client._call") as mock_call:
            mock_call.return_value = MagicMock()
            client.call("https://api.stripe.com", agent=my_agent)

            assert mock_call.call_count == 1
            _, kwargs = mock_call.call_args
            assert kwargs["agent_id"] == "my-custom-agent"
            assert kwargs["agent_token"] == "MY-CUSTOM-AGENT_TOKEN"

    @patch("agentsecrets.client.AgentSecrets._ensure_auth")
    def test_client_constructor_resolves_agent(self, mock_ensure_auth: MagicMock) -> None:
        mock_ensure_auth.return_value = MagicMock(port=8765)
        client = AgentSecrets(agent="client-agent", agent_token="client-token", auto_start=False)
        with patch("agentsecrets.client._call") as mock_call:
            mock_call.return_value = MagicMock()
            client.call("https://api.stripe.com")

            _, kwargs = mock_call.call_args
            assert kwargs["agent_id"] == "client-agent"
            assert kwargs["agent_token"] == "client-token"

    @patch("agentsecrets.client.AgentSecrets._ensure_auth")
    def test_agent_object_shortcut_call(self, mock_ensure_auth: MagicMock) -> None:
        mock_ensure_auth.return_value = MagicMock(port=8765)
        my_agent = Agent(name="shortcut-agent")

        with patch("agentsecrets.client._call") as mock_call:
            mock_call.return_value = MagicMock()
            my_agent.call("https://api.stripe.com", bearer="STRIPE_KEY")

            assert mock_call.call_count == 1
            _, kwargs = mock_call.call_args
            assert kwargs["agent_id"] == "shortcut-agent"
            assert kwargs["agent_token"] == "SHORTCUT-AGENT_TOKEN"
            assert kwargs["bearer"] == "STRIPE_KEY"
