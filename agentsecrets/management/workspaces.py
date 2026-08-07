"""Workspace management sub-client."""

from __future__ import annotations

from .._cli import run
from ..models import Member, Workspace


class WorkspacesClient:
    """Manage workspaces via the ``agentsecrets workspace`` CLI commands."""

    def list(self) -> list[Workspace]:
        """List all workspaces the current user has access to."""
        result = run("workspace", "list")
        # The CLI outputs a formatted table. We return raw text for now;
        # richer parsing can be added once the CLI gains --json support.
        return _parse_workspace_list(result.stdout)

    def create(self, name: str) -> None:
        """Create a new workspace."""
        run("workspace", "create", name)

    def switch(self, name: str) -> None:
        """Switch the active workspace."""
        run("workspace", "switch", name)

    def invite(self, email: str, *, role: str = "member") -> None:
        """Invite a user to the current workspace."""
        run("workspace", "invite", email, "--role", role)

    def remove(self, email: str) -> None:
        """Remove a member from the current workspace."""
        run("workspace", "remove", email)

    def promote(self, email: str) -> None:
        """Promote a member to admin."""
        run("workspace", "promote", email)

    def demote(self, email: str) -> None:
        """Demote an admin to member."""
        run("workspace", "demote", email)

    def members(self) -> list[Member]:
        """List members of the current workspace."""
        result = run("workspace", "members")
        return _parse_member_list(result.stdout)


# ---------------------------------------------------------------------------
# Output parsers — intentionally simple; will improve with CLI --json support
# ---------------------------------------------------------------------------

import re

from ._parsing import strip_ansi

# Matches a parenthesized token like ``(shared)`` or ``(admin)``.
_PAREN_RE = re.compile(r"\(([^)]+)\)")


def _parse_workspace_list(output: str) -> list[Workspace]:
    """Best-effort parse of CLI workspace list output.

    The Go CLI (``runWorkspaceList``) outputs lines like::

        → my-workspace (personal)
          other-workspace (shared)

    with lipgloss ANSI styles applied.
    """
    clean = strip_ansi(output)
    workspaces: list[Workspace] = []
    for line in clean.splitlines():
        line = line.strip()
        if not line or line.startswith("─") or line.startswith("Name") or line.startswith("Workspaces"):
            continue
        # Strip the leading arrow marker (→ or ▸ variants).
        line = line.lstrip("→▸ ").strip()

        paren_match = _PAREN_RE.search(line)
        ws_type = paren_match.group(1) if paren_match else ""
        # The workspace name is everything before the parenthesized type.
        name = _PAREN_RE.sub("", line).strip() if paren_match else line.split()[0] if line.split() else ""

        if name:
            workspaces.append(Workspace(id="", name=name, type=ws_type))
    return workspaces


def _parse_member_list(output: str) -> list[Member]:
    """Best-effort parse of CLI members output.

    The Go CLI (``runWorkspaceMembers``) outputs lines like::

        user@example.com (admin) active
        other@example.com (member) pending

    with lipgloss ANSI styles applied.
    """
    clean = strip_ansi(output)
    members: list[Member] = []
    for line in clean.splitlines():
        line = line.strip()
        if not line or line.startswith("─") or line.startswith("Email") or "Members" in line:
            continue

        parts = line.split()
        if not parts:
            continue

        email = parts[0]
        # Validate it looks like an email.
        if "@" not in email:
            continue

        paren_match = _PAREN_RE.search(line)
        role = paren_match.group(1) if paren_match else ""
        # Status is the token after the closing parenthesis.
        status = ""
        if paren_match:
            after = line[paren_match.end():].strip()
            if after:
                status = after.split()[0]

        members.append(Member(email=email, role=role, status=status))
    return members
