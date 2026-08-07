"""Allowlist management sub-client."""

from __future__ import annotations

from .._cli import run
from ..models import AllowlistEntry


class AllowlistClient:
    """Manage the workspace domain allowlist via CLI commands."""

    def list(self) -> list[AllowlistEntry]:
        """List allowed domains for the current workspace."""
        result = run("workspace", "allowlist", "list")
        return _parse_allowlist(result.stdout)

    def add(self, *domains: str) -> None:
        """Add one or more domains to the allowlist."""
        if not domains:
            return
        run("workspace", "allowlist", "add", *domains)

    def remove(self, domain: str) -> None:
        """Remove a domain from the allowlist."""
        run("workspace", "allowlist", "remove", domain)

    def log(self) -> str:
        """View the allowlist audit log (raw CLI output)."""
        result = run("workspace", "allowlist", "log")
        return result.stdout


def _parse_allowlist(output: str) -> list[AllowlistEntry]:
    """Best-effort parse of CLI allowlist output.

    The Go CLI (``runAllowlistList``) renders a ``lipgloss.RoundedBorder()``
    table with columns ``Domain | Added By | Added At``.

    Example (after ANSI stripping)::

        ╭────────────────┬───────────────────┬──────────────────╮
        │ Domain         │ Added By          │ Added At         │
        ├────────────────┼───────────────────┼──────────────────┤
        │ api.stripe.com │ user@example.com  │ 2025-01-15 09:30 │
        ╰────────────────┴───────────────────┴──────────────────╯
    """
    from ._parsing import parse_lipgloss_table

    rows = parse_lipgloss_table(output)
    entries: list[AllowlistEntry] = []

    # Skip the header row (index 0); data rows start at index 1.
    for row in rows[1:]:
        domain = row[0] if len(row) > 0 else ""
        added_by = row[1] if len(row) > 1 else ""
        created_at = row[2] if len(row) > 2 else ""
        if domain:
            entries.append(AllowlistEntry(
                domain=domain,
                added_by=added_by,
                created_at=created_at,
            ))
    return entries

