"""Regression tests for proxy lifecycle management.

The proxy module handles discovery, auto-start, and readiness polling for the
local ``agentsecrets`` daemon.  These tests lock down the contract so refactor
does not break the lifecycle:

* ``find_binary()`` uses ``shutil.which("agentsecrets")`` or raises ``CLINotFound``
* ``health_check()`` probes ``GET /health`` and returns ``ProxyStatus`` or raises ``ProxyConnectionError``
* ``auto_start()`` spawns the proxy with ``subprocess.Popen``
* ``wait_for_ready()`` polls with exponential backoff until healthy or timeout
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, Mock, patch

import pytest

from agentsecrets.errors import AgentSecretsNotRunning, CLINotFound, ProxyConnectionError
from agentsecrets.models import ProxyStatus
from agentsecrets.proxy import auto_start, find_binary, health_check, wait_for_ready


class TestFindBinary:
    """Binary discovery."""

    @patch("agentsecrets.proxy.shutil.which", return_value="/usr/local/bin/agentsecrets")
    def test_binary_found_returns_path(self, mock_which: Mock) -> None:
        path = find_binary()

        mock_which.assert_called_once_with("agentsecrets")
        assert path == "/usr/local/bin/agentsecrets"

    @patch("agentsecrets.proxy.shutil.which", return_value=None)
    def test_binary_not_found_raises_cli_not_found(self, mock_which: Mock) -> None:
        with pytest.raises(CLINotFound):
            find_binary()


class TestHealthCheck:
    """Health endpoint probing."""

    def test_healthy_proxy_returns_status(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url="http://localhost:8765/health",
            method="GET",
            json={"running": True, "project": "payments-service"},
        )

        status = health_check(8765)

        assert status.running is True
        assert status.port == 8765
        assert status.project == "payments-service"

    def test_connection_refused_raises_proxy_connection_error(self, httpx_mock) -> None:
        import httpx

        httpx_mock.add_exception(httpx.ConnectError("Connection refused"))

        with pytest.raises(ProxyConnectionError) as excinfo:
            health_check(8765)
        assert excinfo.value.port == 8765

    def test_http_error_raises_proxy_connection_error(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url="http://localhost:8765/health",
            method="GET",
            status_code=503,
        )

        with pytest.raises(ProxyConnectionError):
            health_check(8765)

    def test_invalid_json_raises_proxy_connection_error(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url="http://localhost:8765/health",
            method="GET",
            content=b"not-json",
        )

        with pytest.raises(ProxyConnectionError):
            health_check(8765)


class TestAutoStart:
    """Proxy auto-start."""

    @patch("agentsecrets.proxy.find_binary", return_value="/bin/agentsecrets")
    @patch("agentsecrets.proxy.subprocess.Popen")
    def test_spawns_proxy_start_command(self, mock_popen: Mock, mock_find: Mock) -> None:
        auto_start(9000)

        mock_find.assert_called_once()
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert call_args[0][0] == ["/bin/agentsecrets", "proxy", "start", "--port", "9000"]
        assert call_args[1]["stdout"] == subprocess.DEVNULL
        assert call_args[1]["stderr"] == subprocess.DEVNULL


class TestWaitForReady:
    """Readiness polling with exponential backoff."""

    @patch("agentsecrets.proxy.health_check")
    @patch("agentsecrets.proxy.time.sleep")
    def test_returns_immediately_when_healthy(
        self, mock_sleep: Mock, mock_health: Mock
    ) -> None:
        mock_health.return_value = ProxyStatus(running=True, port=8765, project="test")

        status = wait_for_ready(8765, timeout=10.0, interval=0.25)

        assert status.running is True
        mock_health.assert_called_once_with(8765)
        mock_sleep.assert_not_called()

    @patch("agentsecrets.proxy.health_check")
    @patch("agentsecrets.proxy.time.sleep")
    @patch("agentsecrets.proxy.time.monotonic", side_effect=[0.0, 0.3, 0.6, 1.0])
    def test_polls_with_backoff_until_healthy(
        self, mock_monotonic: Mock, mock_sleep: Mock, mock_health: Mock
    ) -> None:
        mock_health.side_effect = [
            ProxyConnectionError(8765, "not ready"),
            ProxyConnectionError(8765, "not ready"),
            ProxyStatus(running=True, port=8765, project="test"),
        ]

        status = wait_for_ready(8765, timeout=10.0, interval=0.25)

        assert status.running is True
        assert mock_health.call_count == 3
        assert mock_sleep.call_count == 2
        # Backoff: 0.25 * 1.5 = 0.375 (capped at 2.0)
        assert mock_sleep.call_args_list[0][0][0] == 0.25
        assert mock_sleep.call_args_list[1][0][0] == pytest.approx(0.375, rel=1e-3)

    @patch("agentsecrets.proxy.health_check")
    @patch("agentsecrets.proxy.time.sleep")
    @patch("agentsecrets.proxy.time.monotonic", side_effect=[0.0, 5.0, 11.0])
    def test_raises_not_running_after_timeout(
        self, mock_monotonic: Mock, mock_sleep: Mock, mock_health: Mock
    ) -> None:
        mock_health.side_effect = ProxyConnectionError(8765, "refused")

        with pytest.raises(AgentSecretsNotRunning) as excinfo:
            wait_for_ready(8765, timeout=10.0, interval=0.25)
        assert excinfo.value.port == 8765
