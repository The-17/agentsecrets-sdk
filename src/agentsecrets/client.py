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
        If ``True``, start the proxy automatically when needed.
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
    ) -> None:
        self._port = port or int(os.environ.get("AGENTSECRETS_PORT", DEFAULT_PORT))
        self._workspace = workspace or os.environ.get("AGENTSECRETS_WORKSPACE")
        self._project = project or os.environ.get("AGENTSECRETS_PROJECT")
        self._auto_start = auto_start
        self._agent = agent
        self._agent_token = agent_token
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
        """Resolve authentication lazily on first use."""
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
        """Make an authenticated API call through the proxy.

        See :func:`agentsecrets.call.call` for full parameter docs.
        """
        self._ensure_open()
        auth = self._ensure_auth()

        resolved_agent_id, resolved_agent_token = _resolve_agent_identity(
            agent, agent_id, agent_token, self._agent, self._agent_token
        )

        return _call(
            auth.port,
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
        auth = self._ensure_auth()

        resolved_agent_id, resolved_agent_token = _resolve_agent_identity(
            agent, agent_id, agent_token, self._agent, self._agent_token
        )

        return await _async_call(
            auth.port,
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

    def __enter__(self) -> AgentSecrets:
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
    """Synchronous AgentSecrets client — the default entry point.

    All I/O is synchronous: :meth:`call` and :meth:`spawn` block until they
    return. Async variants (:meth:`async_call`, :meth:`spawn_async`) are
    available for occasional use inside an event loop, but if async is your
    primary mode reach for :class:`AsyncAgentSecrets` instead.

    Use as a context manager to guarantee cleanup::

        with AgentSecrets() as client:
            client.call("https://api.stripe.com/v1/balance", bearer="STRIPE_KEY")
    """


class AsyncAgentSecrets(_BaseClient):
    """Asynchronous AgentSecrets client.

    Mirrors :class:`AgentSecrets`, but :meth:`call` and :meth:`spawn` are
    coroutines — so the primary API is ``await client.call(...)`` (not
    ``async_call``). Use ``async with`` for deterministic cleanup::

        async with AsyncAgentSecrets() as client:
            await client.call(
                "https://api.stripe.com/v1/balance", bearer="STRIPE_KEY"
            )
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

    async def __aenter__(self) -> AsyncAgentSecrets:
        self._ensure_open()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the client and release resources (async variant of :meth:`close`).

        Idempotent: closing an already-closed client is a no-op.
        """
        self.close()
