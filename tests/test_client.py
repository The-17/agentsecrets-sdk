"""Tests for the main AgentSecrets client."""

from __future__ import annotations

from unittest.mock import patch

from agentsecrets.client import AgentSecrets
from agentsecrets.management.allowlist import AllowlistClient
from agentsecrets.management.projects import ProjectsClient
from agentsecrets.management.proxy import ProxyClient
from agentsecrets.management.secrets import SecretsClient
from agentsecrets.management.workspaces import WorkspacesClient


class TestClientConstruction:
    """Client reads env vars and wires sub-clients."""

    def test_default_port(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            client = AgentSecrets(auto_start=False)
        assert client._port == 8765

    def test_custom_port_from_env(self) -> None:
        with patch.dict("os.environ", {"AGENTSECRETS_PORT": "9000"}):
            client = AgentSecrets(auto_start=False)
        assert client._port == 9000

    def test_custom_port_from_arg(self) -> None:
        client = AgentSecrets(port=9001, auto_start=False)
        assert client._port == 9001

    def test_sub_clients_exist(self) -> None:
        client = AgentSecrets(auto_start=False)
        assert isinstance(client.workspaces, WorkspacesClient)
        assert isinstance(client.projects, ProjectsClient)
        assert isinstance(client.secrets, SecretsClient)
        assert isinstance(client.proxy, ProxyClient)
        assert isinstance(client.allowlist, AllowlistClient)


class TestClientContextManager:
    """AgentSecrets as a context manager."""

    def test_enter_exit(self) -> None:
        with AgentSecrets(auto_start=False) as client:
            assert isinstance(client, AgentSecrets)
