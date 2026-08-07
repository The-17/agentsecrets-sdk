"""Regression tests for the real ``call()`` / ``async_call()`` HTTP round-trip.

Unlike ``test_call.py`` (which only covers ``_build_proxy_headers`` and
``_map_proxy_error`` in isolation), these tests drive the full network path
through ``pytest-httpx`` so the wire contract with the local proxy is locked
down before any refactor:

* request goes to ``http://localhost:{port}/proxy``
* the HTTP method mirrors the *target* method (GET call -> GET to proxy)
* dict bodies are JSON-encoded and ``Content-Type`` is set; bytes pass through
* the session token is attached as ``X-AS-Session-Token`` when present
* ``AgentSecretsResponse`` is built faithfully (status/headers/body/redacted)
* proxy error statuses raise the mapped SDK exceptions

The session token reader is patched to ``None`` by default so assertions do
not depend on the developer's real ``~/.agentsecrets/keyring.json``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from agentsecrets import call as call_mod
from agentsecrets.call import async_call, call
from agentsecrets.errors import DomainNotAllowed, SecretNotFound, UpstreamError
from agentsecrets.models import AgentSecretsResponse

PORT = 8765
PROXY_URL = f"http://localhost:{PORT}/proxy"
TARGET = "https://api.stripe.com/v1/balance"


@pytest.fixture(autouse=True)
def _no_session_token():
    """Default every test to *no* session token for deterministic headers."""
    with patch.object(call_mod, "_get_session_token", return_value=None):
        yield


class TestCallHTTP:
    """Synchronous ``call()`` wire behaviour."""

    def test_posts_to_proxy_url_with_target_headers(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="GET", json={"ok": True})

        resp = call(PORT, TARGET, bearer="STRIPE_KEY")

        req = httpx_mock.get_request()
        assert req is not None
        assert str(req.url) == PROXY_URL
        assert req.method == "GET"
        assert req.headers["X-AS-Target-URL"] == TARGET
        assert req.headers["X-AS-Method"] == "GET"
        assert req.headers["X-AS-Inject-Bearer"] == "STRIPE_KEY"
        assert isinstance(resp, AgentSecretsResponse)
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_method_mirrors_target_method(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="POST", json={})

        call(PORT, TARGET, method="post", bearer="K")

        req = httpx_mock.get_request()
        assert req.method == "POST"
        assert req.headers["X-AS-Method"] == "POST"

    def test_dict_body_is_json_encoded(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="POST", json={})

        call(PORT, TARGET, method="POST", body={"amount": 1000, "currency": "usd"})

        req = httpx_mock.get_request()
        assert json.loads(req.content) == {"amount": 1000, "currency": "usd"}
        assert req.headers["content-type"] == "application/json"

    def test_bytes_body_passes_through_untouched(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="POST", json={})

        call(PORT, TARGET, method="POST", body=b"raw-payload")

        req = httpx_mock.get_request()
        assert req.content == b"raw-payload"
        # We do not force a Content-Type for raw bytes.
        assert "content-type" not in req.headers

    def test_extra_headers_are_forwarded(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="GET", json={})

        call(PORT, TARGET, headers={"X-Trace-Id": "abc123"})

        req = httpx_mock.get_request()
        assert req.headers["X-Trace-Id"] == "abc123"

    def test_session_token_attached_when_present(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="GET", json={})

        with patch.object(call_mod, "_get_session_token", return_value="sess-xyz"):
            call(PORT, TARGET, bearer="K")

        req = httpx_mock.get_request()
        assert req.headers["X-AS-Session-Token"] == "sess-xyz"

    def test_session_token_absent_when_none(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="GET", json={})

        call(PORT, TARGET, bearer="K")

        req = httpx_mock.get_request()
        assert "X-AS-Session-Token" not in req.headers

    def test_response_fields_are_populated(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=PROXY_URL,
            method="GET",
            status_code=201,
            headers={"X-Upstream": "yes"},
            content=b'{"created": true}',
        )

        resp = call(PORT, TARGET, bearer="K")

        assert resp.status_code == 201
        # NOTE: response.headers is a plain dict built from httpx's .items(),
        # which lowercases header names. It is NOT case-insensitive like
        # httpx.Headers — response.headers["X-Upstream"] would KeyError.
        # (Flagged for Phase 4: consider a case-insensitive mapping.)
        assert resp.headers["x-upstream"] == "yes"
        assert resp.body == b'{"created": true}'
        assert resp.text == '{"created": true}'
        assert resp.redacted is False
        assert resp.duration_ms >= 0

    def test_redacted_flag_set_when_marker_present(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=PROXY_URL,
            method="GET",
            content=b"key is [REDACTED_BY_AGENTSECRETS] here",
        )

        resp = call(PORT, TARGET, bearer="K")

        assert resp.redacted is True

    def test_403_raises_domain_not_allowed(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=PROXY_URL,
            method="GET",
            status_code=403,
            json={"error": "domain_not_in_allowlist", "domain": "api.stripe.com"},
        )

        with pytest.raises(DomainNotAllowed) as excinfo:
            call(PORT, TARGET, bearer="K")
        assert excinfo.value.domain == "api.stripe.com"

    def test_502_secret_not_found_raises_secret_not_found(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=PROXY_URL,
            method="GET",
            status_code=502,
            json={"error": "secret 'STRIPE_KEY' not found in keychain — run set"},
        )

        with pytest.raises(SecretNotFound) as excinfo:
            call(PORT, TARGET, bearer="STRIPE_KEY")
        assert excinfo.value.key == "STRIPE_KEY"

    def test_502_generic_raises_upstream_error(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=PROXY_URL,
            method="GET",
            status_code=502,
            json={"error": "upstream connection refused"},
        )

        with pytest.raises(UpstreamError) as excinfo:
            call(PORT, TARGET, bearer="K")
        assert excinfo.value.status_code == 502


class TestAsyncCallHTTP:
    """``async_call()`` mirrors the sync path (asyncio_mode = auto)."""

    async def test_async_round_trip(self, httpx_mock) -> None:
        httpx_mock.add_response(url=PROXY_URL, method="GET", json={"ok": True})

        resp = await async_call(PORT, TARGET, bearer="OPENAI_KEY")

        req = httpx_mock.get_request()
        assert str(req.url) == PROXY_URL
        assert req.headers["X-AS-Inject-Bearer"] == "OPENAI_KEY"
        assert resp.json() == {"ok": True}

    async def test_async_502_secret_not_found(self, httpx_mock) -> None:
        httpx_mock.add_response(
            url=PROXY_URL,
            method="GET",
            status_code=502,
            json={"error": "secret 'OPENAI_KEY' not found in keychain"},
        )

        with pytest.raises(SecretNotFound) as excinfo:
            await async_call(PORT, TARGET, bearer="OPENAI_KEY")
        assert excinfo.value.key == "OPENAI_KEY"
