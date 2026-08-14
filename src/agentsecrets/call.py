"""Call translation — supports both local binary delegation and cloud API modes.

In local mode (default), ``call()`` delegates to ``agentsecrets call`` exactly the way
:mod:`agentsecrets.spawn` delegates to ``agentsecrets env``.  The binary is
the one authorized process: it owns the session token, reuses a running
proxy or spins up a transient one for the request (``CallViaProxy`` in
``pkg/proxy/client.go``), handles approval prompts, and injects the real
secret values.  The SDK only ever passes secret **key names** as CLI flags
and parses the result — it never sees a credential value.

In cloud mode, the SDK communicates directly with the AgentSecrets cloud API
to perform authenticated calls, eliminating the need for a local binary.

Forward-compatibility: today ``agentsecrets call`` prints ``HTTP <code>`` and
the body as plain text (no response headers).  When the binary grows a
``--output json`` flag, :func:`_binary_supports_json_call` detects it and this
module upgrades to the structured path automatically — no SDK change needed.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import time
import warnings
from functools import lru_cache
from typing import Any

import httpx

from .errors import (
    CLIError,
    DomainNotAllowed,
    SecretNotFound,
    UpstreamError,
)
from .models import AgentSecretsResponse
from .proxy import find_binary
from .config import settings

# ---------------------------------------------------------------------------
# Argv construction — SDK params -> `agentsecrets call` flags
# ---------------------------------------------------------------------------


def _build_call_args(
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
    agent_token: str | None = None,
    output_json: bool = False,
) -> list[str]:
    """Translate call parameters into ``agentsecrets call`` CLI arguments.

    Values passed for ``bearer`` / ``basic`` / ``header`` / ``query`` /
    ``body_field`` / ``form_field`` are secret **key names**, not secret
    values — the binary resolves them from the keychain.

    When ``output_json`` is true, ``--output json`` is appended so the binary
    emits the structured envelope (real response headers, authoritative
    ``redacted`` flag, ``duration_ms``, and a structured ``error``).
    """
    args: list[str] = ["call", "--url", url, "--method", method.upper()]

    if body is not None:
        if isinstance(body, bytes):
            body_str = body.decode("utf-8", errors="replace")
        elif isinstance(body, str):
            body_str = body
        else:
            body_str = json.dumps(body)
        args += ["--body", body_str]

    if bearer:
        args += ["--bearer", bearer]
    if basic:
        args += ["--basic", basic]
    if header:
        for name, secret_key in header.items():
            args += ["--header", f"{name}={secret_key}"]
    if query:
        for param, secret_key in query.items():
            args += ["--query", f"{param}={secret_key}"]
    if body_field:
        for path, secret_key in body_field.items():
            args += ["--body-field", f"{path}={secret_key}"]
    if form_field:
        for field_name, secret_key in form_field.items():
            args += ["--form-field", f"{field_name}={secret_key}"]
    if agent_token:
        args += ["--token", agent_token]

    if output_json:
        args += ["--output", "json"]

    # `headers` (arbitrary forward headers) and `agent_id` have no equivalent
    # flag on today's binary. They are accepted for API stability and restored
    # once the binary exposes them (see module docstring). Warn once so callers
    # relying on them are not silently surprised.
    if headers:
        warnings.warn(
            "Forward headers (headers=...) are not yet supported by the "
            "'agentsecrets call' binary and will be ignored. This will be "
            "restored when the binary adds header forwarding.",
            stacklevel=3,
        )

    return args


# ---------------------------------------------------------------------------
# Binary capability probe — enables the future JSON path with zero SDK change
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _binary_supports_json_call() -> bool:
    """Return ``True`` if ``agentsecrets call`` accepts ``--output`` (JSON mode).

    Probes ``agentsecrets call --help`` once per process.  Today's binary has
    no such flag, so this returns ``False`` and the text parser is used.  When
    the binary gains ``--output json`` this flips to ``True`` automatically.
    """
    try:
        binary = find_binary()
        result = subprocess.run(
            [binary, "call", "--help"],
            capture_output=True,
            text=True,
            timeout=10.0,
        )  # noqa: S603
    except Exception:
        return False
    return "--output" in (result.stdout or "")


# ---------------------------------------------------------------------------
# Output parsing
# ---------------------------------------------------------------------------

# The binary prints "HTTP <code>\n\n<body>" on success (pkg .../commands/call.go).
_HTTP_LINE = re.compile(r"^HTTP\s+(\d+)\s*$", re.MULTILINE)


def _parse_call_stdout(stdout: str, duration_ms: int) -> AgentSecretsResponse:
    """Parse the binary's ``HTTP <code>\\n\\n<body>`` stdout into a response."""
    status_code = 0
    body_text = stdout

    match = _HTTP_LINE.search(stdout)
    if match:
        status_code = int(match.group(1))
        # Body is everything after the blank line that follows the status line.
        rest = stdout[match.end():]
        body_text = rest[2:] if rest.startswith("\n\n") else rest.lstrip("\n")

    return AgentSecretsResponse(
        status_code=status_code,
        headers={},  # binary does not emit response headers in text mode
        body=body_text.encode("utf-8"),
        redacted="[REDACTED_BY_AGENTSECRETS]" in body_text,
        duration_ms=duration_ms,
    )


