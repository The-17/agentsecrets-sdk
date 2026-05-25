"""Tests for auth resolution."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agentsecrets.auth import resolve
from agentsecrets.errors import AgentSecretsNotRunning, ProxyConnectionError
from agentsecrets.models import ProxyStatus


class TestResolve:
    """Auth resolution follows the correct fallback order."""

    def test_running_proxy_returns_proxy_auth(self) -> None:
        with patch("agentsecrets.auth.health_check") as mock_health:
            mock_health.return_value = ProxyStatus(running=True, port=8765, project="test")
            ctx = resolve(8765, auto_start_proxy=False)

        assert ctx.method == "proxy"
        assert ctx.port == 8765
        assert ctx.project == "test"

    def test_no_proxy_raises(self) -> None:
        with (
            patch("agentsecrets.auth.health_check", side_effect=ProxyConnectionError(8765, "refused")),
            patch.dict("os.environ", {}, clear=True),
        ):
            with pytest.raises(AgentSecretsNotRunning):
                resolve(8765, auto_start_proxy=False)

    def test_auto_start_attempts_start(self) -> None:
        with (
            patch("agentsecrets.auth.health_check", side_effect=ProxyConnectionError(8765, "refused")),
            patch.dict("os.environ", {}, clear=True),
            patch("agentsecrets.auth.auto_start") as mock_start,
            patch("agentsecrets.auth.wait_for_ready") as mock_wait,
        ):
            mock_wait.return_value = ProxyStatus(running=True, port=8765, project="test")
            ctx = resolve(8765, auto_start_proxy=True)

        mock_start.assert_called_once_with(8765)
        assert ctx.method == "proxy"
