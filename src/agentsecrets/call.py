"""Call translation — the core of the SDK.

The SDK does **not** talk to the proxy over HTTP.  The local proxy is
guarded by a pre-shared session token that the ``agentsecrets`` binary
generates and stores in the OS keychain; that token is the *binary's* own
loopback credential, and the keychain daemon only releases it to the real
binary (it verifies the caller's binary hash).  A separate Python process
cannot — and should not — read it.

So ``call()`` delegates to ``agentsecrets call`` exactly the way
:mod:`agentsecrets.spawn` delegates to ``agentsecrets env``.  The binary is
the one authorized process: it owns the session token, reuses a running
proxy or spins up a transient one for the request (``CallViaProxy`` in
``pkg/proxy/client.go``), handles approval prompts, and injects the real
secret values.  The SDK only ever passes secret **key names** as CLI flags
and parses the result — it never sees a credential value.

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

from .errors import (
    CLIError,
    DomainNotAllowed,
    SecretNotFound,
    UpstreamError,
)
from .models import AgentSecretsResponse
from .proxy import find_binary

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
) -> list[str]:
    """Translate call parameters into ``agentsecrets call`` CLI arguments.

    Values passed for ``bearer`` / ``basic`` / ``header`` / ``query`` /
    ``body_field`` / ``form_field`` are secret **key names**, not secret
    values — the binary resolves them from the keychain.
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

    if "domain_not_in_allowlist" in lower or "not in the workspace allowlist" in lower:
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
    """Make an authenticated API call by delegating to ``agentsecrets call``.

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
        Maximum seconds to wait for the binary.

    Returns
    -------
    AgentSecretsResponse

    Notes
    -----
    The proxy port and session token are handled entirely inside the binary,
    which reuses a running proxy or starts a transient one for this call.
    """
    binary = find_binary()
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

    if result.returncode != 0:
        raise _map_call_error(result.stderr or "", result.returncode, url)

    return _parse_call_stdout(result.stdout or "", duration_ms)


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
    binary = find_binary()
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

    if proc.returncode != 0:
        raise _map_call_error(stderr, proc.returncode or 1, url)

    return _parse_call_stdout(stdout, duration_ms)
