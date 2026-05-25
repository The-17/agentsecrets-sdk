"""Proxy management sub-client."""

from __future__ import annotations

import json as _json
from datetime import datetime

from .._cli import run
from ..errors import ProxyConnectionError
from ..models import AuditEvent, ProxyStatus
from ..proxy import DEFAULT_PORT, health_check


class ProxyClient:
    """Manage the proxy via the ``agentsecrets proxy`` CLI commands."""

    def start(self, *, port: int = DEFAULT_PORT) -> None:
        """Start the proxy server."""
        run("proxy", "start", "--port", str(port))

    def stop(self) -> None:
        """Stop the proxy server."""
        run("proxy", "stop")

    def status(self, *, port: int = DEFAULT_PORT) -> ProxyStatus:
        """Check whether the proxy is running."""
        try:
            return health_check(port)
        except ProxyConnectionError:
            return ProxyStatus(running=False)

    def logs(
        self,
        *,
        last: int = 20,
        secret: str | None = None,
    ) -> list[AuditEvent]:
        """Retrieve recent proxy audit log entries."""
        args = ["proxy", "logs", "--last", str(last)]
        if secret:
            args.extend(["--secret", secret])
        result = run(*args)
        return _parse_audit_logs(result.stdout)


def _parse_audit_logs(output: str) -> list[AuditEvent]:
    """Best-effort parse of proxy log output.

    The CLI renders a table.  We return an empty list if we can't parse;
    richer parsing will come with CLI --json support.
    """
    events: list[AuditEvent] = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = _json.loads(line)
            events.append(AuditEvent(
                timestamp=datetime.fromisoformat(data["timestamp"]),
                secret_keys=data.get("secret_keys", []),
                method=data.get("method", ""),
                target_url=data.get("target_url", ""),
                auth_styles=data.get("auth_styles", []),
                status_code=data.get("status_code", 0),
                duration_ms=data.get("duration_ms", 0),
                status=data.get("status", "OK"),
                agent_id=data.get("agent_id", ""),
                domain=data.get("domain", ""),
                reason=data.get("reason", "-"),
                redacted=data.get("redacted", False),
            ))
        except (ValueError, KeyError, _json.JSONDecodeError):
            continue
    return events
