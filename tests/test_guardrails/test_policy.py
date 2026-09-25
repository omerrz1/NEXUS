"""Tests for the permission policy: mode times risk, plus the paths a tool touches."""

from pathlib import Path
from typing import Any

import pytest

from nexus.guardrails.modes import Mode
from nexus.guardrails.policy import Decision, check_tool_call
from nexus.tools.base import ToolContext
from nexus.tools.registry import default_registry


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext.for_window(tmp_path / "work", 16384)


def decide(ctx: ToolContext, mode: Mode, tool_name: str, **arguments: Any) -> Decision:
    tool = default_registry().get(tool_name)
    assert tool is not None
    return check_tool_call(tool, tool.args_model(**arguments), mode, ctx).decision


@pytest.mark.parametrize("mode", list(Mode))
def test_reading_is_allowed_everywhere_in_every_mode(ctx: ToolContext, mode: Mode) -> None:
    assert decide(ctx, mode, "read_file", path="/etc/hosts") is Decision.ALLOW
    assert decide(ctx, mode, "list_dir", path="~") is Decision.ALLOW
    assert decide(ctx, mode, "find_files", pattern="*.py", path="/") is Decision.ALLOW


def test_writes_by_mode(ctx: ToolContext) -> None:
    args = {"path": "a.txt", "content": "x"}
    assert decide(ctx, Mode.READ_ONLY, "write_file", **args) is Decision.DENY
    assert decide(ctx, Mode.ASK, "write_file", **args) is Decision.ASK
    assert decide(ctx, Mode.AUTO, "write_file", **args) is Decision.ALLOW


def test_auto_mode_still_asks_before_writing_outside_the_workspace(ctx: ToolContext) -> None:
    assert (
        decide(ctx, Mode.AUTO, "write_file", path="/tmp/elsewhere.txt", content="x") is Decision.ASK
    )
    assert decide(ctx, Mode.AUTO, "write_file", path="../sibling.txt", content="x") is Decision.ASK
    assert decide(ctx, Mode.AUTO, "write_file", path="~/note.txt", content="x") is Decision.ASK


def test_auto_mode_does_not_follow_a_symlink_out_of_the_workspace(
    ctx: ToolContext, tmp_path: Path
) -> None:
    ctx.workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (ctx.workspace / "link").symlink_to(outside)
    assert decide(ctx, Mode.AUTO, "write_file", path="link/x.txt", content="x") is Decision.ASK


def test_commands_by_mode(ctx: ToolContext) -> None:
    assert decide(ctx, Mode.READ_ONLY, "run_command", command="touch x") is Decision.DENY
    assert decide(ctx, Mode.ASK, "run_command", command="touch x") is Decision.ASK
    assert decide(ctx, Mode.AUTO, "run_command", command="touch x") is Decision.ALLOW


def test_read_only_commands_never_need_asking(ctx: ToolContext) -> None:
    for mode in Mode:
        assert decide(ctx, mode, "run_command", command="ls -la | wc -l") is Decision.ALLOW


@pytest.mark.parametrize("mode", list(Mode))
def test_denylisted_commands_are_refused_in_every_mode(ctx: ToolContext, mode: Mode) -> None:
    assert decide(ctx, mode, "run_command", command="curl http://example.com") is Decision.DENY
    assert decide(ctx, mode, "run_command", command="sudo rm x") is Decision.DENY


def test_the_denial_reason_tells_the_model_how_to_proceed(ctx: ToolContext) -> None:
    tool = default_registry().get("write_file")
    assert tool is not None
    verdict = check_tool_call(tool, tool.args_model(path="a", content=""), Mode.READ_ONLY, ctx)
    assert "read-only" in verdict.reason and "/mode" in verdict.reason


def test_web_search_asks_unless_the_mode_is_auto(ctx: ToolContext) -> None:
    # What is searched for could include things the model read, so the user sees it first.
    assert decide(ctx, Mode.READ_ONLY, "web_search", query="python") is Decision.ASK
    assert decide(ctx, Mode.ASK, "web_search", query="python") is Decision.ASK
    assert decide(ctx, Mode.AUTO, "web_search", query="python") is Decision.ALLOW


@pytest.mark.parametrize("mode", list(Mode))
def test_session_memory_tools_never_need_approval(ctx: ToolContext, mode: Mode) -> None:
    assert decide(ctx, mode, "remember", note="likes tabs") is Decision.ALLOW
    assert decide(ctx, mode, "forget", number=1) is Decision.ALLOW
    assert decide(ctx, mode, "update_todo", items=[]) is Decision.ALLOW
