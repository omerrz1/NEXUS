"""Tests for the CLI's everyday polish: help, plan card, context meter, tool-call lines."""

import io
from pathlib import Path
from typing import Any

import pytest
from prompt_toolkit.formatted_text import to_plain_text
from rich.console import Console

from nexus.brain.base import BrainReply
from nexus.brain.mock import MockBrain
from nexus.cli.agent_events import EventPrinter
from nexus.cli.prompt import _status_bar
from nexus.cli.render import CliRenderer
from nexus.cli.repl import _run_agent_turn
from nexus.cli.session_commands import attach_session, open_session
from nexus.cli.slash import HELP_GROUPS, SLASH_COMMANDS, handle_slash_command
from nexus.cli.status import context_meter
from nexus.cli.theme import ERROR, OK, WARN
from nexus.cli.todo_view import todo_progress, todo_text
from nexus.loop.events import ModelFinished, ToolFinished
from nexus.messages import Message, ToolCall, Usage
from nexus.session.memory import SessionMemory, TodoItem, TodoStatus
from nexus.tools.base import ToolResult
from tests.helpers import make_deps


def plain(width: int = 100) -> tuple[Console, io.StringIO]:
    output = io.StringIO()
    return Console(file=output, width=width, force_terminal=False, color_system=None), output


# ---- /help


def test_every_command_is_in_exactly_one_help_group() -> None:
    grouped = [name for _, names in HELP_GROUPS for name in names]
    assert sorted(grouped) == sorted(command.name for command in SLASH_COMMANDS)


def test_help_shows_groups_and_the_bracketed_usage_hints() -> None:
    console, output = plain()
    handle_slash_command("/help", {}, console)
    text = output.getvalue()
    for title, _ in HELP_GROUPS:
        assert title in text
    # Square brackets used to vanish because Rich read them as markup.
    for usage in ("/depth [level]", "/resume [number|id]", "/memory [add|forget]", "/save [file]"):
        assert usage in text
    assert "(or /quit)" in text and "(or /export)" in text


# ---- the plan checklist


def test_the_todo_list_reads_as_a_checklist_and_shows_brackets_literally() -> None:
    items = [
        TodoItem("read [the] config", TodoStatus.DONE),
        TodoItem("fix it", TodoStatus.IN_PROGRESS),
        TodoItem("test it"),
    ]
    assert todo_text(items).plain.splitlines() == [
        "  ✔ read [the] config",
        "  ◐ fix it",
        "  ○ test it",
    ]
    assert todo_progress(items) == "1 of 3 done"
    assert todo_progress([]) == "0 of 0 done"


def printer_with_memory() -> tuple[EventPrinter, SessionMemory, io.StringIO]:
    console, output = plain()
    memory = SessionMemory()
    return EventPrinter(CliRenderer(console), memory), memory, output


def todo_finished(ok: bool = True) -> ToolFinished:
    call = ToolCall("1", "update_todo", {"items": []})
    return ToolFinished(call, ToolResult(ok, "Todo list saved:\n1. [done] x"))


def test_updating_the_todo_list_shows_a_plan_card_not_the_raw_reply() -> None:
    printer, memory, output = printer_with_memory()
    memory.set_todo([TodoItem("read", TodoStatus.DONE), TodoItem("write", TodoStatus.IN_PROGRESS)])
    printer(todo_finished())
    text = output.getvalue()
    assert "☰ Plan" in text and "1 of 2 done" in text and "✔ read" in text and "◐ write" in text
    assert "Todo list saved" not in text


def test_clearing_the_todo_list_says_so() -> None:
    printer, _, output = printer_with_memory()
    printer(todo_finished())
    assert "Plan cleared." in output.getvalue()


def test_a_failed_todo_update_shows_the_error_as_usual() -> None:
    printer, memory, output = printer_with_memory()
    memory.set_todo([TodoItem("x")])
    call = ToolCall("1", "update_todo", {})
    printer(ToolFinished(call, ToolResult.error("Invalid arguments for update_todo")))
    assert "Invalid arguments" in output.getvalue() and "☰ Plan" not in output.getvalue()


def test_without_a_memory_the_todo_reply_is_shown_as_it_is() -> None:
    console, output = plain()
    EventPrinter(CliRenderer(console))(todo_finished())
    assert "Todo list saved" in output.getvalue()


# ---- the context meter


@pytest.mark.parametrize(
    ("used", "percent", "color"),
    [(0, 0, OK), (5000, 31, OK), (9800, 60, WARN), (13000, 79, WARN), (14000, 85, ERROR)],
)
def test_the_meter_turns_amber_then_red_as_the_window_fills(
    used: int, percent: int, color: str
) -> None:
    assert context_meter(used, 16384) == (percent, color)


def test_the_meter_copes_with_no_window() -> None:
    assert context_meter(100, 0) == (0, OK)


def test_the_status_bar_shows_the_context_share() -> None:
    session: dict[str, Any] = {
        "model": "m",
        "mode": "ask",
        "depth": "fast",
        "tokens": 1234,
        "context_used": 8192,
        "context_window": 16384,
    }
    assert "context 50%" in to_plain_text(_status_bar(session))


