"""Unit tests for the CLI rendering, slash commands, and approver."""

import io

import pytest
from rich.console import Console

from nexus.brain.mock import MockBrain
from nexus.cli.approve import Approval, CliApprover
from nexus.cli.main import parse_args
from nexus.cli.oneshot import run_oneshot
from nexus.cli.render import CliRenderer
from nexus.cli.slash import handle_slash_command
from nexus.messages import Message, ToolCall


def test_cli_renderer_static_banner() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    renderer.print_banner(animate=False)
    output = buf.getvalue()
    assert "NEXUS" in output or "███" in output
    assert "LOCAL-FIRST TERMINAL CODING AGENT" in output


def test_cli_renderer_hud() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    renderer.print_hud(
        model="test-model",
        base_url="http://127.0.0.1:11434/v1",
        mode="ask",
        tokens=42,
        speed=25.0,
    )
    output = buf.getvalue()
    assert "test-model" in output
    assert "42" in output
    assert "25.0 tok/s" in output


def test_cli_renderer_tool_card() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    renderer.print_tool_call("read_file", {"path": "src/main.py"})
    output = buf.getvalue()
    assert "read_file" in output
    assert "src/main.py" in output


def test_cli_renderer_compact_reasoning() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    renderer.start_stream()
    renderer.print_reasoning_chunk("Step 1: internal reasoning...\n")
    renderer.print_chunk("Final answer.")
    speed = renderer.end_stream()

    output = buf.getvalue()
    # In non-verbose mode, the raw internal reasoning shouldn't be dumped to main text
    assert "Step 1: internal reasoning" not in output
    assert "Final answer." in output
    assert speed > 0
    assert renderer.last_reasoning_trace == "Step 1: internal reasoning...\n"


def test_slash_command_help() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    should_exit = handle_slash_command("/help", {}, console)
    assert should_exit is False
    assert "/help" in buf.getvalue()
    assert "/doctor" in buf.getvalue()


def test_slash_command_stats() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    context = {"turns": 3, "tokens": 150, "speed": 35.5}
    should_exit = handle_slash_command("/stats", context, console)
    assert should_exit is False
    assert "150" in buf.getvalue()
    assert "35.5 tok/s" in buf.getvalue()


def test_slash_command_thoughts() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    renderer.last_reasoning_trace = "The reasoning steps: A, B, C."
    context = {"renderer": renderer}
    should_exit = handle_slash_command("/thoughts", context, console)
    assert should_exit is False
    assert "The reasoning steps: A, B, C." in buf.getvalue()


def test_slash_command_exit() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    should_exit = handle_slash_command("/exit", {}, console)
    assert should_exit is True
    assert "Goodbye" in buf.getvalue()


def test_cli_approver_once(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)
    monkeypatch.setattr("rich.console.Console.input", lambda self, prompt="": "y")
    approver = CliApprover(console=console)
    call = ToolCall(id="call_1", name="edit_file", arguments={"path": "x.py"})
    res = approver.approve(call)
    assert res == Approval.ONCE


def test_cli_approver_session(monkeypatch: pytest.MonkeyPatch) -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False)
    monkeypatch.setattr("rich.console.Console.input", lambda self, prompt="": "a")
    approver = CliApprover(console=console)
    call = ToolCall(id="call_2", name="edit_file", arguments={"path": "x.py"})
    res = approver.approve(call)
    assert res == Approval.SESSION
    # Second call should bypass prompt and return SESSION immediately
    assert approver.approve(call) == Approval.SESSION


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.model == "nexus-qwen"
    assert args.base_url == "http://127.0.0.1:11434/v1"
    assert args.mode == "ask"
    assert args.prompt is None


def test_run_oneshot_mode() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    brain = MockBrain()
    brain.queue_reply(Message.assistant("Oneshot reply test."))
    code = run_oneshot("Hello", brain, renderer)
    assert code == 0
    assert "Oneshot reply test." in buf.getvalue()
