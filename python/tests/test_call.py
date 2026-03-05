"""Tests for call() header translation and error mapping.

Verifies that SDK call parameters are correctly translated into the
X-AS-* proxy headers that the Go server expects, and that proxy error
responses are mapped to the correct SDK exceptions.
"""

from __future__ import annotations

import json

import pytest

from agentsecrets.call import _build_proxy_headers, _map_proxy_error
from agentsecrets.errors import DomainNotAllowed, SecretNotFound, UpstreamError


class TestBuildProxyHeaders:
    """Verify parameter → header translation matches the Go parseInjections."""

    def test_bearer_injection(self) -> None:
        headers = _build_proxy_headers(
            "https://api.stripe.com/v1/charges",
            bearer="STRIPE_KEY",
        )
        assert headers["X-AS-Target-URL"] == "https://api.stripe.com/v1/charges"
        assert headers["X-AS-Inject-Bearer"] == "STRIPE_KEY"

    def test_basic_injection(self) -> None:
        headers = _build_proxy_headers(
            "https://api.example.com",
            basic="MY_CRED",
        )
        assert headers["X-AS-Inject-Basic"] == "MY_CRED"

    def test_header_injection(self) -> None:
        headers = _build_proxy_headers(
            "https://api.example.com",
            header={"X-Api-Key": "API_KEY", "X-Org-Id": "ORG_KEY"},
        )
        assert headers["X-AS-Inject-Header-X-Api-Key"] == "API_KEY"
        assert headers["X-AS-Inject-Header-X-Org-Id"] == "ORG_KEY"

    def test_query_injection(self) -> None:
        headers = _build_proxy_headers(
            "https://maps.googleapis.com/maps/api",
            query={"key": "GOOGLE_KEY"},
        )
        assert headers["X-AS-Inject-Query-key"] == "GOOGLE_KEY"

    def test_body_field_injection(self) -> None:
        headers = _build_proxy_headers(
            "https://api.example.com",
            body_field={"auth.key": "SECRET"},
        )
        assert headers["X-AS-Inject-Body-auth.key"] == "SECRET"

    def test_form_field_injection(self) -> None:
        headers = _build_proxy_headers(
            "https://api.example.com",
            form_field={"api_key": "KEY"},
        )
        assert headers["X-AS-Inject-Form-api_key"] == "KEY"

    def test_method_defaults_to_get(self) -> None:
        headers = _build_proxy_headers("https://example.com")
        assert headers["X-AS-Method"] == "GET"

    def test_method_uppercased(self) -> None:
        headers = _build_proxy_headers("https://example.com", method="post")
        assert headers["X-AS-Method"] == "POST"

    def test_agent_id(self) -> None:
        headers = _build_proxy_headers(
            "https://example.com",
            agent_id="claude-session-123",
        )
        assert headers["X-AS-Agent-ID"] == "claude-session-123"

    def test_multiple_injections(self) -> None:
        """Multiple injection styles in a single call."""
        headers = _build_proxy_headers(
            "https://api.example.com",
            bearer="TOKEN",
            header={"X-Custom": "CUSTOM_KEY"},
            query={"key": "QUERY_KEY"},
        )
        assert headers["X-AS-Inject-Bearer"] == "TOKEN"
        assert headers["X-AS-Inject-Header-X-Custom"] == "CUSTOM_KEY"
        assert headers["X-AS-Inject-Query-key"] == "QUERY_KEY"

    def test_no_injections(self) -> None:
        """Headers without any injection are just target + method."""
        headers = _build_proxy_headers("https://example.com")
        assert "X-AS-Target-URL" in headers
        assert "X-AS-Method" in headers
        # No X-AS-Inject-* headers present
        inject_headers = [k for k in headers if k.startswith("X-AS-Inject")]
        assert inject_headers == []


