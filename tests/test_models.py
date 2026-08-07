"""Tests for the data models."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from agentsecrets.models import (
    AgentSecretsResponse,
    AllowlistEntry,
    AuditEvent,
    DiffResult,
    Member,
    Project,
    SecretKey,
    SpawnResult,
    Workspace,
)


class TestAgentSecretsResponse:
    """The core response model."""

    def test_has_no_value_field(self) -> None:
        """Zero-knowledge: the response structurally cannot carry a credential."""
        resp = AgentSecretsResponse(
            status_code=200,
            headers={"Content-Type": "application/json"},
            body=b'{"ok": true}',
        )
        assert not hasattr(resp, "value")

    def test_json_parsing(self) -> None:
        body = json.dumps({"amount": 1000}).encode()
        resp = AgentSecretsResponse(status_code=200, headers={}, body=body)
        assert resp.json() == {"amount": 1000}

    def test_text_property(self) -> None:
        resp = AgentSecretsResponse(status_code=200, headers={}, body=b"hello")
        assert resp.text == "hello"

    def test_frozen(self) -> None:
        resp = AgentSecretsResponse(status_code=200, headers={}, body=b"")
        with pytest.raises(AttributeError):
            resp.status_code = 500  # type: ignore[misc]


class TestAuditEvent:
    """The audit log entry model."""

    def test_has_no_value_field(self) -> None:
        """Zero-knowledge: audit events never carry credential values."""
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc),
            secret_keys=["STRIPE_KEY"],
            method="POST",
            target_url="https://api.stripe.com/v1/charges",
            auth_styles=["bearer"],
            status_code=200,
            duration_ms=342,
            status="OK",
        )
        assert not hasattr(event, "value")
        assert not hasattr(event, "secret_value")

    def test_frozen(self) -> None:
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc),
            secret_keys=[],
            method="GET",
            target_url="",
            auth_styles=[],
            status_code=200,
            duration_ms=0,
            status="OK",
        )
        with pytest.raises(AttributeError):
            event.status_code = 500  # type: ignore[misc]

    def test_extended_fields_default(self) -> None:
        """New fields added for Go compatibility default correctly."""
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc),
            secret_keys=[],
            method="GET",
            target_url="",
            auth_styles=[],
            status_code=200,
            duration_ms=0,
            status="OK",
        )
        assert event.id == ""
        assert event.environment == ""
        assert event.identity_level == ""
        assert event.resolution_path == ""
        assert event.caller_role == ""
        assert event.workspace_id == ""
        assert event.project_id == ""
        assert event.token_id == ""

    def test_extended_fields_populated(self) -> None:
        """New fields can be populated explicitly."""
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc),
            secret_keys=["KEY_1"],
            method="POST",
            target_url="https://api.example.com",
            auth_styles=["bearer"],
            status_code=200,
            duration_ms=100,
            status="OK",
            id="evt-abc123",
            environment="production",
            identity_level="agent",
            caller_role="admin",
            workspace_id="ws-456",
            project_id="proj-789",
        )
        assert event.id == "evt-abc123"
        assert event.environment == "production"
        assert event.identity_level == "agent"
        assert event.caller_role == "admin"
        assert event.workspace_id == "ws-456"
        assert event.project_id == "proj-789"


class TestOtherModels:
    """Smoke tests for remaining models."""

    def test_secret_key_has_no_value_field(self) -> None:
        key = SecretKey(key="API_KEY")
        assert not hasattr(key, "value")

    def test_workspace_creation(self) -> None:
        ws = Workspace(id="ws-123", name="My Workspace", type="team", role="admin")
        assert ws.name == "My Workspace"
        assert ws.type == "team"
        assert ws.role == "admin"

    def test_workspace_defaults(self) -> None:
        ws = Workspace(id="ws-1", name="minimal")
        assert ws.type == ""
        assert ws.role == ""

    def test_project_creation(self) -> None:
        proj = Project(id="proj-1", name="api-keys", workspace_id="ws-1", description="API keys")
        assert proj.name == "api-keys"
        assert proj.workspace_id == "ws-1"
        assert proj.description == "API keys"

    def test_project_defaults(self) -> None:
        proj = Project(id="", name="minimal")
        assert proj.workspace_id == ""
        assert proj.description == ""

    def test_member_creation(self) -> None:
        m = Member(email="user@example.com", role="admin", status="active", user_id="uid-1", id="mid-1")
        assert m.email == "user@example.com"
        assert m.role == "admin"
        assert m.status == "active"
        assert m.user_id == "uid-1"
        assert m.id == "mid-1"

    def test_member_defaults(self) -> None:
        m = Member(email="user@example.com", role="member")
        assert m.status == ""
        assert m.user_id == ""
        assert m.id == ""

    def test_allowlist_entry_creation(self) -> None:
        entry = AllowlistEntry(
            domain="api.stripe.com",
            added_by="admin@example.com",
            created_at="2025-01-15",
        )
        assert entry.domain == "api.stripe.com"
        assert entry.added_by == "admin@example.com"
        assert entry.created_at == "2025-01-15"

    def test_allowlist_entry_defaults(self) -> None:
        entry = AllowlistEntry(domain="api.openai.com")
        assert entry.added_by == ""
        assert entry.created_at == ""

    def test_diff_result_defaults(self) -> None:
        diff = DiffResult(has_drift=False)
        assert diff.local_only == []
        assert diff.remote_only == []

    def test_spawn_result_defaults(self) -> None:
        result = SpawnResult(exit_code=0)
        assert result.stdout == ""
        assert result.stderr == ""

