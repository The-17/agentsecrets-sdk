"""Secrets management sub-client."""

from __future__ import annotations

from .._cli import run
from ..models import DiffResult, PushResult, SecretKey, SyncResult


class SecretsClient:
    """Manage secrets via the ``agentsecrets secrets`` CLI commands."""

    def list(self) -> list[SecretKey]:
        """List secret key names in the active project."""
        result = run("secrets", "list")
        return _parse_secret_list(result.stdout)

    def set(self, key: str, value: str) -> None:
        """Set a secret value.

        The value is passed through to the CLI, which writes it to the
        keychain — the SDK does not store it.
        """
        run("secrets", "set", f"{key}={value}")

    def delete(self, key: str) -> None:
        """Delete a secret from both cloud and local keychain."""
        run("secrets", "delete", key)

    def diff(self) -> DiffResult:
        """Compare local keychain secrets with cloud state."""
        result = run("secrets", "diff")
        return _parse_diff(result.stdout)

    def pull(self, *, force: bool = False) -> SyncResult:
        """Pull secrets from cloud to local keychain."""
        args = ["secrets", "pull"]
        if force:
            args.append("--force")
        result = run(*args)
        return SyncResult()  # CLI outputs human text; structured in future

    def push(self, *, force: bool = False) -> PushResult:
        """Push local secrets to cloud."""
        args = ["secrets", "push"]
        if force:
            args.append("--force")
        result = run(*args)
        return PushResult()  # CLI outputs human text; structured in future


def _parse_secret_list(output: str) -> list[SecretKey]:
    """Best-effort parse of CLI secrets list output."""
    keys: list[SecretKey] = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("─") or line.startswith("Key"):
            continue
        parts = line.split()
        if parts:
            keys.append(SecretKey(key=parts[0]))
    return keys


def _parse_diff(output: str) -> DiffResult:
    """Best-effort parse of CLI diff output."""
    # Simplified — the CLI diff output is human-readable text.
    # Full structured parsing will be added with CLI --json support.
    has_drift = "drift" in output.lower() or "added" in output.lower()
    return DiffResult(has_drift=has_drift)
