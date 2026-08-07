"""Regression tests for transparent HTTP interception.

The interceptor monkeypatches ``httpx.Client.send``, ``httpx.AsyncClient.send``,
and ``requests.Session.send`` to detect ``AS_SECRET_`` placeholders in headers,
rewrite the target URL to the local proxy, and attach ``X-AS-*`` injection headers.

These tests lock down that monkeypatch contract so the interception machinery
is not broken during refactor:

* ``parse_placeholder`` recognizes ``AS_SECRET_<key>`` (header) and ``BEARER AS_SECRET_<key>`` (bearer)
* ``install_interceptor`` globally patches send methods (no restore)
* placeholder headers are deleted and converted to ``X-AS-Inject-*`` headers
* the URL is rewritten to ``http://localhost:{settings.port}/proxy``
* non-placeholder requests pass through untouched
* httpx sync + async both work; requests is optional (importorskip)

A fixture SAVES and RESTORES the original send methods so tests do not
pollute the global suite.
"""

from __future__ import annotations

import pytest

from agentsecrets.interceptor import install_interceptor, parse_placeholder


class TestParsePlaceholder:
    """Placeholder detection logic."""

    def test_header_style_returns_header_key(self) -> None:
        result = parse_placeholder("AS_SECRET_STRIPE_KEY")
        assert result == ("header", "STRIPE_KEY")

    def test_bearer_style_returns_bearer_key(self) -> None:
        result = parse_placeholder("Bearer AS_SECRET_OPENAI_KEY")
        assert result == ("bearer", "OPENAI_KEY")

    def test_case_insensitive_bearer(self) -> None:
        result = parse_placeholder("BEARER AS_SECRET_GITHUB_TOKEN")
        assert result == ("bearer", "GITHUB_TOKEN")

    def test_bytes_input_decoded(self) -> None:
        result = parse_placeholder(b"AS_SECRET_KEY")
        assert result == ("header", "KEY")

    def test_non_placeholder_returns_none(self) -> None:
        assert parse_placeholder("sk_live_real_stripe_key") is None
        assert parse_placeholder("Authorization: Bearer xyz") is None
        assert parse_placeholder("AS_SECRETKEY") is None  # missing underscore

    def test_whitespace_stripped(self) -> None:
        result = parse_placeholder("  AS_SECRET_KEY  ")
        assert result == ("header", "KEY")


@pytest.fixture
def _restore_httpx_send():
    """Save and restore httpx send methods to prevent global pollution."""
    import httpx

    original_sync_send = httpx.Client.send
    original_async_send = httpx.AsyncClient.send

    yield

    httpx.Client.send = original_sync_send  # type: ignore[method-assign]
    httpx.AsyncClient.send = original_async_send  # type: ignore[method-assign]


@pytest.fixture
def _restore_requests_send():
    """Save and restore requests send method (optional, skip if not installed)."""
    requests = pytest.importorskip("requests")
    original_send = requests.Session.send

    yield

    requests.Session.send = original_send  # type: ignore[method-assign]


class TestInstallInterceptorHttpx:
    """httpx interception behaviour (sync + async)."""

    @pytest.fixture(autouse=True)
    def _setup(self, _restore_httpx_send):
        """Reinstall the interceptor for each test in a clean state."""
        install_interceptor()

    def test_httpx_sync_placeholder_rewritten_to_proxy(self, httpx_mock) -> None:
        import httpx

        from agentsecrets.config import settings

        proxy_url = f"http://localhost:{settings.port}/proxy"
        httpx_mock.add_response(url=proxy_url, method="GET", json={"ok": True})

        with httpx.Client() as client:
            resp = client.get(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": "Bearer AS_SECRET_STRIPE_KEY"},
            )

        req = httpx_mock.get_request()
        assert str(req.url) == proxy_url
        assert req.headers["X-AS-Target-URL"] == "https://api.stripe.com/v1/balance"
        assert req.headers["X-AS-Method"] == "GET"
        assert req.headers["X-AS-Inject-Bearer"] == "STRIPE_KEY"
        assert "Authorization" not in req.headers  # placeholder removed
        assert resp.json() == {"ok": True}

    def test_httpx_sync_header_style_placeholder(self, httpx_mock) -> None:
        import httpx

        from agentsecrets.config import settings

        proxy_url = f"http://localhost:{settings.port}/proxy"
        httpx_mock.add_response(url=proxy_url, method="POST", json={})

        with httpx.Client() as client:
            client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"X-Api-Key": "AS_SECRET_SENDGRID_KEY"},
                json={"subject": "test"},
            )

        req = httpx_mock.get_request()
        assert req.headers["X-AS-Inject-Header-X-Api-Key"] == "SENDGRID_KEY"
        assert "X-Api-Key" not in req.headers

    def test_httpx_sync_non_placeholder_passes_through(self, httpx_mock) -> None:
        import httpx

        target = "https://httpbin.org/get"
        httpx_mock.add_response(url=target, method="GET", json={"ok": True})

        with httpx.Client() as client:
            resp = client.get(target, headers={"X-Trace-Id": "abc123"})

        req = httpx_mock.get_request()
        assert str(req.url) == target  # NOT rewritten to proxy
        assert req.headers["X-Trace-Id"] == "abc123"
        assert "X-AS-Target-URL" not in req.headers
        assert resp.json() == {"ok": True}

    async def test_httpx_async_placeholder_rewritten(self, httpx_mock) -> None:
        import httpx

        from agentsecrets.config import settings

        proxy_url = f"http://localhost:{settings.port}/proxy"
        httpx_mock.add_response(url=proxy_url, method="GET", json={"ok": True})

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": "Bearer AS_SECRET_OPENAI_KEY"},
            )

        req = httpx_mock.get_request()
        assert str(req.url) == proxy_url
        assert req.headers["X-AS-Target-URL"] == "https://api.openai.com/v1/models"
        assert req.headers["X-AS-Inject-Bearer"] == "OPENAI_KEY"
        assert resp.json() == {"ok": True}


class TestInstallInterceptorRequests:
    """requests interception behaviour (optional)."""

    @pytest.fixture(autouse=True)
    def _setup(self, _restore_requests_send):
        """Reinstall the interceptor for each test (requests path)."""
        install_interceptor()

    def test_requests_placeholder_rewritten_to_proxy(self, httpx_mock) -> None:
        requests = pytest.importorskip("requests")
        from agentsecrets.config import settings

        proxy_url = f"http://localhost:{settings.port}/proxy"
        httpx_mock.add_response(url=proxy_url, method="GET", json={"ok": True})

        with requests.Session() as session:
            resp = session.get(
                "https://api.stripe.com/v1/balance",
                headers={"Authorization": "Bearer AS_SECRET_STRIPE_KEY"},
            )

        req = httpx_mock.get_request()
        assert str(req.url) == proxy_url
        assert req.headers["X-AS-Target-URL"] == "https://api.stripe.com/v1/balance"
        assert req.headers["X-AS-Inject-Bearer"] == "STRIPE_KEY"
        assert resp.json() == {"ok": True}

    def test_requests_non_placeholder_passes_through(self, httpx_mock) -> None:
        requests = pytest.importorskip("requests")
        target = "https://httpbin.org/status/200"
        httpx_mock.add_response(url=target, method="GET", status_code=200)

        with requests.Session() as session:
            resp = session.get(target)

        req = httpx_mock.get_request()
        assert str(req.url) == target
        assert "X-AS-Target-URL" not in req.headers
        assert resp.status_code == 200