def test_the_printer_learns_the_real_context_size_from_the_server_counts() -> None:
    printer, _, _ = printer_with_memory()
    printer(ModelFinished(Usage(prompt_tokens=4000, completion_tokens=120, total_tokens=4120)))
    assert printer.context_tokens == 4120
    printer(ModelFinished(Usage()))  # a reply the server did not count keeps the last number
    assert printer.context_tokens == 4120


def test_a_turn_updates_the_meter_from_the_servers_count(tmp_path: Path) -> None:
    (tmp_path / "w").mkdir()
    reply = BrainReply(Message.assistant("hi"), (), Usage(3000, 40, 3040))
    deps = make_deps(tmp_path / "w", MockBrain(responder=lambda messages: reply))
    session, _ = open_session(deps, None, None)
    context: dict[str, Any] = {"deps": deps, "store": None, "mode": "ask", "depth": "balanced"}
    attach_session(context, session)
    before = context["context_used"]
    console, _ = plain()

    _run_agent_turn("hello", deps, CliRenderer(console), context)

    assert context["context_used"] == 3040 and before != 3040


def test_a_fresh_session_starts_with_an_estimate_that_counts_the_tool_specs(
    tmp_path: Path,
) -> None:
    (tmp_path / "w").mkdir()
    deps = make_deps(tmp_path / "w")
    session, _ = open_session(deps, None, None)
    context: dict[str, Any] = {"deps": deps}
    attach_session(context, session)
    assert context["context_used"] > 1000  # the system prompt plus every tool's schema


def test_stats_include_how_full_the_window_is() -> None:
    console, output = plain()
    context = {"turns": 2, "tokens": 900, "context_used": 4096, "context_window": 16384}
    handle_slash_command("/stats", context, console)
    assert "4,096 of 16,384 tokens (25%)" in output.getvalue()


# ---- tool-call lines


def call_line(name: str, arguments: dict[str, Any]) -> str:
    console, output = plain(width=90)
    CliRenderer(console).print_tool_call(name, arguments)
    return output.getvalue().strip()


def test_the_main_argument_needs_no_label_and_long_text_becomes_a_line_count() -> None:
    assert call_line("write_file", {"path": "a.py", "content": "x\ny\nz"}) == (
        "⚙ write_file  a.py  content=3 lines"
    )
    with_offset = call_line("read_file", {"path": "a.py", "offset": 200})
    assert with_offset == "⚙ read_file  a.py  offset=200"
    assert call_line("run_command", {"command": "ls -la"}) == "⚙ run_command  ls -la"


def test_a_write_reports_the_short_path(tmp_path: Path) -> None:
    from nexus.tools.base import ToolContext
    from nexus.tools.registry import default_registry

    ctx = ToolContext.for_window(tmp_path, 16384)
    tool = default_registry().get("write_file")
    assert tool is not None
    result = tool.run(tool.args_model(path="src/new/file.py", content="a\nb\n"), ctx)
    assert result.output == "Created src/new/file.py (2 lines)."


def test_a_trailing_newline_does_not_add_a_line_to_the_count() -> None:
    def content_part(content: str) -> str:
        return call_line("write_file", {"path": "a.py", "content": content}).split("  ")[-1]

    assert content_part("print(1)\n") == "content=print(1)"  # one line: shown as it is
    assert content_part("a\nb\n") == "content=2 lines"
    assert content_part("a\nb") == "content=2 lines"
    assert content_part("a\n\n\nb") == "content=4 lines"


def test_long_folders_keep_the_part_that_tells_projects_apart() -> None:
    from nexus.cli.session_commands import _short_folder

    home = str(Path.home())
    assert _short_folder(f"{home}/proj") == "~/proj"
    assert _short_folder("/short/path") == "/short/path"
    long_folder = "/private/tmp/claude-501/-Users-someone-projects/scratchpad/e2e"
    assert _short_folder(long_folder) == "…/scratchpad/e2e"
    assert (
        _short_folder("/" + "x" * 80).startswith("…") and len(_short_folder("/" + "x" * 80)) == 28
    )


def test_tools_that_nexus_made_are_marked_in_the_tool_list(tmp_path: Path) -> None:
    from nexus.tools.custom.library import ToolLibrary
    from nexus.tools.custom.manifest import ToolManifest
    from nexus.tools.registry import default_registry

    library = ToolLibrary(tmp_path / "tools")
    registry = default_registry(library=library)
    registry.register(library.save(ToolManifest("word_count", "Count [words].", {}), "pass\n"))
    console, output = plain(width=120)
    handle_slash_command("/tools", {"tools": registry}, console)
    lines = output.getvalue().splitlines()
    made = next(line for line in lines if "word_count" in line)
    assert "(made by Nexus)" in made and "Count [words]." in made
    assert "(made by Nexus)" not in next(line for line in lines if "read_file" in line)


def test_startup_builds_the_registry_around_the_library_it_is_given(tmp_path: Path) -> None:
    from nexus.brain.openai_compat import OpenAIBrain
    from nexus.cli.main import _build_deps
    from nexus.tools.custom.library import ToolLibrary

    console, _ = plain()
    library = ToolLibrary(tmp_path / "tools")
    deps = _build_deps(OpenAIBrain(), console, library)
    assert deps.tools.get("create_tool") is not None and deps.tools.get("delete_tool") is not None