def _map_call_error(stderr: str, exit_code: int, url: str) -> Exception:
    """Map a failed ``agentsecrets call`` invocation to an SDK exception.

    The binary prints the proxy's error message to stderr on failure.  We
    match the same message shapes the proxy produces (mirrors the former
    ``_map_proxy_error`` HTTP-status logic, now keyed off text):

    * domain-not-allowlisted  -> :class:`DomainNotAllowed`
    * secret-not-found        -> :class:`SecretNotFound`
    * anything else           -> :class:`UpstreamError` / :class:`CLIError`
    """
    text = (stderr or "").strip()
    lower = text.lower()

    if (
        "domain_not_in_allowlist" in lower
        or "empty_allowlist" in lower
        or "workspace allowlist" in lower
    ):
        domain_match = re.search(r"'([^']+)'", text)
        domain = domain_match.group(1) if domain_match else url
        return DomainNotAllowed(domain=domain)

    if "not found in keychain" in lower or ("secret '" in lower and "not found" in lower):
        key_match = re.search(r"secret '([^']+)'", text)
        key = key_match.group(1) if key_match else text
        return SecretNotFound(key=key)

    if "upstream" in lower:
        return UpstreamError(status_code=502, body=text, url=url)

    return CLIError("call", exit_code, text)


# ---------------------------------------------------------------------------
# JSON output parsing (`agentsecrets call --output json`)
# ---------------------------------------------------------------------------
#
# The binary's structured envelope is:
#
#     {"status": int, "headers": {name: [values...]}, "body": str,
#      "redacted": bool, "duration_ms": int, "error": str (omitted on success)}
#
# Header/body values are already redacted by the proxy engine, so every field
# is safe to surface. On any failure the binary still prints the full envelope
# to stdout (with a populated "error") and exits non-zero — so the JSON path
# reads stdout regardless of exit code and classifies off the envelope, falling
# back to stderr only when the binary died before emitting a parseable one.


def _flatten_headers(raw: Any) -> dict[str, str]:
    """Collapse the binary's ``{name: [values...]}`` headers to ``{name: value}``.

    Multi-valued headers are joined with ``", "`` (the conventional HTTP
    representation).  Non-list values pass through as strings.
    """
    if not isinstance(raw, dict):
        return {}
    flat: dict[str, str] = {}
    for name, value in raw.items():
        if isinstance(value, list):
            flat[str(name)] = ", ".join(str(v) for v in value)
        else:
            flat[str(name)] = str(value)
    return flat


def _envelope_body_str(envelope: dict[str, Any]) -> str:
    body = envelope.get("body")
    if isinstance(body, str):
        return body
    if body is None:
        return ""
    return str(body)


def _parse_call_json_envelope(
    envelope: dict[str, Any], fallback_duration_ms: int
) -> AgentSecretsResponse:
    """Build a response from a successful ``--output json`` envelope."""
    status = envelope.get("status")
    status_code = int(status) if isinstance(status, (int, float)) else 0

    duration = envelope.get("duration_ms")
    duration_ms = (
        int(duration) if isinstance(duration, (int, float)) else fallback_duration_ms
    )

    body_text = _envelope_body_str(envelope)

    return AgentSecretsResponse(
        status_code=status_code,
        headers=_flatten_headers(envelope.get("headers")),
        body=body_text.encode("utf-8"),
        redacted=bool(envelope.get("redacted", False)),
        duration_ms=duration_ms,
    )


# Structured error slugs the proxy engine emits in the response body's "error"
# field for allowlist rejections — both map to the actionable DomainNotAllowed.
_ALLOWLIST_ERROR_TOKENS = frozenset({"domain_not_in_allowlist", "empty_allowlist"})


