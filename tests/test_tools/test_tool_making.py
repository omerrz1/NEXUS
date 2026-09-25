"""Tests for create_tool and delete_tool: how Nexus makes, changes, and removes its own tools."""

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nexus.guardrails.modes import Mode
from nexus.guardrails.policy import Decision, check_tool_call
from nexus.tools.base import Risk, Tool, ToolContext, ToolResult
from nexus.tools.custom.library import ToolLibrary
from nexus.tools.custom.script_tool import ScriptTool
from nexus.tools.registry import ToolRegistry, default_registry

CODE = "import json, sys\nprint(len(json.load(sys.stdin)['text'].split()))\n"


@pytest.fixture
def library(tmp_path: Path) -> ToolLibrary:
    return ToolLibrary(tmp_path / "tools")


@pytest.fixture
def registry(library: ToolLibrary) -> ToolRegistry:
    return default_registry(library=library)


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    (tmp_path / "work").mkdir()
    return ToolContext.for_window(tmp_path / "work", 16384)


def tool_named(registry: ToolRegistry, name: str) -> Tool[Any]:
    tool = registry.get(name)
    assert tool is not None
    return tool


def create(registry: ToolRegistry, ctx: ToolContext, **overrides: Any) -> ToolResult:
    arguments: dict[str, Any] = {
        "name": "word_count",
        "description": "Count the words in some text.",
        "parameters": {"text": "the text to count"},
        "code": CODE,
    }
    arguments.update(overrides)
    tool = tool_named(registry, "create_tool")
    return tool.run(tool.args_model(**arguments), ctx)


# ---- create_tool


def test_a_new_tool_can_be_used_straight_away(registry: ToolRegistry, ctx: ToolContext) -> None:
    result = create(registry, ctx)
    assert result.ok and "Created the tool word_count." in result.output
    assert 'call it directly as word_count(text="...")' in result.output

    made = tool_named(registry, "word_count")
    assert isinstance(made, ScriptTool)
    assert made.run(made.args_model(text="one two three"), ctx).output == "3"
    assert "word_count" in [spec.name for spec in registry.specs()]


def test_the_new_tool_is_saved_so_the_next_session_has_it(
    registry: ToolRegistry, library: ToolLibrary, ctx: ToolContext
) -> None:
    create(registry, ctx)
    assert library.read_script("word_count") == CODE
    assert [tool.name for tool in library.load_all().tools] == ["word_count"]


def test_replacing_a_tool_changes_it_everywhere(
    registry: ToolRegistry, library: ToolLibrary, ctx: ToolContext
) -> None:
    create(registry, ctx)
    result = create(
        registry,
        ctx,
        description="Count lines instead.",
        code="import sys\nprint(sys.stdin.read().count('n'))\n",
    )
    assert result.output.startswith("Replaced the tool word_count")
    assert registry.names().count("word_count") == 1
    assert tool_named(registry, "word_count").description == "Count lines instead."
    assert "count('n')" in (library.read_script("word_count") or "")


def test_a_tool_can_have_no_inputs(registry: ToolRegistry, ctx: ToolContext) -> None:
    result = create(registry, ctx, name="say_hello", parameters={}, code="print('hello')\n")
    assert result.ok and "call it directly as say_hello()" in result.output
    made = tool_named(registry, "say_hello")
    assert made.run(made.args_model(), ctx).output == "hello"


def test_there_is_a_limit_on_how_many_tools_can_be_made_but_replacing_is_always_allowed(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    for number in range(12):
        assert create(registry, ctx, name=f"tool_{number:02d}", parameters={}).ok
    refused = create(registry, ctx, name="one_too_many", parameters={})
    assert not refused.ok and "already have 12 tools you made" in refused.output
    assert registry.get("one_too_many") is None

    assert create(registry, ctx, name="tool_05", parameters={}, description="Changed.").ok
    delete = tool_named(registry, "delete_tool")
    delete.run(delete.args_model(name="tool_00"), ctx)
    assert create(registry, ctx, name="one_too_many", parameters={}).ok  # room again


def test_a_built_in_tool_cannot_be_replaced(
    registry: ToolRegistry, library: ToolLibrary, ctx: ToolContext
) -> None:
    original = tool_named(registry, "read_file")
    result = create(registry, ctx, name="read_file", code="print('fake')\n")
    assert not result.ok and "built-in tool" in result.output
    assert tool_named(registry, "read_file") is original
    assert library.read_script("read_file") is None  # nothing was written


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"name": "Bad Name"}, "name"),
        ({"name": "../escape"}, "name"),
        ({"description": ""}, "description"),
        ({"parameters": {"json": "clashes"}}, "reserved"),
        ({"code": ""}, "code is empty"),
        ({"code": "print('unclosed"}, "syntax error on line 1"),
        ({"code": "x = 1\ndef broken(:\n    pass\n"}, "syntax error on line 2"),
        ({"code": "x" * 20_001}, "at most 20000"),
    ],
)
def test_a_bad_tool_is_refused_with_a_message_before_the_user_is_asked(
    registry: ToolRegistry, overrides: dict[str, Any], expected: str
) -> None:
    tool = tool_named(registry, "create_tool")
    arguments: dict[str, Any] = {
        "name": "word_count",
        "description": "Count words.",
        "parameters": {"text": "meaning"},
        "code": CODE,
    }
    arguments.update(overrides)
    with pytest.raises(ValidationError, match=expected):
        tool.args_model(**arguments)


