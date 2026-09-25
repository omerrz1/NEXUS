"""Unit tests for the CLI rendering, slash commands, and approver."""

import io
from pathlib import Path

from rich.console import Console

from nexus.brain.base import Depth
from nexus.brain.mock import MockBrain
from nexus.cli.agent_events import EventPrinter
from nexus.cli.main import parse_args
from nexus.cli.oneshot import run_oneshot
from nexus.cli.render import CliRenderer, HudInfo
from nexus.cli.slash import handle_slash_command
from nexus.cli.status import ServerStatus
from nexus.guardrails.modes import Mode
from nexus.instructions.assemble import build_system_prompt
from nexus.loop import run_agent
from nexus.messages import Message, ToolCall
from nexus.tools.registry import ToolRegistry
from tests.helpers import make_deps


def test_cli_renderer_static_banner() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    renderer.print_banner(animate=False)
    output = buf.getvalue()
    assert "NEXUS" in output or "███" in output
    assert "local-first AI agent" in output
    assert "coding" not in output


def test_cli_renderer_hud() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=100)
    renderer = CliRenderer(console=console)
    renderer.print_hud(
        HudInfo(
            model="test-model",
            base_url="http://127.0.0.1:11434/v1",
            tokens=42,
            speed=25.0,
            branch="main",
            server=ServerStatus(online=True, latency_ms=12.4, model_found=True),
        )
    )
    output = buf.getvalue()
    assert "test-model" in output
    assert "127.0.0.1:11434" in output
    assert "/v1" not in output
    assert "connected" in output and "12 ms" in output
    assert "none (chat only)" in output
    assert "git:main" in output
    assert "42 tok" in output
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


def test_parse_args_defaults() -> None:
    args = parse_args([])
    assert args.model == "nexus-qwen"
    assert args.base_url == "http://127.0.0.1:11434/v1"
    assert args.mode is None  # falls back to the saved setting
    assert args.prompt is None


def test_run_oneshot_mode() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    renderer = CliRenderer(console=console)
    brain = MockBrain()
    brain.queue_reply(Message.assistant("Oneshot reply test."))
    code = run_oneshot("Hello", make_deps(Path.cwd(), brain), renderer)
    assert code == 0
    assert "Oneshot reply test." in buf.getvalue()


def test_slash_command_tools_shows_nothing_when_no_tools_registered() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    handle_slash_command("/tools", {"tools": ToolRegistry()}, console)
    output = buf.getvalue()
    assert "No tools are registered yet" in output
    assert "read_file" not in output


def test_slash_command_mode_switches_mode() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    context: dict[str, object] = {"mode": Mode.ASK}
    handle_slash_command("/mode auto", context, console)
    assert context["mode"] == Mode.AUTO
    handle_slash_command("/mode bogus", context, console)
    assert context["mode"] == Mode.AUTO
    assert "Unknown mode" in buf.getvalue()


def test_slash_command_unknown() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    assert handle_slash_command("/undo", {}, console) is False
    assert "Unknown command" in buf.getvalue()


def test_slash_command_depth_sets_depth() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None)
    context: dict[str, object] = {"depth": Depth.BALANCED}
    handle_slash_command("/depth fast", context, console)
    assert context["depth"] == Depth.FAST


def test_run_oneshot_passes_depth() -> None:
    brain = MockBrain()
    renderer = CliRenderer(console=Console(file=io.StringIO(), color_system=None))
    run_oneshot("Hello", make_deps(Path.cwd(), brain), renderer, depth=Depth.FAST)
    assert brain.depths == [Depth.FAST]


def test_system_prompt_describes_a_general_agent() -> None:
    prompt = build_system_prompt(Path.cwd())
    assert "AI agent" in prompt
    assert "coding" not in prompt.lower()
    assert str(Path.cwd()) in prompt  # the environment snapshot names the working directory


def _card_text(info: HudInfo) -> str:
    buf = io.StringIO()
    CliRenderer(Console(file=buf, force_terminal=False, color_system=None, width=100)).print_hud(
        info
    )
    return buf.getvalue()


def test_hud_warns_when_server_is_down_or_model_is_missing() -> None:
    base = HudInfo(model="qwen", base_url="http://127.0.0.1:11434/v1", tool_count=8)
    down = _card_text(HudInfo(**{**base.__dict__, "server": ServerStatus(online=False)}))
    assert "server not responding" in down and "nexus doctor" in down
    missing = ServerStatus(online=True, latency_ms=3, model_found=False)
    assert "no model named 'qwen'" in _card_text(HudInfo(**{**base.__dict__, "server": missing}))
    assert "8 available" in down


def test_slash_model_rechecks_the_server_and_shows_the_card() -> None:
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, color_system=None, width=100)
    # Port 9 (discard) is closed on loopback, so the probe fails immediately.
    context: dict[str, object] = {"model": "qwen", "base_url": "http://127.0.0.1:9/v1"}
    handle_slash_command("/model", context, console)
    assert "qwen" in buf.getvalue()
    assert "server not responding" in buf.getvalue()


def test_tool_call_and_result_are_compact_lines() -> None:
    buf = io.StringIO()
    out = CliRenderer(Console(file=buf, force_terminal=False, color_system=None, width=80))
    out.print_tool_call("run_command", {"command": "ls -la"})
    out.print_tool_call("write_file", {"path": "a.py", "content": "line1\nline2\nline3"})
    out.print_tool_result("\n".join(f"row {n}" for n in range(20)), ok=True)
    out.print_tool_result("Not found: x", ok=False)
    lines = buf.getvalue().splitlines()
    assert lines[0].strip() == "⚙ run_command  ls -la"
    assert lines[1].strip() == "⚙ write_file  a.py  content=3 lines"
    assert "✔ row 0" in buf.getvalue() and "… 14 more lines" in buf.getvalue()
    assert "✖ Not found: x" in buf.getvalue()


def test_event_printer_shows_a_full_tool_turn(tmp_path: Path) -> None:
    (tmp_path / "hello.txt").write_text("hi there")
    buf = io.StringIO()
    out = CliRenderer(Console(file=buf, force_terminal=False, color_system=None, width=80))
    brain = MockBrain()
    read = ToolCall(id="c1", name="read_file", arguments={"path": "hello.txt"})
    brain.queue_reply(Message.assistant("", (read,)), tool_calls=(read,))
    brain.queue_reply(Message.assistant("The file says hi."))

    printer = EventPrinter(out)
    run_agent(
        [Message.system("s"), Message.user("read it")],
        make_deps(tmp_path, brain),
        Mode.ASK,
        Depth.BALANCED,
        printer,
    )
    output = buf.getvalue()
    assert "⚙ read_file  hello.txt" in output
    assert "✔     1  hi there" in output
    assert "The file says hi." in output


def test_long_paths_keep_their_filename_and_stay_on_one_line() -> None:
    buf = io.StringIO()
    out = CliRenderer(Console(file=buf, force_terminal=False, color_system=None, width=60))
    out.print_tool_call("read_file", {"path": "/very/long/" + "folder/" * 20 + "notes.md"})
    lines = buf.getvalue().splitlines()
    assert len(lines) == 1 and "notes.md" in lines[0]


def test_hud_warns_about_a_small_context_window() -> None:
    small = _card_text(HudInfo(model="m", base_url="http://127.0.0.1:1/v1", context_window=4096))
    large = _card_text(HudInfo(model="m", base_url="http://127.0.0.1:1/v1", context_window=32768))
    assert "4,096 tok" in small and "small" in small
    assert "32,768 tok" in large and "small" not in large
