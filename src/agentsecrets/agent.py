"""Agent Identity management layer."""

from __future__ import annotations

from typing import Any

from ._cli import run
from .client import AgentSecrets
from .errors import AgentSecretsError
from .models import AgentCapabilities, AgentToken, IssuedAgentToken, AgentSecretsResponse


class Agent:
    """Represents an Agent Identity in AgentSecrets.

    Provides methods to manage the agent's tokens, policies, and
    make secure calls scoped under this agent's identity.
    """

    def __init__(
        self,
        name: str,
        id: str = "",
        project_id: str | None = None,
        created_at: str | None = None,
        token_count: int = 0,
        last_used: str | None = None,
    ) -> None:
        self.name = name
        self.id = id
        self.project_id = project_id
        self.created_at = created_at
        self.token_count = token_count
        self.last_used = last_used

    def list_tokens(self) -> list[AgentToken]:
        """List active tokens for this agent."""
        return list_tokens(self.name)

    def issue_token(
        self,
        *,
        label: str | None = None,
        expires: str | None = None,
        env: str | None = None,
        save_token: bool = False,
    ) -> IssuedAgentToken:
        """Issue a new token for this agent."""
        return issue_token(
            self.name,
            label=label,
            expires=expires,
            env=env,
            save_token=save_token,
        )

    def revoke_token(self, token_id: str, *, confirm: bool = True) -> None:
        """Revoke a specific token for this agent."""
        revoke_token(self.name, token_id, confirm=confirm)

    def revoke_all_tokens(self, *, confirm: bool = True) -> None:
        """Revoke all active tokens for this agent."""
        revoke_all_tokens(self.name, confirm=confirm)

    def get_policy(self) -> AgentCapabilities:
        """Get the capabilities/policy for this agent."""
        return get_policy(self.name)

    def set_policy(
        self,
        *,
        allow: list[str] | str | None = None,
        deny: list[str] | str | None = None,
    ) -> None:
        """Set the capabilities/policy for this agent."""
        set_policy(self.name, allow=allow, deny=deny)

    def delete(self, *, confirm: bool = True) -> None:
        """Delete this agent registration and all its tokens."""
        delete(self.name, confirm=confirm)

    def call(self, url: str, **kwargs: Any) -> AgentSecretsResponse:
        """Make an authenticated API call through the proxy scoped to this agent.

        Uses the agent's name as agent_id and automatically resolves the agent's
        token from the OS Keychain.
        """
        kwargs.setdefault("agent", self)
        return AgentSecrets().call(url, **kwargs)

    async def async_call(self, url: str, **kwargs: Any) -> AgentSecretsResponse:
        """Async variant of :meth:`call`."""
        kwargs.setdefault("agent", self)
        return await AgentSecrets().async_call(url, **kwargs)

    def __repr__(self) -> str:
        return f"Agent(name={self.name!r}, id={self.id!r}, project_id={self.project_id!r})"


# ---------------------------------------------------------------------------
# Module level lifecycle functions
# ---------------------------------------------------------------------------

def list_agents(project: str | None = None) -> list[Agent]:
    """List registered agents in the current workspace or filtered by project."""
    args = ["agent", "list"]
    if project:
        args.extend(["--project", project])

    result = run(*args)
    return _parse_agent_list(result.stdout)


def get(name: str) -> Agent:
    """Retrieve a registered agent by name."""
    agent_list = list_agents()
    for agent in agent_list:
        if agent.name == name:
            return agent
    raise AgentSecretsError(f"Agent '{name}' not found in the current workspace.")


def create(
    name: str,
    *,
    project: str | None = None,
    label: str | None = None,
    expires: str | None = None,
    env: str | None = None,
    save_token: bool = False,
) -> IssuedAgentToken:
    """Register a new agent and issue its first token."""
    args = ["agent", "register", name]
    if project:
        args.extend(["--project", project])
    if label:
        args.extend(["--label", label])
    if expires:
        args.extend(["--expires", expires])
    if env:
        args.extend(["--env", env])
    if save_token:
        args.append("--save-token")

    result = run(*args)
    parsed = _parse_registration_or_issue(result.stdout)
    
    agent_name = parsed.get("name", name)
    scope = parsed.get("scope", "workspace")
    project_id = None if scope == "workspace" else scope

    agent_obj = Agent(
        name=agent_name,
        project_id=project_id,
        created_at=None,
        token_count=1,
    )
    return IssuedAgentToken(
        agent=agent_obj,
        token=parsed.get("token", ""),
        label=parsed.get("label", label or ""),
        expires_at=parsed.get("expires"),
    )


def delete(name: str, *, confirm: bool = True) -> None:
    """Delete an agent registration by name and revoke all active tokens."""
    args = ["agent", "delete", name]
    if confirm:
        args.append("--confirm")
    run(*args)


def list_tokens(agent_name: str) -> list[AgentToken]:
    """List all active tokens for an agent."""
    result = run("agent", "token", "list", agent_name)
    tokens = _parse_token_list(result.stdout)
    for t in tokens:
        # Since the list doesn't output agent_id, populate it with agent_name
        object.__setattr__(t, "agent_id", agent_name)
    return tokens


