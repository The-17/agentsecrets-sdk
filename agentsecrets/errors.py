"""AgentSecrets SDK exception hierarchy.

Every exception carries a human-readable message and an optional ``fix_hint``
that tells the caller exactly which CLI command resolves the problem.  This
makes errors actionable for both humans and AI agents reading the output.

Hierarchy
---------
AgentSecretsError
├── AgentSecretsNotRunning
├── CLINotFound
├── CLIError
├── ProxyConnectionError
├── SessionExpired
├── SecretNotFound
├── DomainNotAllowed
├── UpstreamError
├── PermissionDenied
├── WorkspaceNotFound
├── ProjectNotFound
└── AllowlistModificationDenied
"""

from __future__ import annotations


class AgentSecretsError(Exception):
    """Base exception for all AgentSecrets SDK errors."""

    def __init__(self, message: str, *, fix_hint: str | None = None) -> None:
        self.message = message
        self.fix_hint = fix_hint
        full = f"{message}\n  ↳ Fix: {fix_hint}" if fix_hint else message
        super().__init__(full)


# ---------------------------------------------------------------------------
# Proxy / connectivity
# ---------------------------------------------------------------------------

class AgentSecretsNotRunning(AgentSecretsError):
    """The proxy is not running and could not be auto-started."""

    def __init__(self, port: int) -> None:
        self.port = port
        super().__init__(
            f"AgentSecrets proxy is not running on port {port}.",
            fix_hint="agentsecrets proxy start",
        )


class ProxyConnectionError(AgentSecretsError):
    """Could not connect to the proxy."""

    def __init__(self, port: int, reason: str) -> None:
        self.port = port
        self.reason = reason
        super().__init__(
            f"Cannot connect to proxy on port {port}: {reason}",
            fix_hint="agentsecrets proxy start",
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class CLINotFound(AgentSecretsError):
    """The ``agentsecrets`` binary is not on PATH."""

    def __init__(self) -> None:
        super().__init__(
            "The 'agentsecrets' binary was not found on PATH.",
            fix_hint="Install AgentSecrets: https://github.com/The-17/agentsecrets",
        )


class CLIError(AgentSecretsError):
    """A CLI command returned a non-zero exit code."""

    def __init__(self, command: str, exit_code: int, stderr: str) -> None:
        self.command = command
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(
            f"CLI command failed (exit {exit_code}): agentsecrets {command}\n{stderr}",
        )


# ---------------------------------------------------------------------------
# Auth / session
# ---------------------------------------------------------------------------

class SessionExpired(AgentSecretsError):
    """The current session token has expired."""

    def __init__(self) -> None:
        super().__init__(
            "Your session has expired.",
            fix_hint="agentsecrets login",
        )


# ---------------------------------------------------------------------------
# Secrets / resources
# ---------------------------------------------------------------------------

class SecretNotFound(AgentSecretsError):
    """A referenced secret key does not exist in the keychain."""

    def __init__(self, key: str, project: str | None = None) -> None:
        self.key = key
        self.project = project
        ctx = f" in project '{project}'" if project else ""
        super().__init__(
            f"Secret '{key}' not found{ctx}.",
            fix_hint=f"agentsecrets secrets set {key}=VALUE",
        )


class DomainNotAllowed(AgentSecretsError):
    """The target domain is not in the workspace allowlist."""

    def __init__(self, domain: str, workspace: str | None = None) -> None:
        self.domain = domain
        self.workspace = workspace
        super().__init__(
            f"Domain '{domain}' is not in the workspace allowlist.",
            fix_hint=f"agentsecrets workspace allowlist add {domain}",
        )


class UpstreamError(AgentSecretsError):
    """The upstream API returned an error or was unreachable."""

    def __init__(self, status_code: int, body: str, url: str) -> None:
        self.status_code = status_code
        self.body = body
        self.url = url
        super().__init__(
            f"Upstream error {status_code} from {url}",
        )


# ---------------------------------------------------------------------------
# Permissions / RBAC
# ---------------------------------------------------------------------------

class PermissionDenied(AgentSecretsError):
    """The current user lacks the required role for this operation."""

    def __init__(
        self,
        operation: str,
        *,
        required_role: str | None = None,
        current_role: str | None = None,
    ) -> None:
        self.operation = operation
        self.required_role = required_role
        self.current_role = current_role
        parts = [f"Permission denied for '{operation}'."]
        if required_role:
            parts.append(f"Required: {required_role}.")
        if current_role:
            parts.append(f"Current: {current_role}.")
        super().__init__(" ".join(parts))


# ---------------------------------------------------------------------------
# Workspace / project lookup
# ---------------------------------------------------------------------------

class WorkspaceNotFound(AgentSecretsError):
    """The specified workspace does not exist."""

    def __init__(self, workspace_name: str) -> None:
        self.workspace_name = workspace_name
        super().__init__(
            f"Workspace '{workspace_name}' not found.",
            fix_hint="agentsecrets workspace list",
        )


class ProjectNotFound(AgentSecretsError):
    """The specified project does not exist."""

    def __init__(
        self, project_name: str, workspace_name: str | None = None
    ) -> None:
        self.project_name = project_name
        self.workspace_name = workspace_name
        ctx = f" in workspace '{workspace_name}'" if workspace_name else ""
        super().__init__(
            f"Project '{project_name}' not found{ctx}.",
            fix_hint="agentsecrets project list",
        )


class AllowlistModificationDenied(AgentSecretsError):
    """The user does not have permission to modify the allowlist."""

    def __init__(self) -> None:
        super().__init__(
            "Only workspace admins can modify the domain allowlist.",
        )