class TestMapProxyError:
    """Verify error body → SDK exception mapping reflects real Go proxy behaviour.

    The Go proxy (server.go:115) wraps ALL engine errors as 502.
    Domain blocks are the only errors that come back as 403 (engine.go:149).
    There is no 401.
    """

    def test_502_secret_not_found_raises_SecretNotFound(self) -> None:
        """The proxy sends 502 with the engine.go error message for missing keys."""
        body = json.dumps({
            "error": "secret 'FAKE_KEY_XYZ' not found in keychain — use list_secrets to see available keys"
        }).encode()
        exc = _map_proxy_error(502, body, "https://httpbin.org/get")
        assert isinstance(exc, SecretNotFound)
        assert exc.key == "FAKE_KEY_XYZ"

    def test_502_real_upstream_error_raises_UpstreamError(self) -> None:
        """A genuine 502 (e.g. upstream timed out) stays as UpstreamError."""
        body = json.dumps({"error": "upstream connection refused"}).encode()
        exc = _map_proxy_error(502, body, "https://api.stripe.com")
        assert isinstance(exc, UpstreamError)
        assert exc.status_code == 502

    def test_403_domain_blocked_raises_DomainNotAllowed(self) -> None:
        """Domain allowlist blocks come back as 403 from engine.logBlocked."""
        body = json.dumps({
            "error": "domain_not_in_allowlist",
            "domain": "httpbin.org",
            "message": "httpbin.org is not in your workspace allowlist",
        }).encode()
        exc = _map_proxy_error(403, body, "https://httpbin.org/get")
        assert isinstance(exc, DomainNotAllowed)
        assert exc.domain == "httpbin.org"


class TestDirectBypass:
    """Verify that call() and async_call() bypass the proxy when no injections are used."""

    def test_direct_bypass_sync(self, httpx_mock: httpx.MockTransport) -> None:
        """A sync call with no injections hits the target URL directly."""
        httpx_mock.add_response(
            url="https://api.example.com/status",
            method="GET",
            status_code=200,
            json={"ok": True},
        )

        from agentsecrets.call import call
        resp = call(8765, "https://api.example.com/status")

        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        
        # Verify the mock received the request at the actual URL, not localhost proxy
        request = httpx_mock.get_requests()[0]
        assert str(request.url) == "https://api.example.com/status"
        assert "X-AS-Target-URL" not in request.headers

    @pytest.mark.asyncio
    async def test_direct_bypass_async(self, httpx_mock: httpx.MockTransport) -> None:
        """An async call with no injections hits the target URL directly."""
        httpx_mock.add_response(
            url="https://api.example.com/status",
            method="POST",
            status_code=201,
            json={"created": True},
        )

        from agentsecrets.call import async_call
        resp = await async_call(8765, "https://api.example.com/status", method="POST", body={"foo": "bar"})

        assert resp.status_code == 201
        assert resp.json() == {"created": True}
        
        request = httpx_mock.get_requests()[0]
        assert str(request.url) == "https://api.example.com/status"
        # Content-Type should be set for the JSON body
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {"foo": "bar"}

    def test_direct_bypass_http_error(self, httpx_mock: httpx.MockTransport) -> None:
        """HTTP errors in bypass mode raise UpstreamError directly."""
        httpx_mock.add_response(
            url="https://api.example.com/fail",
            method="GET",
            status_code=404,
            text="Not Found",
        )

        from agentsecrets.call import call
        with pytest.raises(UpstreamError) as exc_info:
            call(8765, "https://api.example.com/fail")
            
        assert exc_info.value.status_code == 404
        assert exc_info.value.url == "https://api.example.com/fail"
        assert exc_info.value.body == "Not Found"

    def test_direct_bypass_network_error(self, httpx_mock: httpx.MockTransport) -> None:
        """Network errors in bypass mode raise UpstreamError with status 502."""
        import httpx
        
        def raise_timeout(*args: Any, **kwargs: Any) -> httpx.Response:
            raise httpx.ConnectTimeout("Connection timed out")
            
        httpx_mock.add_callback(raise_timeout)

        from agentsecrets.call import call
        with pytest.raises(UpstreamError) as exc_info:
            call(8765, "https://api.example.com/timeout")
            
        assert exc_info.value.status_code == 502
        assert exc_info.value.url == "https://api.example.com/timeout"
        assert "Connection timed out" in exc_info.value.body
