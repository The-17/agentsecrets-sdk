"""Tests for CLI output parsers.

Covers workspace list, member list, project list, and allowlist parsers
with both plain text and lipgloss-styled (ANSI + box-drawing) output.
"""

from __future__ import annotations

from agentsecrets.management._parsing import parse_lipgloss_table, strip_ansi
from agentsecrets.management.workspaces import _parse_workspace_list, _parse_member_list
from agentsecrets.management.projects import _parse_project_list
from agentsecrets.management.allowlist import _parse_allowlist


class TestStripAnsi:
    """strip_ansi should remove all ANSI escape sequences."""

    def test_removes_color_codes(self) -> None:
        styled = "\x1b[38;5;212mhello\x1b[0m"
        assert strip_ansi(styled) == "hello"

    def test_preserves_plain_text(self) -> None:
        assert strip_ansi("hello world") == "hello world"

    def test_preserves_unicode(self) -> None:
        assert strip_ansi("╭──╮") == "╭──╮"


class TestParseLipglossTable:
    """parse_lipgloss_table should extract header + data rows."""

    TABLE = (
        "╭──────────┬───────────┬─────────────╮\n"
        "│ Project  │ Workspace │ Description │\n"
        "├──────────┼───────────┼─────────────┤\n"
        "│ my-proj  │ personal  │ My project  │\n"
        "│ demo     │ team      │ —           │\n"
        "╰──────────┴───────────┴─────────────╯\n"
    )

    def test_extracts_rows(self) -> None:
        rows = parse_lipgloss_table(self.TABLE)
        assert len(rows) == 3  # 1 header + 2 data
        assert rows[0] == ["Project", "Workspace", "Description"]
        assert rows[1] == ["my-proj", "personal", "My project"]
        assert rows[2] == ["demo", "team", "—"]

    def test_empty_input(self) -> None:
        assert parse_lipgloss_table("") == []

    def test_ansi_codes_stripped(self) -> None:
        styled = "│ \x1b[1mBold\x1b[0m │ \x1b[2mDim\x1b[0m │\n"
        rows = parse_lipgloss_table(styled)
        assert rows == [["Bold", "Dim"]]


class TestParseWorkspaceList:
    """Workspace list parser should extract name and type."""

    def test_plain_text(self) -> None:
        output = (
            "\n"
            "Workspaces\n"
            "  ──────────────────────────────\n"
            "→ my-workspace (personal)\n"
            "  team-workspace (shared)\n"
            "\n"
        )
        result = _parse_workspace_list(output)
        assert len(result) == 2
        assert result[0].name == "my-workspace"
        assert result[0].type == "personal"
        assert result[1].name == "team-workspace"
        assert result[1].type == "shared"

    def test_ansi_styled(self) -> None:
        output = (
            "\x1b[1;36m→ \x1b[0m \x1b[37mmy-ws\x1b[0m \x1b[2m(personal)\x1b[0m\n"
        )
        result = _parse_workspace_list(output)
        assert len(result) == 1
        assert result[0].name == "my-ws"
        assert result[0].type == "personal"

    def test_empty_output(self) -> None:
        assert _parse_workspace_list("") == []

    def test_no_type(self) -> None:
        output = "  simple-ws\n"
        result = _parse_workspace_list(output)
        assert len(result) == 1
        assert result[0].name == "simple-ws"
        assert result[0].type == ""


class TestParseMemberList:
    """Member list parser should extract email, role, and status."""

    def test_plain_text(self) -> None:
        output = (
            "\n"
            "👥 Workspace Members\n"
            "  ──────────────────────────────\n"
            "  admin@example.com (admin) active\n"
            "  user@example.com (member) pending\n"
            "\n"
        )
        result = _parse_member_list(output)
        assert len(result) == 2
        assert result[0].email == "admin@example.com"
        assert result[0].role == "admin"
        assert result[0].status == "active"
        assert result[1].email == "user@example.com"
        assert result[1].role == "member"
        assert result[1].status == "pending"

    def test_skips_non_email_lines(self) -> None:
        output = (
            "Some Header\n"
            "not-an-email\n"
            "  real@test.com (owner) active\n"
        )
        result = _parse_member_list(output)
        assert len(result) == 1
        assert result[0].email == "real@test.com"

    def test_empty_output(self) -> None:
        assert _parse_member_list("") == []


class TestParseProjectList:
    """Project list parser should extract from lipgloss tables."""

    def test_lipgloss_table(self) -> None:
        output = (
            "\n"
            "Your Projects\n"
            "╭──────────┬───────────┬─────────────╮\n"
            "│ Project  │ Workspace │ Description │\n"
            "├──────────┼───────────┼─────────────┤\n"
            "│ api-keys │ personal  │ API keys    │\n"
            "│ demo     │ team      │ —           │\n"
            "╰──────────┴───────────┴─────────────╯\n"
            "\n"
        )
        result = _parse_project_list(output)
        assert len(result) == 2
        assert result[0].name == "api-keys"
        assert result[0].description == "API keys"
        assert result[1].name == "demo"
        assert result[1].description == ""  # "—" maps to empty

    def test_empty_output(self) -> None:
        assert _parse_project_list("") == []


class TestParseAllowlist:
    """Allowlist parser should extract domain, added_by, and created_at."""

    def test_lipgloss_table(self) -> None:
        output = (
            "\n"
            "Workspace Allowlist\n"
            "╭────────────────┬───────────────────┬──────────────────╮\n"
            "│ Domain         │ Added By          │ Added At         │\n"
            "├────────────────┼───────────────────┼──────────────────┤\n"
            "│ api.stripe.com │ admin@example.com │ 2025-01-15 09:30 │\n"
            "│ api.openai.com │ user@example.com  │ 2025-02-20 14:00 │\n"
            "╰────────────────┴───────────────────┴──────────────────╯\n"
            "\n"
        )
        result = _parse_allowlist(output)
        assert len(result) == 2
        assert result[0].domain == "api.stripe.com"
        assert result[0].added_by == "admin@example.com"
        assert result[0].created_at == "2025-01-15 09:30"
        assert result[1].domain == "api.openai.com"
        assert result[1].added_by == "user@example.com"

    def test_empty_output(self) -> None:
        assert _parse_allowlist("") == []
