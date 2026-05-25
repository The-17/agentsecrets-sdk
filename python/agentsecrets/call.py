"""HTTP call translation — the core of the SDK.

Translates ``call()`` parameters into ``X-AS-*`` proxy headers, sends
the request to the local proxy, and maps the response back into an
``AgentSecretsResponse``.

The header mapping mirrors ``parseInjections`` in the Go proxy server
(``pkg/proxy/server.go``).  See the proxy spec for the full mapping table.
"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import (
    AgentSecretsError,
    DomainNotAllowed,
    SecretNotFound,
    UpstreamError,
)
from .models import AgentSecretsResponse

# ---------------------------------------------------------------------------
# Header building — one function, no duplication
# ---------------------------------------------------------------------------

def _build_proxy_headers(
    url: str,
    *,
    method: str = "GET",
    bearer: str | None = None,
    basic: str | None = None,
    header: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    body_field: dict[str, str] | None = None,
    form_field: dict[str, str] | None = None,
    agent_id: str | None = None,
) -> dict[str, str]:
    """Convert call parameters into ``X-AS-*`` proxy headers."""
    headers: dict[str, str] = {
        "X-AS-Target-URL": url,
        "X-AS-Method": method.upper(),
    }

    if bearer:
        headers["X-AS-Inject-Bearer"] = bearer
    if basic:
        headers["X-AS-Inject-Basic"] = basic
    if header:
        for name, secret_key in header.items():
            headers[f"X-AS-Inject-Header-{name}"] = secret_key
    if query:
        for param, secret_key in query.items():
            headers[f"X-AS-Inject-Query-{param}"] = secret_key
    if body_field:
        for path, secret_key in body_field.items():
            headers[f"X-AS-Inject-Body-{path}"] = secret_key
    if form_field:
        for key, secret_key in form_field.items():
            headers[f"X-AS-Inject-Form-{key}"] = secret_key
    if agent_id:
        headers["X-AS-Agent-ID"] = agent_id

    return headers


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------

def _map_proxy_error(status_code: int, body: bytes, url: str) -> AgentSecretsError:
    """Map a proxy error response to the appropriate SDK exception.

    The Go proxy (server.go) uses these status codes:
    - 400  Bad request (missing headers)
    - 403  Domain not on allowlist  (returned by engine.logBlocked)
    - 502  ALL engine errors — including secret not found — wrapped by server.go line 115

    For 502s, we inspect the error message body to distinguish between
    "secret not found in keychain" and a real upstream failure.
    """
    text = body.decode("utf-8", errors="replace")

    # Try to extract the JSON error message.
    error_msg = text
    try:
        import json
        data = json.loads(text)
        error_msg = data.get("error", data.get("message", text))
    except (ValueError, TypeError):
        pass

    if status_code == 403:
        # Domain not in allowlist — returned by engine.logBlocked (engine.go:149).
        # The JSON body has {"error":"domain_not_in_allowlist","domain":"...","message":"..."}
        try:
            import json
            data = json.loads(text)
            domain = data.get("domain", error_msg)
        except (ValueError, TypeError):
            domain = error_msg
        return DomainNotAllowed(domain=domain)

    if status_code == 502:
        # The proxy wraps ALL engine errors as 502 (server.go:115).
        # Detect the "secret not found" case by matching the error message
        # format from engine.go:202:
        #   "secret 'KEY' not found in keychain — ..."
        lower = error_msg.lower()
        if "not found in keychain" in lower or "secret '" in lower and "not found" in lower:
            # Extract the key name from the message if possible.
            import re
            match = re.search(r"secret '([^']+)'", error_msg)
            key = match.group(1) if match else error_msg
            return SecretNotFound(key=key)

        return UpstreamError(status_code=status_code, body=text, url=url)

    return AgentSecretsError(f"Proxy error {status_code}: {error_msg}")


# ---------------------------------------------------------------------------
# Response builder
# ---------------------------------------------------------------------------

def _to_response(resp: httpx.Response, duration_ms: int) -> AgentSecretsResponse:
    """Convert an httpx response into an ``AgentSecretsResponse``."""
    flat_headers = {k: v for k, v in resp.headers.items()}
    return AgentSecretsResponse(
        status_code=resp.status_code,
        headers=flat_headers,
        body=resp.content,
        redacted="[REDACTED_BY_AGENTSECRETS]" in resp.text,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Public API — sync
# ---------------------------------------------------------------------------

def call(
    port: int,
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    headers: dict[str, str] | None = None,
    bearer: str | None = None,
    basic: str | None = None,
    header: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    body_field: dict[str, str] | None = None,
    form_field: dict[str, str] | None = None,
    agent_id: str | None = None,
    timeout: float = 30.0,
) -> AgentSecretsResponse:
    """Make an authenticated API call through the proxy (synchronous).

    Parameters
    ----------
    port:
        Proxy port.
    url:
        Target upstream URL.
    method:
        HTTP method (GET, POST, PUT, PATCH, DELETE).
    body:
        Request body — dict (JSON-encoded) or bytes.
    headers:
        Extra (non-auth) headers to forward.
    bearer / basic / header / query / body_field / form_field:
        Credential injection parameters.  Values are secret **key names**,
        not secret values.
    agent_id:
        Optional agent identifier for audit logging.
    timeout:
        HTTP timeout in seconds.

    Returns
    -------
    AgentSecretsResponse
    """
    proxy_headers = _build_proxy_headers(
        url,
        method=method,
        bearer=bearer,
        basic=basic,
        header=header,
        query=query,
        body_field=body_field,
        form_field=form_field,
        agent_id=agent_id,
    )
    if headers:
        proxy_headers.update(headers)

    # Encode body.
    content: bytes | None = None
    if body is not None:
        if isinstance(body, bytes):
            content = body
        else:
            import json
            content = json.dumps(body).encode("utf-8")
            proxy_headers.setdefault("Content-Type", "application/json")

    proxy_url = f"http://localhost:{port}/proxy"

    import time
    start = time.monotonic()
    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            method.upper(),
            proxy_url,
            headers=proxy_headers,
            content=content,
        )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if resp.status_code >= 400:
        raise _map_proxy_error(resp.status_code, resp.content, url)

    return _to_response(resp, elapsed_ms)


# ---------------------------------------------------------------------------
# Public API — async
# ---------------------------------------------------------------------------

async def async_call(
    port: int,
    url: str,
    *,
    method: str = "GET",
    body: Any = None,
    headers: dict[str, str] | None = None,
    bearer: str | None = None,
    basic: str | None = None,
    header: dict[str, str] | None = None,
    query: dict[str, str] | None = None,
    body_field: dict[str, str] | None = None,
    form_field: dict[str, str] | None = None,
    agent_id: str | None = None,
    timeout: float = 30.0,
) -> AgentSecretsResponse:
    """Make an authenticated API call through the proxy (asynchronous).

    Same parameters as :func:`call`.
    """
    proxy_headers = _build_proxy_headers(
        url,
        method=method,
        bearer=bearer,
        basic=basic,
        header=header,
        query=query,
        body_field=body_field,
        form_field=form_field,
        agent_id=agent_id,
    )
    if headers:
        proxy_headers.update(headers)

    content: bytes | None = None
    if body is not None:
        if isinstance(body, bytes):
            content = body
        else:
            import json
            content = json.dumps(body).encode("utf-8")
            proxy_headers.setdefault("Content-Type", "application/json")

    proxy_url = f"http://localhost:{port}/proxy"

    import time
    start = time.monotonic()
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.request(
            method.upper(),
            proxy_url,
            headers=proxy_headers,
            content=content,
        )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if resp.status_code >= 400:
        raise _map_proxy_error(resp.status_code, resp.content, url)

    return _to_response(resp, elapsed_ms)