def test_the_preview_shows_a_new_script_and_says_it_will_run_with_the_users_permissions(
    registry: ToolRegistry, library: ToolLibrary, ctx: ToolContext
) -> None:
    tool = tool_named(registry, "create_tool")
    preview = tool.preview(
        tool.args_model(
            name="word_count",
            description="Count the words in some text.",
            parameters={"text": "what to count"},
            code=CODE,
        ),
        ctx,
    )
    assert preview is not None
    assert preview.title == "Create the tool word_count"
    assert preview.before is None and preview.after == CODE and preview.is_file_change
    assert preview.path == str(library.script_path("word_count"))
    assert "Count the words in some text." in preview.body and "Inputs: text" in preview.body
    assert "with your permissions" in preview.body


def test_replacing_a_tool_previews_a_diff_against_its_current_script(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    create(registry, ctx)
    tool = tool_named(registry, "create_tool")
    preview = tool.preview(
        tool.args_model(name="word_count", description="Changed.", code="print('new')\n"), ctx
    )
    assert preview is not None and preview.title == "Replace the tool word_count"
    assert preview.before == CODE and preview.after == "print('new')\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores folder permissions")
def test_a_tool_that_cannot_be_saved_is_reported_and_not_registered(
    registry: ToolRegistry, library: ToolLibrary, ctx: ToolContext, tmp_path: Path
) -> None:
    locked = tmp_path / "tools"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        result = create(registry, ctx)
    finally:
        locked.chmod(0o700)
    assert not result.ok and "Could not save the tool" in result.output
    assert registry.get("word_count") is None


# ---- delete_tool


def test_deleting_removes_the_tool_from_the_model_and_from_disk(
    registry: ToolRegistry, library: ToolLibrary, ctx: ToolContext
) -> None:
    create(registry, ctx)
    tool = tool_named(registry, "delete_tool")
    result = tool.run(tool.args_model(name="word_count"), ctx)
    assert result.ok and "Deleted the tool word_count" in result.output
    assert registry.get("word_count") is None
    assert "word_count" not in [spec.name for spec in registry.specs()]
    assert library.read_script("word_count") is None


def test_a_built_in_tool_cannot_be_deleted(registry: ToolRegistry, ctx: ToolContext) -> None:
    create(registry, ctx)
    tool = tool_named(registry, "delete_tool")
    result = tool.run(tool.args_model(name="read_file"), ctx)
    assert not result.ok and "no tool you made called 'read_file'" in result.output
    assert "Tools you made: word_count" in result.output
    assert registry.get("read_file") is not None


def test_deleting_when_nothing_was_made_says_so(registry: ToolRegistry, ctx: ToolContext) -> None:
    tool = tool_named(registry, "delete_tool")
    result = tool.run(tool.args_model(name="anything"), ctx)
    assert not result.ok and "Tools you made: none yet" in result.output


def test_deleting_previews_the_script_that_will_be_lost(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    create(registry, ctx)
    tool = tool_named(registry, "delete_tool")
    preview = tool.preview(tool.args_model(name="word_count"), ctx)
    assert preview is not None and preview.title == "Delete the tool word_count"
    assert preview.before == CODE and preview.after == ""
    assert "cannot be undone" in preview.body


# ---- the guardrails around changing Nexus itself


@pytest.mark.parametrize("name", ["create_tool", "delete_tool"])
def test_making_or_deleting_tools_asks_in_every_mode_even_auto(
    registry: ToolRegistry, ctx: ToolContext, name: str
) -> None:
    tool = tool_named(registry, name)
    args = tool.args_model(
        **(
            {"name": "x_tool"}
            if name == "delete_tool"
            else {"name": "x_tool", "description": "d", "code": "pass\n"}
        )
    )
    assert tool.always_ask and tool.risk is Risk.WRITE
    assert check_tool_call(tool, args, Mode.ASK, ctx).decision is Decision.ASK
    assert check_tool_call(tool, args, Mode.AUTO, ctx).decision is Decision.ASK
    denied = check_tool_call(tool, args, Mode.READ_ONLY, ctx)
    assert denied.decision is Decision.DENY and "read-only" in denied.reason


@pytest.mark.parametrize("name", ["create_tool", "delete_tool"])
def test_approving_one_change_can_never_approve_the_next(
    registry: ToolRegistry, ctx: ToolContext, name: str
) -> None:
    tool = tool_named(registry, name)
    args = tool.args_model(
        **(
            {"name": "x_tool"}
            if name == "delete_tool"
            else {"name": "x_tool", "description": "d", "code": "pass\n"}
        )
    )
    assert tool.grant_scope(args, ctx) == ""  # no "always" choice is offered


def test_using_a_made_tool_is_judged_like_a_command(
    registry: ToolRegistry, ctx: ToolContext
) -> None:
    create(registry, ctx)
    made = tool_named(registry, "word_count")
    args = made.args_model(text="hello")
    assert check_tool_call(made, args, Mode.ASK, ctx).decision is Decision.ASK
    assert check_tool_call(made, args, Mode.AUTO, ctx).decision is Decision.ALLOW
    assert check_tool_call(made, args, Mode.READ_ONLY, ctx).decision is Decision.DENY
