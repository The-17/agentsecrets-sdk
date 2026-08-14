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
    """Base exception for all AgentSecrets SDK errors.

    All AgentSecrets SDK exceptions inherit from this class, so catching it
    catches every SDK-specific error. Each exception carries a human-readable
    ``message`` and an optional ``fix_hint`` — the concrete CLI command that
    resolves the problem (e.g. ``"agentsecrets proxy start"``).

    The fix_hint, when provided, is appended to the rendered message as
    ``"  ↳ Fix: <command>"`` so it surfaces in str(exc) and in tracebacks,
    making errors actionable for both humans and AI agents reading the output.
    """

    def __init__(self, message: str, *, fix_hint: str | None = None) -> None:
        self.message = message
        self.fix_hint = fix_hint
        full = f"{message}\n  ↳ Fix: {fix_hint}" if fix_hint else message
        super().__init__(full)


# ---------------------------------------------------------------------------
# Proxy / connectivity
# ---------------------------------------------------------------------------

class AgentSecretsNotRunning(AgentSecretsError):
    """The proxy is not running and could not be auto-started.

    Raised when the SDK probes the configured port, finds no proxy, and
    ``auto_start`` is disabled (or auto-start itself failed). The fix is to
    start the proxy with ``agentsecrets proxy start``.

    :param port: The port where the proxy is expected to be running.
    """

    def __init__(self, port: int) -> None:
        self.port = port
        super().__init__(
            f"AgentSecrets proxy is not running on port {port}.",
            fix_hint="agentsecrets proxy start",
        )


class ProxyConnectionError(AgentSecretsError):
    """Could not connect to the proxy.

    Raised when the proxy appears to be running (a PID file exists or a port is
    configured) but the SDK's health probe fails to reach it — e.g. the process
    died and left a stale PID, or the port is blocked. The fix is to restart the
    proxy with ``agentsecrets proxy start``.

    :param port: The port where the proxy is expected to be running.
    :param reason: The reason for the connection failure.
    """

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
    """The ``agentsecrets`` binary is not on PATH.

    Raised when the SDK tries to shell out to the ``agentsecrets`` CLI but no
    executable is found. The fix is to install the CLI (see the linked URL).
    """

    def __init__(self) -> None:
        super().__init__(
            "The 'agentsecrets' binary was not found on PATH.",
            fix_hint="Install AgentSecrets: https://github.com/The-17/agentsecrets",
        )


class CLIError(AgentSecretsError):
    """A CLI command returned a non-zero exit code.

    Raised when the ``agentsecrets`` binary exits non-zero and the error does
    not map to a more specific SDK exception. Carries the failing ``command``,
    ``exit_code``, and raw ``stderr`` so callers can inspect the failure.

    :param command: The CLI command that failed.
    :param exit_code: The exit code of the CLI command.
    :param stderr: The standard error output of the CLI command.
    """

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
    """The current session token has expired.

    Raised when the proxy rejects a request because the session token's TTL has
    elapsed. The fix is to re-authenticate with ``agentsecrets login``.
    """

    def __init__(self) -> None:
        super().__init__(
            "Your session has expired.",
            fix_hint="agentsecrets login",
        )


# ---------------------------------------------------------------------------
# Secrets / resources
# ---------------------------------------------------------------------------

class SecretNotFound(AgentSecretsError):
    """A referenced secret key does not exist in the keychain.

    Raised when a call references a secret key name (e.g. ``bearer="STRIPE_KEY"``)
    that the active project/environment does not have stored. The fix is to
    provision it with ``agentsecrets secrets set <KEY>=<value>``. Carries the
    ``key`` name and optional ``project`` context.

    :param key: The name of the secret key that was not found.
    :param project: The project context (if any) where the key was sought.
    """

    def __init__(self, key: str, project: str | None = None) -> None:
        self.key = key
        self.project = project
        ctx = f" in project '{project}'" if project else ""
        super().__init__(
            f"Secret '{key}' not found{ctx}.",
            fix_hint=f"agentsecrets secrets set {key}=VALUE",
        )


class DomainNotAllowed(AgentSecretsError):
    """The target domain is not in the workspace allowlist.

    Raised by the proxy when the upstream URL's host is not on the workspace's
    domain allowlist — a guardrail preventing credentials from being sent to
    unintended hosts. The fix is to add the domain with
    ``agentsecrets workspace allowlist add <domain>``. Carries the offending
    ``domain`` and optional ``workspace`` name.

    :param domain: The domain that was not allowed.
    :param workspace: The workspace context (if any) where the check occurred.
    """

    def __init__(self, domain: str, workspace: str | None = None) -> None:
        self.domain = domain
        self.workspace = workspace
        super().__init__(
            f"Domain '{domain}' is not in the workspace allowlist.",
            fix_hint=f"agentsecrets workspace allowlist add {domain}",
        )


class UpstreamError(AgentSecretsError):
    """The upstream API returned an error or was unreachable.

    Raised when credential injection succeeded and the request reached the
    upstream API, but the upstream returned a non-2xx status (or was
    unreachable). This is distinct from a proxy/SDK failure: the auth worked,
    the upstream itself is the problem. Carries the ``status_code``, ``body``,
    and target ``url`` for diagnostics.

    :param status_code: The HTTP status code returned by the upstream API.
    :param body: The response body from the upstream API.
    :param url: The target URL that was requested.
    """

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
    """The current user lacks the required role for this operation.

    Raised when an operation requires a workspace role the current user does not
    hold (e.g. admin-only actions like modifying the allowlist). Carries the
    ``operation`` that was attempted, plus the ``required_role`` and
    ``current_role`` when known, so callers can surface a precise message.

    :param operation: The operation that was attempted and denied.
    :param required_role: The role required to perform the operation.
    :param current_role: The current role of the user (if known).
    """

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
    """The specified workspace does not exist.

    Raised when an operation targets a workspace name that is not registered to
    the current account. The fix is to list workspaces to confirm the name with
    ``agentsecrets workspace list``. Carries the ``workspace_name``.

    :param workspace_name: The name of the workspace that was not found.
    """

    def __init__(self, workspace_name: str) -> None:
        self.workspace_name = workspace_name
        super().__init__(
            f"Workspace '{workspace_name}' not found.",
            fix_hint="agentsecrets workspace list",
        )


class ProjectNotFound(AgentSecretsError):
    """The specified project does not exist.

    Raised when an operation targets a project name that is not registered within
    the current workspace. The fix is to list projects to confirm the name with
    ``agentsecrets project list``. Carries the ``project_name`` and optional
    ``workspace_name`` for context.

    :param project_name: The name of the project that was not found.
    :param workspace_name: The workspace context (if any) where the project was sought.
    """

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
    """The user does not have permission to modify the allowlist.

    Raised specifically when a non-admin user attempts to add or remove a domain
    from the workspace allowlist. Allowlist modifications are restricted to
    workspace admins. The fix is to contact a workspace admin to perform the
    change.
    """

    def __init__(self) -> None:
        super().__init__(
            "Only workspace admins can modify the domain allowlist.",
        )
