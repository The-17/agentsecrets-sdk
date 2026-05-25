from __future__ import annotations

from typing import Any, Generator
from unittest.mock import MagicMock, patch

import httpx
import pytest

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None  # type: ignore[assignment]

from agentsecrets import AgentSecrets, credential, init, settings
from agentsecrets.config import Settings
from agentsecrets.interceptor import install_interceptor


@pytest.fixture(autouse=True)
def restore_http_clients_and_settings() -> Generator[None, None, None]:
    # Save original send methods to restore after test
    orig_requests_send = requests.Session.send if HAS_REQUESTS else None
    orig_httpx_send = httpx.Client.send
    orig_httpx_async_send = httpx.AsyncClient.send

    # Save settings state
    old_port = settings.port
    old_workspace = settings.workspace
    old_project = settings.project
    old_env = settings._environment

    yield

    # Restore send methods
    if HAS_REQUESTS and orig_requests_send:
        requests.Session.send = orig_requests_send  # type: ignore[method-assign]
    httpx.Client.send = orig_httpx_send  # type: ignore[method-assign]
    httpx.AsyncClient.send = orig_httpx_async_send  # type: ignore[method-assign]

    # Restore settings
    settings.port = old_port
    settings.workspace = old_workspace
    settings.project = old_project
    settings._environment = old_env


class TestCredentialHelper:
    def test_dynamic_placeholders(self) -> None:
        assert credential.GITHUB_TOKEN == "AS_SECRET_GITHUB_TOKEN"
        assert credential["STRIPE_API_KEY"] == "AS_SECRET_STRIPE_API_KEY"
        assert credential.get("OPENAI_API_KEY") == "AS_SECRET_OPENAI_API_KEY"


class TestSettingsEnvironment:
    @patch("agentsecrets._cli.run")
    def test_switch_environment_success(self, mock_cli_run: MagicMock) -> None:
        # Create a fresh settings instance for isolated testing
        test_settings = Settings()
        test_settings._environment = "development"

        # Change environment
        test_settings.environment = "staging"

        # Check CLI was invoked correctly
        mock_cli_run.assert_called_once_with("environment", "switch", "staging")
        assert test_settings.environment == "staging"

    @patch("agentsecrets._cli.run")
    def test_switch_environment_no_change(self, mock_cli_run: MagicMock) -> None:
        test_settings = Settings()
        test_settings._environment = "staging"

        # Change to same environment
        test_settings.environment = "staging"

        mock_cli_run.assert_not_called()

    @patch("agentsecrets._cli.run")
    def test_switch_environment_failure(self, mock_cli_run: MagicMock) -> None:
        mock_cli_run.side_effect = Exception("CLI error")
        test_settings = Settings()
        test_settings._environment = "development"

        err_msg = "Failed to switch AgentSecrets environment to 'staging'"
        with pytest.raises(ValueError, match=err_msg):
            test_settings.environment = "staging"


@pytest.mark.skipif(not HAS_REQUESTS, reason="requests library not installed")
class TestRequestsInterceptor:
    def test_requests_interceptor_bearer(self) -> None:
        # Install the interceptor
        install_interceptor()
        settings.port = 1234

        with patch("requests.adapters.HTTPAdapter.send") as mock_send:
            mock_send.return_value = requests.Response()

            session = requests.Session()
            session.get(
                "https://api.stripe.com/v1/charges",
                headers={"Authorization": "Bearer AS_SECRET_STRIPE_KEY"}
            )

            assert mock_send.call_count == 1
            args, kwargs = mock_send.call_args
            req = args[0] if args else kwargs.get("request")

            # Check that URL was routed to local proxy
            assert req.url == "http://localhost:1234/proxy"
            # Check target url header
            assert req.headers.get("X-AS-Target-URL") == "https://api.stripe.com/v1/charges"
            assert req.headers.get("X-AS-Method") == "GET"
            assert req.headers.get("X-AS-Inject-Bearer") == "STRIPE_KEY"
            # Check that original authorization placeholder was stripped
            assert "Authorization" not in req.headers

    def test_requests_interceptor_custom_header(self) -> None:
        install_interceptor()
        settings.port = 1234

        with patch("requests.adapters.HTTPAdapter.send") as mock_send:
            mock_send.return_value = requests.Response()

            session = requests.Session()
            session.post(
                "https://api.example.com/data",
                headers={"X-Custom-Header": "AS_SECRET_MY_TOKEN"}
            )

            args, kwargs = mock_send.call_args
            req = args[0] if args else kwargs.get("request")

            assert req.url == "http://localhost:1234/proxy"
            assert req.headers.get("X-AS-Target-URL") == "https://api.example.com/data"
            assert req.headers.get("X-AS-Method") == "POST"
            assert req.headers.get("X-AS-Inject-Header-X-Custom-Header") == "MY_TOKEN"
            assert "X-Custom-Header" not in req.headers


class TestHTTPInterceptors:
    def test_httpx_sync_interceptor(self) -> None:
        install_interceptor()
        settings.port = 5678

        received_request = None
        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_request
            received_request = request
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport) as client:
            client.get(
                "https://api.stripe.com/v1/charges",
                headers={"Authorization": "Bearer AS_SECRET_STRIPE_KEY"}
            )

        assert received_request is not None
        assert str(received_request.url) == "http://localhost:5678/proxy"
        assert received_request.headers.get("X-AS-Target-URL") == "https://api.stripe.com/v1/charges"
        assert received_request.headers.get("X-AS-Method") == "GET"
        assert received_request.headers.get("X-AS-Inject-Bearer") == "STRIPE_KEY"
        assert "Authorization" not in received_request.headers

    @pytest.mark.asyncio
    async def test_httpx_async_interceptor(self) -> None:
        install_interceptor()
        settings.port = 5678

        received_request = None
        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal received_request
            received_request = request
            return httpx.Response(200, json={"ok": True})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await client.get(
                "https://api.stripe.com/v1/charges",
                headers={"Authorization": "Bearer AS_SECRET_STRIPE_KEY"}
            )

        assert received_request is not None
        assert str(received_request.url) == "http://localhost:5678/proxy"
        assert received_request.headers.get("X-AS-Target-URL") == "https://api.stripe.com/v1/charges"
        assert received_request.headers.get("X-AS-Method") == "GET"
        assert received_request.headers.get("X-AS-Inject-Bearer") == "STRIPE_KEY"
        assert "Authorization" not in received_request.headers


class TestClientEnvironmentSwitching:
    @patch("agentsecrets._cli.run")
    def test_client_constructor_triggers_switch(self, mock_cli_run: MagicMock) -> None:
        with patch.dict("os.environ", {}, clear=True):
            AgentSecrets(
                port=8765,
                environment="production",
                auto_start=False
            )

        mock_cli_run.assert_called_once_with("environment", "switch", "production")
        assert settings.environment == "production"

    @patch("agentsecrets._cli.run")
    def test_client_init_helper(self, mock_cli_run: MagicMock) -> None:
        # Verify package-level init works as expected
        init(port=8888, environment="staging")
        mock_cli_run.assert_called_once_with("environment", "switch", "staging")
        assert settings.port == 8888
        assert settings.environment == "staging"
