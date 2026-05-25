from __future__ import annotations

import os


class Settings:
    """Global configuration settings for AgentSecrets SDK.

    Can be set programmatically:
        from agentsecrets import settings
        settings.environment = "staging"  # Automatically switches environment in background
    """
    def __init__(self) -> None:
        self.port = int(os.environ.get("AGENTSECRETS_PORT", 8765))
        self.workspace = os.environ.get("AGENTSECRETS_WORKSPACE")
        self.project = os.environ.get("AGENTSECRETS_PROJECT")
        self._environment = os.environ.get("AGENTSECRETS_ENV") or os.environ.get("AS_ENV")

    @property
    def environment(self) -> str | None:
        return self._environment

    @environment.setter
    def environment(self, value: str) -> None:
        if not value:
            raise ValueError("Environment name cannot be empty")
        if value == self._environment:
            return

        # Trigger background CLI command to switch project environment context
        from ._cli import run as _cli_run
        try:
            _cli_run("environment", "switch", value)
            self._environment = value
        except Exception as e:
            raise ValueError(f"Failed to switch AgentSecrets environment to '{value}': {e}")

settings = Settings()
