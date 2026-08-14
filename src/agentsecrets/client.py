"""AgentSecrets SDK — main client.

The ``AgentSecrets`` class is the single entry point for the SDK.
It wires together auth resolution, the proxy call engine, process
spawning, and the management sub-clients.

Usage::

    from agentsecrets import AgentSecrets

    as_client = AgentSecrets()
    response = as_client.call(
        "https://api.stripe.com/v1/charges",
        method="POST",
        bearer="STRIPE_SECRET_KEY",
        body={"amount": 1000, "currency": "usd", "source": "tok_visa"},
    )
    print(response.json())
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any
from typing_extensions import Self

from .auth import AuthContext, resolve
from .call import async_call as _async_call
from .call import call as _call
from .management.allowlist import AllowlistClient
from .management.projects import ProjectsClient
from .management.proxy import ProxyClient
from .management.secrets import SecretsClient
from .management.workspaces import WorkspacesClient
from .models import AgentSecretsResponse, SpawnResult
from .proxy import DEFAULT_PORT
from .spawn import spawn as _spawn
from .spawn import spawn_async as _spawn_async


def _resolve_agent_identity(
    agent: Any | None,
    agent_id: str | None,
    agent_token: str | None,
    default_agent: Any | None,
    default_token: str | None,
) -> tuple[str | None, str | None]:
    """Resolve an effective ``(agent_id, agent_token)`` pair.

    Precedence for the agent: explicit ``agent`` > ``agent_id`` > the
    constructor default. A string agent is used verbatim; an object with a
    ``.name`` contributes its name; anything else is stringified. When no
    token is supplied, one is synthesised as ``f"{ID.upper()}_TOKEN"``. An
    explicitly supplied token is never overwritten.
    """
    effective_agent = agent or agent_id or default_agent
    effective_token = agent_token or default_token

    resolved_agent_id = None
    resolved_agent_token = effective_token

    if effective_agent is not None:
        if isinstance(effective_agent, str):
            resolved_agent_id = effective_agent
        elif hasattr(effective_agent, "name"):
            resolved_agent_id = effective_agent.name
        else:
            resolved_agent_id = str(effective_agent)

        if not resolved_agent_token:
            resolved_agent_token = f"{resolved_agent_id.upper()}_TOKEN"

    return resolved_agent_id, resolved_agent_token


class _BaseClient:
    """Shared configuration, auth resolution, and lifecycle state.

    Both :class:`AgentSecrets` (sync) and :class:`AsyncAgentSecrets` (async)
    extend this. It owns the constructor, the management sub-clients, lazy
    auth resolution, the closed-state guard, and the synchronous defaults for
    :meth:`call` / :meth:`spawn`. :class:`AsyncAgentSecrets` overrides those two
    with coroutine equivalents; everything else is shared unchanged.

    Parameters
    ----------
    port:
        Proxy port (default: ``8765``, or ``AGENTSECRETS_PORT`` env var).
    workspace:
        Active workspace name (or ``AGENTSECRETS_WORKSPACE``).
    project:
        Active project name (or ``AGENTSECRETS_PROJECT``).
    auto_start:
        If ``True``, warm up a persistent proxy when needed. Calls work
        without it — the binary starts a transient proxy per call — but a
        running proxy is faster.
    timeout:
        Default timeout in seconds for the delegated ``agentsecrets`` binary.
    """

    def __init__(
        self,
        *,
        port: int | None = None,
        workspace: str | None = None,
        project: str | None = None,
        auto_start: bool = True,
        intercept: bool = False,
        environment: str | None = None,
        agent: Any | None = None,
        agent_token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._port = port or int(os.environ.get("AGENTSECRETS_PORT", DEFAULT_PORT))
        self._workspace = workspace or os.environ.get("AGENTSECRETS_WORKSPACE")
        self._project = project or os.environ.get("AGENTSECRETS_PROJECT")
        self._auto_start = auto_start
        self._agent = agent
        self._agent_token = agent_token
        self._timeout = timeout
        self._is_closed = False

        from .config import settings
        self._environment = (
            environment
            or os.environ.get("AGENTSECRETS_ENV")
            or os.environ.get("AS_ENV")
        )
        if self._environment:
            settings.environment = self._environment

        if intercept:
            from . import init as _init
            _init(
                port=self._port,
                workspace=self._workspace,
                project=self._project,
                environment=self._environment,
            )

        # Management sub-clients
        self.workspaces = WorkspacesClient()
        self.projects = ProjectsClient()
        self.secrets = SecretsClient()
        self.proxy = ProxyClient()
        self.allowlist = AllowlistClient()

        # Lazily resolved on first call
        self._auth: AuthContext | None = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        """Verify the client has not been closed."""
        if self._is_closed:
            raise RuntimeError(
                "Cannot use AgentSecrets client after close(). "
                "Create a new client or use a context manager."
            )

    def _ensure_auth(self) -> AuthContext:
        """Warm up a persistent proxy, lazily, on first use.

        Delegation does not *require* this — the binary starts a transient
        proxy per call when none is running — but warming one up once makes
        subsequent calls faster. Kept off the :meth:`call` critical path.
        """
        if self._auth is None:
            self._auth = resolve(self._port, auto_start_proxy=self._auto_start)
        return self._auth

    # ------------------------------------------------------------------
    # Core — call()
    # ------------------------------------------------------------------

    def call(
        self,
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
        agent: Any | None = None,
        agent_id: str | None = None,
        agent_token: str | None = None,
        timeout: float = 30.0,
    ) -> AgentSecretsResponse:
        """Make an authenticated API call through the AgentSecrets proxy.

        This method resolves credentials from the OS keychain and injects them
        into the request at the transport layer, ensuring your code never handles
        raw credential values. Supports seven authentication injection styles
        to cover all common API authentication patterns.

        :param url: Target upstream URL.
        :param method: HTTP method (GET, POST, PUT, PATCH, DELETE, etc.).
        :param body: Request body — dict (JSON-encoded), str, or bytes.
        :param headers: Extra (non-auth) forward headers to pass through.
        :param bearer: Bearer token secret key name. Injects as:
            ``Authorization: Bearer <value>``
        :param basic: Basic auth secret key name. Stores credential as
            ``username:password`` or ``token`` and injects as:
            ``Authorization: Basic base64(<value>)``
        :param header: Dictionary mapping header names to secret key names.
            Each header is injected as ``<header-name>: <value>``.
        :param query: Dictionary mapping query parameter names to secret key names.
            Each parameter is injected as ``<param-name>=<value>``.
        :param body_field: Dictionary mapping JSON paths to secret key names.
            Each field is injected into the JSON body at the specified path.
            Uses dot notation for nested paths (e.g., ``{"auth.token": "API_KEY"}``
            becomes ``{"auth": {"token": "<value>"}}``).
        :param form_field: Dictionary mapping form field names to secret key names.
            Each field is injected as ``<field-name>=<value>`` in application/x-www-form-urlencoded format.
        :param agent: Optional agent identity for scoping the call.
        :param agent_id: Optional agent ID (deprecated, use ``agent`` parameter).
        :param agent_token: Optional agent token secret key name. Functions like
            ``bearer`` but specifically for agent-to-agent authentication.
        :param timeout: Maximum seconds to wait for the API call.

        **Authentication Injection Styles:**

        1. **Bearer Token** (most common — Stripe, OpenAI, GitHub):
        .. code-block:: python
            client.call("https://api.stripe.com/v1/balance", bearer="STRIPE_KEY")

        2. **Custom Header** (SendGrid, Twilio, API Gateway):
        .. code-block:: python
            client.call(
                "https://api.sendgrid.com/v3/mail/send",
                method="POST",
                body=email_payload,
                header={"X-Api-Key": "SENDGRID_KEY"}
            )

        3. **Query Parameter** (Google Maps, weather APIs):
        .. code-block:: python
            client.call(
                "https://maps.googleapis.com/maps/api/geocode/json",
                query={"key": "GMAP_KEY", "address": "Lagos, Nigeria"}
            )

        4. **Basic Auth** (Jira, legacy REST APIs):
        .. code-block:: python
            client.call(
                "https://yourcompany.atlassian.net/rest/api/2/issue",
                basic="JIRA_CREDS"
            )

        5. **JSON Body Injection** (OAuth tokens, custom APIs):
        .. code-block:: python
            client.call(
                "https://api.example.com/oauth/token",
                method="POST",
                body={"grant_type": "client_credentials"},
                body_field={"client_secret": "CLIENT_SECRET"}
            )

        6. **Form Field Injection** (traditional OAuth, web forms):
        .. code-block:: python
            client.call(
                "https://oauth.example.com/token",
                method="POST",
                form_field={"api_key": "API_KEY"}
            )

        7. **Agent Token** (agent-to-agent authentication):
        .. code-block:: python
            client.call(
                "https://api.internal.example.com/data",
                agent_token="INTERNAL_AGENT_TOKEN"
            )

        Multiple injection styles can be combined in a single call:
        .. code-block:: python
            client.call(
                "https://api.example.com/data",
                bearer="AUTH_TOKEN",
                header={"X-Org-ID": "ORG_SECRET"},
                query={"version": "API_VERSION"}
            )

        :returns: :class:`AgentSecretsResponse` containing status code, headers,
            body, and metadata. The response object never contains injected
            credential values — this is a structural security guarantee.

        :raises AgentSecretsNotRunning: If the AgentSecrets proxy is not running.
        :raises DomainNotAllowed: If the target domain is not on the allowlist.
        :raises SecretNotFound: If any specified secret key is not found.
        :raises UpstreamError: If the upstream API returns an error (injection succeeded).
        :raises PermissionDenied: If insufficient permissions for the requested operation.
        """
        self._ensure_open()

        resolved_agent_id, resolved_agent_token = _resolve_agent_identity(
            agent, agent_id, agent_token, self._agent, self._agent_token
        )

        return _call(
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
            agent_id=resolved_agent_id,
            agent_token=resolved_agent_token,
            timeout=timeout,
        )

    async def async_call(
        self,
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
        agent: Any | None = None,
        agent_id: str | None = None,
        agent_token: str | None = None,
        timeout: float = 30.0,
    ) -> AgentSecretsResponse:
        """Async variant of :meth:`call`."""
        self._ensure_open()

        resolved_agent_id, resolved_agent_token = _resolve_agent_identity(
            agent, agent_id, agent_token, self._agent, self._agent_token
        )

        return await _async_call(
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
            agent_id=resolved_agent_id,
            agent_token=resolved_agent_token,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Core — spawn()
    # ------------------------------------------------------------------

    def spawn(
        self,
        command: list[str],
        *,
        capture: bool = True,
        timeout: float | None = None,
    ) -> SpawnResult:
        """Spawn a child process with secrets injected as env vars.

        See :func:`agentsecrets.spawn.spawn` for full parameter docs.
        """
        self._ensure_open()
        return _spawn(command, capture=capture, timeout=timeout)

    async def spawn_async(
        self,
        command: list[str],
        *,
        capture: bool = True,
        timeout: float | None = None,
    ) -> SpawnResult:
        """Async variant of :meth:`spawn`."""
        self._ensure_open()
        return await _spawn_async(command, capture=capture, timeout=timeout)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Return a dictionary of current session info.

        This is a convenience wrapper; for structured data, use the
        management sub-clients directly.
        """
        self._ensure_open()
        from ._cli import run as _cli_run
        result = _cli_run("status")
        return {"raw": result.stdout}

    # ------------------------------------------------------------------
    # Context managers — temporary workspace / project switch
    # ------------------------------------------------------------------

    @contextmanager
    def use_workspace(self, name: str) -> Generator[None, None, None]:
        """Temporarily switch to a different workspace.

        Restores the previous workspace on exit.
        """
        previous = self._workspace
        try:
            self.workspaces.switch(name)
            self._workspace = name
            yield
        finally:
            if previous:
                self.workspaces.switch(previous)
            self._workspace = previous

    @contextmanager
    def use_project(self, name: str) -> Generator[None, None, None]:
        """Temporarily switch to a different project.

        Restores the previous project on exit.
        """
        previous = self._project
        try:
            self.projects.use(name)
            self._project = name
            yield
        finally:
            if previous:
                self.projects.use(previous)
            self._project = previous

    # ------------------------------------------------------------------
    # Resource management
    # ------------------------------------------------------------------

    def __enter__(self) -> Self:
        self._ensure_open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the client and release all held resources.

        After calling close(), the client cannot be reused. Attempting to call
        any method on a closed client will raise RuntimeError.
        """
        if not self._is_closed:
            self._is_closed = True
            self._auth = None


class AgentSecrets(_BaseClient):
    """Synchronous AgentSecrets client, the default entry point.

    This is the main client class for synchronous applications. All I/O operations
    (:meth:`call`, :meth:`spawn`) are blocking and will return only when the
    operation completes. For occasional async usage within an event loop, async
    variants (:meth:`async_call`, :meth:`spawn_async`) are available, but for
    primarily async codebases, use :class:`AsyncAgentSecrets` instead.

    The client operates in dual-mode: by default it delegates to the local
    ``agentsecrets`` binary for credential injection, but can be configured to
    communicate directly with the AgentSecrets cloud API via environment
    variables. It manages authentication, proxy connections, and provides access
    to all management APIs (secrets, projects, workspaces, allowlist, proxy).

    Use as a context manager to guarantee cleanup of resources::

        with AgentSecrets() as client:
            response = client.call(
                "https://api.stripe.com/v1/balance",
                bearer="STRIPE_KEY"
            )
            print(response.json())

    The client can also be used manually, but remember to call :meth:`close()` when
    finished to release resources::

        client = AgentSecrets()
        try:
            response = client.call("https://api.api.example.com/endpoint")
        finally:
            client.close()

    :param port: Proxy port (default: 8765, or ``AGENTSECRETS_PORT`` env var).
    :param workspace: Active workspace name (or ``AGENTSECRETS_WORKSPACE``).
    :param project: Active project name (or ``AGENTSECRETS_PROJECT``).
    :param auto_start: If ``True``, warm up a persistent proxy when needed.
    :param intercept: Enable transparent HTTP interception for ``requests``/``httpx``.
    :param environment: Default environment for secret resolution.
    :param agent: Default agent for calls (can be overridden per call).
    :param agent_token: Default agent token (can be overridden per call).
    :param timeout: Default timeout in seconds for API calls.
    """


class AsyncAgentSecrets(_BaseClient):
    """Asynchronous AgentSecrets client.

    This is the async variant of :class:`AgentSecrets` designed for async-first
    codebases. All I/O operations (:meth:`call`, :meth:`spawn`) are coroutines
    and should be used with ``await``. The primary API is ``await client.call(...)``
    (not :meth:`async_call` which exists only for backward compatibility).

    The client operates in dual-mode: by default it delegates to the local
    ``agentsecrets`` binary for credential injection, but can be configured to
    communicate directly with the AgentSecrets cloud API via environment
    variables.

    Use ``async with`` for deterministic cleanup of resources::

        async with AsyncAgentSecrets() as client:
            response = await client.call(
                "https://api.stripe.com/v1/balance",
                bearer="STRIPE_KEY"
            )
            print(response.json())

    The client can also be used manually, but remember to call :meth:`aclose()` when
    finished to release resources::

        client = AsyncAgentSecrets()
        try:
            response = await client.call("https://api.api.example.com/endpoint")
        finally:
            await client.aclose()

    :param port: Proxy port (default: 8765, or ``AGENTSECRETS_PORT`` env var).
    :param workspace: Active workspace name (or ``AGENTSECRETS_WORKSPACE``).
    :param project: Active project name (or ``AGENTSECRETS_PROJECT``).
    :param auto_start: If ``True``, warm up a persistent proxy when needed.
    :param intercept: Enable transparent HTTP interception for ``requests``/``httpx``.
    :param environment: Default environment for secret resolution.
    :param agent: Default agent for calls (can be overridden per call).
    :param agent_token: Default agent token (can be overridden per call).
    :param timeout: Default timeout in seconds for API calls.
    """

    async def call(  # type: ignore[override]
        self,
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
        agent: Any | None = None,
        agent_id: str | None = None,
        agent_token: str | None = None,
        timeout: float = 30.0,
    ) -> AgentSecretsResponse:
        """Make an authenticated API call through the proxy (async).

        Delegates to :meth:`async_call`; see it for full parameter docs.
        """
        return await self.async_call(
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
            agent=agent,
            agent_id=agent_id,
            agent_token=agent_token,
            timeout=timeout,
        )

    async def spawn(  # type: ignore[override]
        self,
        command: list[str],
        *,
        capture: bool = True,
        timeout: float | None = None,
    ) -> SpawnResult:
        """Spawn a child process with secrets injected as env vars (async).

        Delegates to :meth:`spawn_async`.
        """
        return await self.spawn_async(command, capture=capture, timeout=timeout)

    async def __aenter__(self) -> Self:
        self._ensure_open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the client and release resources (async variant of :meth:`close`).

        Idempotent: closing an already-closed client is a no-op.
        """
        self.close()
