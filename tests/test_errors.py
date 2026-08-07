"""Tests for the exception hierarchy."""

from __future__ import annotations

import pytest

from agentsecrets.errors import (
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


class TestExceptionHierarchy:
    """All SDK exceptions inherit from AgentSecretsError."""

    @pytest.mark.parametrize("exc_class", [
        AgentSecretsNotRunning,
        CLINotFound,
        ProxyConnectionError,
        SessionExpired,
        DomainNotAllowed,
        UpstreamError,
        PermissionDenied,
        WorkspaceNotFound,
        ProjectNotFound,
        AllowlistModificationDenied,
    ])
    def test_all_inherit_from_base(self, exc_class: type) -> None:
        assert issubclass(exc_class, AgentSecretsError)


class TestFixHints:
    """Actionable errors include a fix_hint."""

    def test_not_running_has_fix(self) -> None:
        exc = AgentSecretsNotRunning(port=8765)
        assert exc.fix_hint == "agentsecrets proxy start"
        assert "8765" in exc.message

    def test_secret_not_found_has_fix(self) -> None:
        exc = SecretNotFound("STRIPE_KEY", "my-project")
        assert "STRIPE_KEY" in exc.fix_hint
        assert "my-project" in exc.message

    def test_domain_not_allowed_has_fix(self) -> None:
        exc = DomainNotAllowed("api.stripe.com")
        assert "api.stripe.com" in exc.fix_hint
        assert "allowlist" in exc.fix_hint

    def test_cli_not_found_has_fix(self) -> None:
        exc = CLINotFound()
        assert exc.fix_hint is not None
        assert "github.com" in exc.fix_hint

    def test_session_expired_has_fix(self) -> None:
        exc = SessionExpired()
        assert exc.fix_hint == "agentsecrets login"


class TestErrorMessages:
    """Error messages are descriptive and actionable."""

    def test_cli_error_includes_command(self) -> None:
        exc = CLIError("secrets list", 1, "not logged in")
        assert "secrets list" in str(exc)
        assert "not logged in" in str(exc)
        assert exc.exit_code == 1

    def test_upstream_error_includes_url(self) -> None:
        exc = UpstreamError(500, "Internal Server Error", "https://api.example.com")
        assert "https://api.example.com" in str(exc)
        assert exc.status_code == 500

    def test_permission_denied_includes_roles(self) -> None:
        exc = PermissionDenied(
            "modify_allowlist",
            required_role="admin",
            current_role="member",
        )
        assert "admin" in str(exc)
        assert "member" in str(exc)

    def test_project_not_found_with_workspace(self) -> None:
        exc = ProjectNotFound("my-project", "my-workspace")
        assert "my-project" in str(exc)
        assert "my-workspace" in str(exc)
