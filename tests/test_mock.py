"""Tests for MockAgentSecrets."""

from __future__ import annotations

from agentsecrets.models import AgentSecretsResponse, SpawnResult
from agentsecrets.testing import MockAgentSecrets


class TestMockCall:
    """Mock call recording."""

    def test_records_call(self) -> None:
        mock = MockAgentSecrets()
        mock.call("https://api.stripe.com", bearer="STRIPE_KEY", method="POST")

        assert len(mock.calls) == 1
        assert mock.calls[0].url == "https://api.stripe.com"
        assert mock.calls[0].bearer == "STRIPE_KEY"
        assert mock.calls[0].method == "POST"

    def test_returns_default_response(self) -> None:
        mock = MockAgentSecrets()
        resp = mock.call("https://example.com")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_custom_response(self) -> None:
        custom = AgentSecretsResponse(
            status_code=201,
            headers={},
            body=b'{"id": "ch_123"}',
        )
        mock = MockAgentSecrets(default_response=custom)
        resp = mock.call("https://api.stripe.com", bearer="KEY")

        assert resp.status_code == 201
        assert resp.json()["id"] == "ch_123"

    def test_records_multiple_calls(self) -> None:
        mock = MockAgentSecrets()
        mock.call("https://a.com", bearer="A")
        mock.call("https://b.com", header={"X-Key": "B"})

        assert len(mock.calls) == 2
        assert mock.calls[0].bearer == "A"
        assert mock.calls[1].header == {"X-Key": "B"}

    def test_never_stores_credential_values(self) -> None:
        """Call records store key names, never values."""
        mock = MockAgentSecrets()
        mock.call("https://example.com", bearer="MY_KEY")

        record = mock.calls[0]
        # The record has the key name, not a value.
        assert record.bearer == "MY_KEY"
        assert not hasattr(record, "value")
        assert not hasattr(record, "secret_value")


class TestMockSpawn:
    """Mock spawn recording."""

    def test_records_spawn(self) -> None:
        mock = MockAgentSecrets()
        mock.spawn(["node", "server.js"])

        assert len(mock.spawns) == 1
        assert mock.spawns[0].command == ["node", "server.js"]

    def test_returns_default_result(self) -> None:
        mock = MockAgentSecrets()
        result = mock.spawn(["echo", "hello"])
        assert result.exit_code == 0

    def test_custom_result(self) -> None:
        custom = SpawnResult(exit_code=1, stderr="failed")
        mock = MockAgentSecrets(default_spawn_result=custom)
        result = mock.spawn(["bad-command"])

        assert result.exit_code == 1
        assert result.stderr == "failed"


class TestMockContextManager:
    """MockAgentSecrets as a context manager."""

    def test_context_manager(self) -> None:
        with MockAgentSecrets() as mock:
            mock.call("https://example.com")
        assert len(mock.calls) == 1
