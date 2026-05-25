"""AgentSecrets SDK data models.

All models are plain ``dataclasses`` — no ORMs, no schema libraries, no magic.
They map 1:1 to the structures used by the AgentSecrets proxy and CLI.

Zero-knowledge rule: ``AgentSecretsResponse`` and ``AuditEvent`` have **no**
field that could carry a credential value.
"""

from __future__ import annotations

import json as _json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Core proxy response
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentSecretsResponse:
    """Response returned from ``call()`` / ``async_call()``.

    Contains the upstream HTTP status, headers, and body — but structurally
    **cannot** carry a credential value.
    """

    status_code: int
    headers: dict[str, str]
    body: bytes
    redacted: bool = False
    duration_ms: int = 0

    @property
    def text(self) -> str:
        """Decode the response body as UTF-8."""
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        """Parse the response body as JSON."""
        return _json.loads(self.body)


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEvent:
    """A single proxy audit log entry.

    Matches the Go ``AuditEvent`` struct in ``pkg/proxy/audit.go``.
    Secret key **names** are logged; values are **never** logged.
    """

    timestamp: datetime
    secret_keys: list[str]
    method: str
    target_url: str
    auth_styles: list[str]
    status_code: int
    duration_ms: int
    status: str  # "OK" or "BLOCKED"
    agent_id: str = ""
    domain: str = ""
    reason: str = "-"
    redacted: bool = False


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusResult:
    """Output of ``agentsecrets status``."""

    logged_in: bool
    user_email: str = ""
    workspace_name: str = ""
    workspace_id: str = ""
    project_name: str = ""
    project_id: str = ""
    proxy_running: bool = False


# ---------------------------------------------------------------------------
# Workspace / project / member
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Workspace:
    """A workspace returned by the management layer."""

    id: str
    name: str
    type: str = ""
    role: str = ""


@dataclass(frozen=True)
class Project:
    """A project within a workspace."""

    id: str
    name: str
    workspace_id: str = ""


@dataclass(frozen=True)
class Member:
    """A workspace member."""

    email: str
    role: str
    user_id: str = ""


# ---------------------------------------------------------------------------
# Secrets (metadata only — never the value)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SecretKey:
    """Metadata for a single secret.  Contains the key name — never the value."""

    key: str
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class DiffResult:
    """Result of ``secrets diff`` — compares local vs. remote keys."""

    has_drift: bool
    local_only: list[str] = field(default_factory=list)
    remote_only: list[str] = field(default_factory=list)
    out_of_sync: list[str] = field(default_factory=list)
    in_sync: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SyncResult:
    """Result of ``secrets pull``."""

    pulled: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PushResult:
    """Result of ``secrets push``."""

    pushed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Proxy
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProxyStatus:
    """Health / status of the local proxy."""

    running: bool
    port: int = 0
    project: str = ""


# ---------------------------------------------------------------------------
# Spawn
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SpawnResult:
    """Result of ``spawn()`` — a completed child process."""

    exit_code: int
    stdout: str = ""
    stderr: str = ""


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AllowlistEntry:
    """A single domain on the workspace allowlist."""

    domain: str


@dataclass(frozen=True)
class AllowlistEvent:
    """An allowlist audit log entry."""

    timestamp: str
    action: str
    domain: str
    user_email: str = ""
