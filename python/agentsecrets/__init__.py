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

__version__ = "2.0.0"

from .client import AgentSecrets
from .config import settings
from .credential import credential
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
from .interceptor import install_interceptor
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


def init(
    *,
    port: int | None = None,
    workspace: str | None = None,
    project: str | None = None,
    environment: str | None = None,
) -> None:
    """Initializes the AgentSecrets secure credential boundary.
    Configures settings and registers transparent HTTP interception.
    """
    if port is not None:
        settings.port = port
    if workspace is not None:
        settings.workspace = workspace
    if project is not None:
        settings.project = project
    if environment is not None:
        settings.environment = environment

    install_interceptor()

__all__ = [
    # Settings and helper
    "settings",
    "credential",
    "init",
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
