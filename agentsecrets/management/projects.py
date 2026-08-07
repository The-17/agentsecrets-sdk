"""Project management sub-client."""

from __future__ import annotations

from .._cli import run
from ..models import Project


class ProjectsClient:
    """Manage projects via the ``agentsecrets project`` CLI commands."""

    def list(self) -> list[Project]:
        """List projects in the current workspace."""
        result = run("project", "list")
        return _parse_project_list(result.stdout)

    def create(self, name: str) -> None:
        """Create a new project in the current workspace."""
        run("project", "create", name)

    def use(self, name: str) -> None:
        """Switch the active project."""
        run("project", "use", name)

    def delete(self, name: str) -> None:
        """Delete a project."""
        run("project", "delete", name)


def _parse_project_list(output: str) -> list[Project]:
    """Best-effort parse of CLI project list output.

    The Go CLI (``runProjectList``) renders a ``lipgloss.RoundedBorder()``
    table with columns ``Project | Workspace | Description``.

    Example (after ANSI stripping)::

        ╭──────────┬───────────┬─────────────╮
        │ Project  │ Workspace │ Description │
        ├──────────┼───────────┼─────────────┤
        │ my-proj  │ personal  │ —           │
        ╰──────────┴───────────┴─────────────╯
    """
    from ._parsing import parse_lipgloss_table

    rows = parse_lipgloss_table(output)
    projects: list[Project] = []

    # Skip the header row (index 0); data rows start at index 1.
    for row in rows[1:]:
        name = row[0] if len(row) > 0 else ""
        # Workspace column is a display name — not the ID.
        description = row[2] if len(row) > 2 else ""
        if description == "—":
            description = ""
        if name:
            projects.append(Project(id="", name=name, description=description))
    return projects