def issue_token(
    agent_name: str,
    *,
    label: str | None = None,
    expires: str | None = None,
    env: str | None = None,
    save_token: bool = False,
) -> IssuedAgentToken:
    """Issue a new token for an existing agent."""
    args = ["agent", "token", "issue", agent_name]
    if label:
        args.extend(["--label", label])
    if expires:
        args.extend(["--expires", expires])
    if env:
        args.extend(["--env", env])
    if save_token:
        args.append("--save-token")

    result = run(*args)
    parsed = _parse_registration_or_issue(result.stdout)
    
    agent_obj = Agent(name=agent_name)
    return IssuedAgentToken(
        agent=agent_obj,
        token=parsed.get("token", ""),
        label=parsed.get("label", label or ""),
        expires_at=parsed.get("expires"),
    )


def revoke_token(agent_name: str, token_id: str, *, confirm: bool = True) -> None:
    """Revoke a specific token for an agent."""
    args = ["agent", "token", "revoke", token_id, "--agent", agent_name]
    if confirm:
        args.append("--confirm")
    run(*args)


def revoke_all_tokens(agent_name: str, *, confirm: bool = True) -> None:
    """Revoke all tokens for an agent."""
    args = ["agent", "token", "revoke", "--all", "--agent", agent_name]
    if confirm:
        args.append("--confirm")
    run(*args)


def get_policy(agent_name: str) -> AgentCapabilities:
    """Get the capabilities/policy for an agent."""
    result = run("agent", "policy", "get", agent_name)
    return _parse_policy(result.stdout)


def set_policy(
    agent_name: str,
    *,
    allow: list[str] | str | None = None,
    deny: list[str] | str | None = None,
) -> None:
    """Set capabilities/policy for an agent."""
    args = ["agent", "policy", "set", agent_name]
    if allow is not None:
        if not isinstance(allow, str):
            allow = ",".join(allow)
        args.extend(["--allow", allow])
    if deny is not None:
        if not isinstance(deny, str):
            deny = ",".join(deny)
        args.extend(["--deny", deny])
    run(*args)


# ---------------------------------------------------------------------------
# Output Parsers
# ---------------------------------------------------------------------------

def _parse_agent_list(output: str) -> list[Agent]:
    """Parse raw agent list table output."""
    agents: list[Agent] = []
    lines = output.strip().splitlines()
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("AGENT") or line_stripped.startswith("─") or "No agents found" in line_stripped:
            continue
        
        # Fixed-width column parsing matching Go formatting
        name = line[0:20].strip()
        scope = line[20:36].strip()
        tokens_str = line[36:45].strip()
        last_used = line[45:71].strip()
        registered = line[71:].strip()
        
        try:
            token_count = int(tokens_str)
        except ValueError:
            token_count = 0
            
        project_id = None
        if scope and scope != "workspace":
            project_id = scope
            
        agents.append(
            Agent(
                name=name,
                project_id=project_id,
                created_at=registered,
                token_count=token_count,
                last_used=None if last_used == "never" else last_used,
            )
        )
    return agents


def _parse_registration_or_issue(output: str) -> dict[str, str]:
    """Parse registration or token issuance details from CLI output."""
    result: dict[str, str] = {}
    for line in output.splitlines():
        line_stripped = line.strip()
        if not line_stripped:
            continue
        
        # Check standard labels
        for label in ["Name", "Scope", "Token", "Agent", "Expires", "Label"]:
            if line_stripped.startswith(label):
                val = line_stripped[len(label):].strip()
                result[label.lower()] = val
    return result


def _parse_token_list(output: str) -> list[AgentToken]:
    """Parse tokens table output."""
    tokens: list[AgentToken] = []
    lines = output.strip().splitlines()
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("TOKEN ID") or line_stripped.startswith("─") or "No tokens found" in line_stripped:
            continue
        
        # Fixed-width slicing matching Go token list output formatting
        token_id = line[0:20].strip()
        label = line[20:36].strip()
        expires: str | None = line[36:52].strip()
        last_used: str | None = line[52:78].strip()
        status = line[78:].strip()

        if label == "(none)":
            label = ""
        if expires == "(none)":
            expires = None
        if last_used == "never":
            last_used = None
            
        tokens.append(
            AgentToken(
                id=token_id,
                agent_id="",
                label=label,
                created_at="",
                expires_at=expires,
                last_used=last_used,
                status=status or "active",
            )
        )
    return tokens


def _parse_policy(output: str) -> AgentCapabilities:
    """Parse capabilities/policy get output."""
    allowed: list[str] = []
    denied: list[str] = []
    for line in output.splitlines():
        line_stripped = line.strip()
        if line_stripped.startswith("Allowed Secrets:"):
            val = line_stripped[len("Allowed Secrets:"):].strip()
            if val and val != "(none)":
                allowed = [s.strip() for s in val.split(",")]
        elif line_stripped.startswith("Denied Secrets:"):
            val = line_stripped[len("Denied Secrets:"):].strip()
            if val and val != "(none)":
                denied = [s.strip() for s in val.split(",")]
    return AgentCapabilities(allowed_secrets=allowed, denied_secrets=denied)
