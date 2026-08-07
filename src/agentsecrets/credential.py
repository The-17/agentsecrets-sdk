from __future__ import annotations


class CredentialHelper:
    """Helper to dynamically generate zero-knowledge secret placeholders.

    Usage:
        from agentsecrets import credential
        token = credential.GITHUB_TOKEN  # returns "AS_SECRET_GITHUB_TOKEN"
    """

    def __getattr__(self, name: str) -> str:
        return f"AS_SECRET_{name}"

    def __getitem__(self, name: str) -> str:
        return f"AS_SECRET_{name}"

    def get(self, name: str, default: str | None = None) -> str | None:
        return f"AS_SECRET_{name}"

credential = CredentialHelper()
