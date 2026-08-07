"""Mock client for testing.

``MockAgentSecrets`` is a drop-in replacement for ``AgentSecrets`` that
records every ``call()`` and ``spawn()`` invocation without touching
the proxy or keychain.  It lets downstream developers write fast,
isolated tests for code that depends on the SDK.

Usage::

    from agentsecrets.testing import MockAgentSecrets

    mock = MockAgentSecrets()
    response = mock.call("https://api.example.com", bearer="KEY")

    assert len(mock.calls) == 1
    assert mock.calls[0]["url"] == "https://api.example.com"
    assert mock.calls[0]["bearer"] == "KEY"
    # No credential values are ever stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import AgentSecretsResponse, SpawnResult


@dataclass
class CallRecord:
    """What was passed to a ``call()`` invocation.

    Records injection **key names** — never values.
    """

    url: str
    method: str = "GET"
    bearer: str | None = None
    basic: str | None = None
    header: dict[str, str] | None = None
    query: dict[str, str] | None = None
    body_field: dict[str, str] | None = None
    form_field: dict[str, str] | None = None
    body: Any = None


@dataclass
class SpawnRecord:
    """What was passed to a ``spawn()`` invocation."""

    command: list[str] = field(default_factory=list)
    capture: bool = True


class MockAgentSecrets:
    """Drop-in replacement for ``AgentSecrets`` in tests.

    Parameters
    ----------
    default_response:
        The ``AgentSecretsResponse`` returned by ``call()`` / ``async_call()``
        unless overridden per-call.
    default_spawn_result:
        The ``SpawnResult`` returned by ``spawn()`` / ``spawn_async()``.
    """

    def __init__(
        self,
        *,
        default_response: AgentSecretsResponse | None = None,
        default_spawn_result: SpawnResult | None = None,
    ) -> None:
        self.calls: list[CallRecord] = []
        self.spawns: list[SpawnRecord] = []

        self._default_response = default_response or AgentSecretsResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=b'{"ok": true}',
        )
        self._default_spawn = default_spawn_result or SpawnResult(exit_code=0)

    # ------------------------------------------------------------------
    # call / async_call
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
        agent_id: str | None = None,
        timeout: float = 30.0,
    ) -> AgentSecretsResponse:
        """Record the call and return the default mock response."""
        self.calls.append(CallRecord(
            url=url,
            method=method,
            bearer=bearer,
            basic=basic,
            header=header,
            query=query,
            body_field=body_field,
            form_field=form_field,
            body=body,
        ))
        return self._default_response

    async def async_call(
        self,
        url: str,
        **kwargs: Any,
    ) -> AgentSecretsResponse:
        """Async variant — same recording, same response."""
        return self.call(url, **kwargs)

    # ------------------------------------------------------------------
    # spawn / spawn_async
    # ------------------------------------------------------------------

    def spawn(
        self,
        command: list[str],
        *,
        capture: bool = True,
        timeout: float | None = None,
    ) -> SpawnResult:
        """Record the spawn and return the default mock result."""
        self.spawns.append(SpawnRecord(command=command, capture=capture))
        return self._default_spawn

    async def spawn_async(
        self,
        command: list[str],
        **kwargs: Any,
    ) -> SpawnResult:
        """Async variant — same recording, same result."""
        return self.spawn(command, **kwargs)

    # ------------------------------------------------------------------
    # Context manager (no-op)
    # ------------------------------------------------------------------

    def __enter__(self) -> MockAgentSecrets:
        return self

    def __exit__(self, *exc: object) -> None:
        pass

    def close(self) -> None:
        """No-op — nothing to clean up."""
