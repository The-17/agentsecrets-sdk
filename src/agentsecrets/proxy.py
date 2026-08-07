"""Proxy lifecycle management — health checks and auto-start.

This module handles the low-level interaction with the proxy server:
discovering whether it's running, starting it if needed, and waiting
for it to become ready.
"""

from __future__ import annotations

import shutil
import subprocess
import time

import httpx

from .errors import AgentSecretsNotRunning, CLINotFound, ProxyConnectionError
from .models import ProxyStatus

DEFAULT_PORT = 8765
_HEALTH_PATH = "/health"


def health_check(port: int = DEFAULT_PORT) -> ProxyStatus:
    """Probe the proxy health endpoint.

    Returns a ``ProxyStatus`` on success or raises ``ProxyConnectionError``.
    """
    url = f"http://localhost:{port}{_HEALTH_PATH}"
    try:
        resp = httpx.get(url, timeout=3)
        resp.raise_for_status()
        data = resp.json()
        return ProxyStatus(
            running=True,
            port=port,
            project=data.get("project", ""),
        )
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        raise ProxyConnectionError(port, str(exc)) from exc


def find_binary() -> str:
    """Locate the ``agentsecrets`` binary on PATH.

    Returns the absolute path, or raises ``CLINotFound``.
    """
    path = shutil.which("agentsecrets")
    if path is None:
        raise CLINotFound()
    return path


def auto_start(port: int = DEFAULT_PORT) -> None:
    """Start the proxy as a background process.

    Requires the ``agentsecrets`` binary to be on PATH.
    """
    binary = find_binary()
    subprocess.Popen(
        [binary, "proxy", "start", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def wait_for_ready(
    port: int = DEFAULT_PORT,
    *,
    timeout: float = 10.0,
    interval: float = 0.25,
) -> ProxyStatus:
    """Poll the health endpoint until the proxy is ready.

    Uses linear back-off (capped at 2 s between attempts).
    Raises ``AgentSecretsNotRunning`` if *timeout* seconds elapse.
    """
    deadline = time.monotonic() + timeout
    delay = interval

    while time.monotonic() < deadline:
        try:
            return health_check(port)
        except ProxyConnectionError:
            time.sleep(delay)
            delay = min(delay * 1.5, 2.0)

    raise AgentSecretsNotRunning(port)
