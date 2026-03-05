"""AgentSecrets Python SDK.

::

    from agentsecrets import AgentSecrets

    client = AgentSecrets()
    response = client.call(
        "https://api.stripe.com/v1/charges",
        method="POST",
        bearer="STRIPE_SECRET_KEY",
        body={"amount": 1000, "currency": "usd"},
    )
"""

__version__ = "1.2.2"

from .client import AgentSecrets
from .errors import (
    AgentSecretsError,
    AgentSecretsNotRunning,
    AllowlistModificationDenied,
    CLIError,
    CLINotFound,
    DomainNotAllowed,
    PermissionDenied,
    ProjectNotFound,
    ProxyConnectionError,
    SecretNotFound,
    SessionExpired,
    UpstreamError,
    WorkspaceNotFound,
)
from .models import (
    AgentSecretsResponse,
    AllowlistEntry,
    AllowlistEvent,
    AuditEvent,
    DiffResult,
    Member,
    Project,
    ProxyStatus,
    PushResult,
    SecretKey,
    SpawnResult,
    StatusResult,
    SyncResult,
    Workspace,
)

__all__ = [
    # Client
    "AgentSecrets",
    # Errors
    "AgentSecretsError",
    "AgentSecretsNotRunning",
    "AllowlistModificationDenied",
    "CLIError",
    "CLINotFound",
    "DomainNotAllowed",
    "PermissionDenied",
    "ProjectNotFound",
    "ProxyConnectionError",
    "SecretNotFound",
    "SessionExpired",
    "UpstreamError",
    "WorkspaceNotFound",
    # Models
    "AgentSecretsResponse",
    "AllowlistEntry",
    "AllowlistEvent",
    "AuditEvent",
    "DiffResult",
    "Member",
    "Project",
    "ProxyStatus",
    "PushResult",
    "SecretKey",
    "SpawnResult",
    "StatusResult",
    "SyncResult",
    "Workspace",
]