def _map_call_json_error(envelope: dict[str, Any], url: str) -> Exception:
    """Map a failed ``--output json`` envelope to an SDK exception.

    Classification keys off the *structured* proxy error rather than fuzzy
    message matching: the response body carries ``{"error": <slug>, "domain":
    <domain>, "message": <text>}`` for proxy blocks, so an allowlist rejection
    is identified by its ``domain_not_in_allowlist`` slug and the real domain
    field (fixing the former misclassification), not by scraping prose.
    """
    top_error = str(envelope.get("error") or "").strip()
    status = envelope.get("status")
    status_code = int(status) if isinstance(status, (int, float)) else 0
    body_str = _envelope_body_str(envelope)

    token = ""
    domain_field = ""
    structured_msg = ""
    try:
        parsed = json.loads(body_str) if body_str else None
    except (json.JSONDecodeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        token = str(parsed.get("error") or "")
        domain_field = str(parsed.get("domain") or "")
        structured_msg = str(parsed.get("message") or "")

    haystack = f"{token} {top_error} {structured_msg}".lower()

    # Allowlist rejection — keyed off the structured slug (authoritative) with a
    # prose fallback, and the real domain from the structured field.
    if (
        token in _ALLOWLIST_ERROR_TOKENS
        or "domain_not_in_allowlist" in haystack
        or "workspace allowlist" in haystack
    ):
        if domain_field:
            domain = domain_field
        else:
            quoted = re.search(r"'([^']+)'", top_error) or re.search(
                r"'([^']+)'", structured_msg
            )
            domain = quoted.group(1) if quoted else url
        return DomainNotAllowed(domain=domain)

    # Missing secret.
    if "not found in keychain" in haystack or (
        "secret '" in haystack and "not found" in haystack
    ):
        key_match = (
            re.search(r"secret '([^']+)'", token)
            or re.search(r"secret '([^']+)'", top_error)
            or re.search(r"secret '([^']+)'", structured_msg)
        )
        key = key_match.group(1) if key_match else (top_error or url)
        return SecretNotFound(key=key)

    # A real HTTP status came back (a genuine upstream error, or a proxy policy
    # block other than allowlist/secret) — surface it with full context.
    if status_code >= 400:
        return UpstreamError(status_code=status_code, body=body_str, url=url)

    # No HTTP status (status 0): the call never reached an upstream response —
    # e.g. the transient proxy failed to start. Mirror text mode's fallback.
    return CLIError("call", 1, top_error or token or "call failed")


def _dispatch_json_result(
    stdout: str,
    stderr: str,
    returncode: int,
    url: str,
    duration_ms: int,
) -> AgentSecretsResponse:
    """Route a ``--output json`` invocation to a response or an exception.

    The binary prints the envelope on stdout even on failure, so this reads
    stdout first. If stdout is not a parseable envelope (the binary died before
    emitting one — a panic, a pre-run gate, etc.), it falls back to the text
    stderr mapper so the caller still gets a meaningful exception.
    """
    try:
        envelope = json.loads(stdout.strip()) if stdout.strip() else None
    except (json.JSONDecodeError, ValueError):
        envelope = None

    if not isinstance(envelope, dict):
        if returncode != 0:
            raise _map_call_error(stderr or stdout or "", returncode or 1, url)
        raise CLIError("call", returncode or 1, stderr or stdout or "empty JSON output")

    top_error = str(envelope.get("error") or "").strip()
    status = envelope.get("status")
    status_code = int(status) if isinstance(status, (int, float)) else 0

    if returncode != 0 or top_error or status_code >= 400:
        raise _map_call_json_error(envelope, url)

    return _parse_call_json_envelope(envelope, duration_ms)


# ---------------------------------------------------------------------------
# Public API — sync
# ---------------------------------------------------------------------------


def call(
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
    agent_token: str | None = None,
    timeout: float = 30.0,
) -> AgentSecretsResponse:
    """Make an authenticated API call.

    In local mode (default), delegates to ``agentsecrets call`` binary.
    In cloud mode, communicates directly with the AgentSecrets cloud API.

    Parameters
    ----------
    url:
        Target upstream URL.
    method:
        HTTP method (GET, POST, PUT, PATCH, DELETE).
    body:
        Request body — dict (JSON-encoded), str, or bytes.
    headers:
        Extra (non-auth) forward headers.  **Not yet supported** by the binary;
        ignored with a warning until header forwarding lands (see module docs).
    bearer / basic / header / query / body_field / form_field:
        Credential injection parameters.  Values are secret **key names**,
        never secret values.
    agent_id:
        Informational agent identifier.  The delegated binary identifies the
        agent by ``agent_token`` (``--token``); ``agent_id`` is currently
        unused on this path.
    agent_token:
        Agent token, passed as ``--token``.
    timeout:
        Maximum seconds to wait for the binary (local mode) or API request (cloud mode).

    Returns
    -------
    AgentSecretsResponse

    Notes
    -----
    In local mode, the proxy port and session token are handled entirely inside the binary,
    which reuses a running proxy or starts a transient one for this call.
    In cloud mode, authentication is handled via the AgentSecrets cloud API.
    """
    # Check if we're in cloud mode
    if getattr(settings, 'mode', 'local') == 'cloud':
        return _call_via_cloud_api(
            url,
            method=method,
            body=body,
            headers=headers,
            bearer=bearer,
            basic=basic,
            header=header,
            query=query,
            body_field=body_field,
            form_field=form_field,
            agent_id=agent_id,
            agent_token=agent_token,
            timeout=timeout,
        )

    # Local mode: delegate to binary (existing behavior)
    if getattr(settings, 'mode', 'local') != 'cloud':
        binary = find_binary()
        use_json = _binary_supports_json_call()
        args = _build_call_args(
            url,
            method=method,
            body=body,
            headers=headers,
            bearer=bearer,
            basic=basic,
            header=header,
            query=query,
            body_field=body_field,
            form_field=form_field,
            agent_id=agent_id,
            agent_token=agent_token,
            output_json=use_json,
        )

        start = time.monotonic()
        try:
            result = subprocess.run(
                [binary, *args],
                capture_output=True,
                text=True,
                timeout=timeout,
            )  # noqa: S603
        except subprocess.TimeoutExpired:
            raise CLIError("call", -1, "Command timed out")
        duration_ms = int((time.monotonic() - start) * 1000)

        if use_json:
            return _dispatch_json_result(
                result.stdout or "",
                result.stderr or "",
                result.returncode,
                url,
                duration_ms,
            )

        if result.returncode != 0:
            raise _map_call_error(result.stderr or "", result.returncode, url)

        return _parse_call_stdout(result.stdout or "", duration_ms)

    # Cloud mode: delegate to cloud API
    return _call_via_cloud_api(
        url,
        method=method,
        body=body,
        headers=headers,
        bearer=bearer,
        basic=basic,
        header=header,
        query=query,
        body_field=body_field,
        form_field=form_field,
        agent_id=agent_id,
        agent_token=agent_token,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Public API — async
# ---------------------------------------------------------------------------


async def async_call(
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
    agent_token: str | None = None,
    timeout: float = 30.0,
) -> AgentSecretsResponse:
    """Async variant of :func:`call` (same parameters and semantics)."""
    # Check if we're in cloud mode
    if getattr(settings, 'mode', 'local') == 'cloud':
        return await _async_call_via_cloud_api(
            url,
            method=method,
            body=body,
            headers=headers,
            bearer=bearer,
            basic=basic,
            header=header,
            query=query,
            body_field=body_field,
            form_field=form_field,
            agent_id=agent_id,
            agent_token=agent_token,
            timeout=timeout,
        )

    # Local mode: delegate to binary (existing behavior)
    binary = find_binary()
    use_json = _binary_supports_json_call()
    args = _build_call_args(
        url,
        method=method,
        body=body,
        headers=headers,
        bearer=bearer,
        basic=basic,
        header=header,
        query=query,
        body_field=body_field,
        form_field=form_field,
        agent_id=agent_id,
        agent_token=agent_token,
        output_json=use_json,
    )

    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        binary,
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise CLIError("call", -1, "Command timed out")
    duration_ms = int((time.monotonic() - start) * 1000)

    stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
    stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")

    if use_json:
        return _dispatch_json_result(
            stdout, stderr, proc.returncode or 0, url, duration_ms
        )

    if proc.returncode != 0:
        raise _map_call_error(stderr, proc.returncode or 1, url)

    return _parse_call_stdout(stdout, duration_ms)


def _call_via_cloud_api(
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
    agent_token: str | None = None,
    timeout: float = 30.0,
) -> AgentSecretsResponse:
    """Make an authenticated API call via the cloud API.

    Communicates directly with the AgentSecrets cloud API to perform
    authenticated calls, eliminating the need for a local binary.
    """
    import os

    # Determine cloud API base URL
    base_url = os.environ.get("AGENTSECRETS_API_URL", "https://secrets-api-orpin.vercel.app/api")

    # Prepare request payload
    payload: dict[str, Any] = {}
    if body is not None:
        if isinstance(body, bytes):
            payload["body"] = body.decode("utf-8", errors="replace")
        elif isinstance(body, str):
            payload["body"] = body
        else:
            payload["body"] = json.dumps(body)

    if headers:
        payload["headers"] = headers
    if bearer:
        payload["bearer"] = bearer
    if basic:
        payload["basic"] = basic
    if header:
        payload["header"] = header
    if query:
        payload["query"] = query
    if body_field:
        payload["body_field"] = body_field
    if form_field:
        payload["form_field"] = form_field
    if agent_id:
        payload["agent_id"] = agent_id
    if agent_token:
        payload["agent_token"] = agent_token

    payload["method"] = method.upper()
    payload["url"] = url

    # Get authentication token
    token = agent_token or os.environ.get("AS_AGENT_TOKEN")
    auth_headers = {}
    if token:
        auth_headers["Authorization"] = f"Bearer {token}"

    # Make request to cloud API
    import httpx

    try:
        response = httpx.post(
            f"{base_url}/v1/call",
            json=payload,
            headers={
                "Content-Type": "application/json",
                **auth_headers
            },
            timeout=timeout
        )

        # Parse JSON response envelope (same format as binary --output json)
        if response.headers.get("content-type", "").startswith("application/json"):
            envelope = response.json()
            return _parse_call_json_envelope(envelope, 0)  # duration from envelope
        else:
            # Fallback for non-JSON responses
            text = response.text
            return _parse_call_stdout(text, 0)

    except httpx.TimeoutException:
        raise CLIError("call", -1, "Command timed out")
    except httpx.RequestError as e:
        raise CLIError("call", -1, f"Cloud API request failed: {str(e)}")
    except (json.JSONDecodeError, ValueError) as e:
        raise CLIError("call", -1, f"Invalid response from cloud API: {str(e)}")


async def _async_call_via_cloud_api(
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
    agent_token: str | None = None,
    timeout: float = 30.0,
) -> AgentSecretsResponse:
    """Make an authenticated API call via the cloud API (async variant).

    Communicates directly with the AgentSecrets cloud API to perform
    authenticated calls, eliminating the need for a local binary.
    """
    import os

    # Determine cloud API base URL
    base_url = os.environ.get("AGENTSECRETS_API_URL", "https://secrets-api-orpin.vercel.app/api")

    # Prepare request payload
    payload: dict[str, Any] = {}
    if body is not None:
        if isinstance(body, bytes):
            payload["body"] = body.decode("utf-8", errors="replace")
        elif isinstance(body, str):
            payload["body"] = body
        else:
            payload["body"] = json.dumps(body)

    if headers:
        payload["headers"] = headers
    if bearer:
        payload["bearer"] = bearer
    if basic:
        payload["basic"] = basic
    if header:
        payload["header"] = header
    if query:
        payload["query"] = query
    if body_field:
        payload["body_field"] = body_field
    if form_field:
        payload["form_field"] = form_field
    if agent_id:
        payload["agent_id"] = agent_id
    if agent_token:
        payload["agent_token"] = agent_token

    payload["method"] = method.upper()
    payload["url"] = url

    # Get authentication token
    token = agent_token or os.environ.get("AS_AGENT_TOKEN")
    auth_headers = {}
    if token:
        auth_headers["Authorization"] = f"Bearer {token}"

    # Make request to cloud API
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.post(
                f"{base_url}/v1/call",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    **auth_headers
                }
            )

            # Parse JSON response envelope (same format as binary --output json)
            if response.headers.get("content-type", "").startswith("application/json"):
                envelope = response.json()
                return _parse_call_json_envelope(envelope, 0)  # duration from envelope
            else:
                # Fallback for non-JSON responses
                text = response.text
                return _parse_call_stdout(text, 0)

        except httpx.TimeoutException:
            raise CLIError("call", -1, "Command timed out")
        except httpx.RequestError as e:
            raise CLIError("call", -1, f"Cloud API request failed: {str(e)}")
        except (json.JSONDecodeError, ValueError) as e:
            raise CLIError("call", -1, f"Invalid response from cloud API: {str(e)}")
