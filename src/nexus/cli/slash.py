"""Slash command parser and handlers for the interactive CLI REPL."""

from datetime import datetime
from pathlib import Path
import re
import subprocess
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from nexus.cli.complete import BUILTIN_TOOLS, NEXUS_COMMANDS
from nexus.cli.questions import ask_choice

_HELP_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/help", "Show this interactive command guide"),
    ("/tools", "List all available capabilities and risk levels"),
    ("/tool <name>", "Show parameter specification for a specific tool"),
    ("/copy", "Copy last generated code block to your clipboard (⌘V)"),
    ("/save [file]", "Export current session conversation to Markdown"),
    ("/thoughts", "View reasoning trace of last turn (or '/thoughts toggle')"),
    ("/doctor", "Run diagnostic checks on local model server"),
    ("/model", "Display active model, endpoint, and context window"),
    ("/tokens", "Show current conversation and session token usage"),
    ("/stats", "Display session throughput and turn statistics"),
    ("/mode", "Switch execution mode (read-only, ask, auto)"),
    ("/clear", "Clear screen and redraw the Nexus banner"),
    ("/exit", "Exit Nexus"),
)


def handle_slash_command(
    command_line: str,
    context: dict[str, Any],
    console: Console,
) -> bool:
    """Handle a user slash command. Returns True if the REPL should exit."""
    cmd = command_line.strip()
    parts = cmd.split(maxsplit=1)
    keyword = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    match keyword:
        case "/help":
            _show_help(console)
        case "/tools":
            _show_tools(console)
        case "/tool":
            _show_tool_detail(argument, console)
        case "/copy":
            _copy_last_code(context, console)
        case "/save" | "/export":
            _save_session(argument, context, console)
        case "/question":
            _demo_question(console)
        case "/clear":
            _clear_screen(context, console)
        case "/doctor":
            from nexus.cli.doctor import run_doctor

            run_doctor(
                base_url=context.get("base_url", "http://127.0.0.1:11434/v1"),
                model=context.get("model", "nexus-qwen"),
                console=console,
            )
        case "/model":
            _show_model_info(context, console)
        case "/tokens":
            console.print(
                f"[bold #70d6ff]Total Session Tokens:[/bold #70d6ff] "
                f"[white]{context.get('tokens', 0)}[/white]"
            )
        case "/stats":
            _show_stats(context, console)
        case "/thoughts":
            _handle_thoughts(argument, context, console)
        case "/mode":
            mode_name = context.get("mode", "ask")
            console.print(
                f"[bold #70d6ff]Current Mode:[/bold #70d6ff] [cyan]{mode_name}[/cyan]\n"
                "[dim](Modes: read-only | ask | auto)[/dim]"
            )
        case "/undo":
            console.print("[dim]Checkpoint undo is configured for Milestone 2.[/dim]")
        case "/compact":
            console.print("[dim]Context compaction is configured for Milestone 3.[/dim]")
        case "/exit" | "/quit":
            console.print("[bold #70d6ff]Exiting Nexus. Goodbye![/bold #70d6ff]")
            return True
        case _:
            console.print(
                f"[bold red]Unknown command:[/bold red] {keyword}. "
                "Type [bold cyan]/help[/bold cyan] for available commands."
            )

    return False


def _show_help(console: Console) -> None:
    """Print a styled table of slash commands."""
    table = Table(
        title="[bold #70d6ff]NEXUS COMMANDS[/bold #70d6ff]",
        border_style="#0077b6",
        header_style="bold #70d6ff",
    )
    table.add_column("Command", style="bold cyan")
    table.add_column("Description", style="white")

    for cmd, desc in _HELP_COMMANDS:
        table.add_row(cmd, desc)

    console.print(table)


def _show_tools(console: Console) -> None:
    """Display all registered tools with their risk classification."""
    table = Table(
        title="[bold #70d6ff]AVAILABLE TOOLS (TAB-COMPLETABLE)[/bold #70d6ff]",
        border_style="#0077b6",
        header_style="bold #70d6ff",
    )
    table.add_column("Tool", style="bold cyan")
    table.add_column("Risk", justify="center")
    table.add_column("Description", style="white")

    risk_colors = {"read": "green", "write": "yellow", "exec": "red", "none": "dim"}
    for name, risk, desc in BUILTIN_TOOLS:
        badge = f"[bold {risk_colors.get(risk, 'white')}]{risk.upper()}[/bold {risk_colors.get(risk, 'white')}]"
        table.add_row(name, badge, desc)

    console.print(table)
    console.print("[dim]Tip: type '/tool <name>' for parameters and schemas.[/dim]\n")


def _show_tool_detail(name: str, console: Console) -> None:
    """Show details for a specific tool."""
    if not name:
        _show_tools(console)
        return

    match_tool = next((t for t in BUILTIN_TOOLS if t[0] == name), None)
    if not match_tool:
        console.print(f"[bold red]Unknown tool:[/bold red] {name}")
        return

    tool_name, risk, desc = match_tool
    panel = Panel(
        f"[bold white]Description:[/bold white] {desc}\n"
        f"[bold white]Risk Level:[/bold white] [bold cyan]{risk.upper()}[/bold cyan]\n"
        f"[bold white]Usage:[/bold white] Type [cyan]@{tool_name}[/cyan] in your prompt or call it via agent.",
        title=f"[bold #70d6ff]🛠️ Tool Specification: {tool_name}[/bold #70d6ff]",
        border_style="#0096c7",
        padding=(0, 2),
    )
    console.print(panel)


def _copy_last_code(context: dict[str, Any], console: Console) -> None:
    """Extract and copy the last generated code snippet to the system clipboard."""
    last_reply = context.get("last_reply", "")
    if not last_reply:
        console.print("[dim]No previous response available to copy.[/dim]")
        return

    code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", last_reply, re.DOTALL)
    target_text = code_blocks[-1].strip() if code_blocks else last_reply.strip()

    try:
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(target_text.encode("utf-8"))
        if proc.returncode == 0:
            console.print("  [bold #70d6ff]✔[/bold #70d6ff] [cyan]Copied to clipboard (⌘V)![/cyan]")
            return
    except Exception:
        pass
    console.print("[dim]Clipboard copy failed (pbcopy not available).[/dim]")


def _save_session(arg: str, context: dict[str, Any], console: Console) -> None:
    """Export conversation history to a clean markdown document."""
    messages = context.get("messages", [])
    if not messages:
        console.print("[dim]No messages to export yet.[/dim]")
        return

    filename = arg if arg else f"nexus_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    target = Path(filename)

    lines = ["# Nexus Session Log\n\n"]
    for msg in messages:
        role = msg.role.value.upper()
        lines.append(f"### {role}\n\n{msg.content}\n\n")

    target.write_text("".join(lines), encoding="utf-8")
    console.print(f"  [bold #70d6ff]✔[/bold #70d6ff] [cyan]Session saved to [bold white]{target}[/bold white][/cyan]")


def _demo_question(console: Console) -> None:
    """Interactive question prompt demonstration."""
    options = [
        "Create minimal skeleton files first",
        "Generate full implementation with tests",
        "Show diff and ask for confirmation",
    ]
    idx = ask_choice("How should Nexus proceed with the proposed refactor?", options, default=0, console=console)
    console.print(f"  [bold #70d6ff]✔ Selection confirmed:[/bold #70d6ff] [cyan]{options[idx]}[/cyan]\n")


def _clear_screen(context: dict[str, Any], console: Console) -> None:
    """Clear screen and redraw banner and HUD."""
    console.clear()
    renderer = context.get("renderer")
    if renderer is not None:
        renderer.print_banner(animate=False)
        renderer.print_hud(
            model=context.get("model", "unknown"),
            base_url=context.get("base_url", "unknown"),
            mode=context.get("mode", "ask"),
            tokens=context.get("tokens", 0),
            speed=context.get("speed", 0.0),
        )


def _show_model_info(context: dict[str, Any], console: Console) -> None:
    """Print active model and context info."""
    model_name = context.get("model")
    endpoint = context.get("base_url")
    window = context.get("context_window", 4096)
    console.print(
        f"[bold #70d6ff]Active Model:[/bold #70d6ff] [white]{model_name}[/white]\n"
        f"[bold #00b4d8]Endpoint:[/bold #00b4d8] [white]{endpoint}[/white]\n"
        f"[bold #1e90ff]Context Window:[/bold #1e90ff] [white]{window} tokens[/white]"
    )


def _show_stats(context: dict[str, Any], console: Console) -> None:
    """Display session telemetry and throughput metrics in a table."""
    table = Table(
        title="[bold #70d6ff]SESSION STATISTICS[/bold #70d6ff]",
        border_style="#0077b6",
        header_style="bold #70d6ff",
    )
    table.add_column("Metric", style="white")
    table.add_column("Value", style="bold cyan")

    turns = context.get("turns", 0)
    tokens = context.get("tokens", 0)
    speed = context.get("speed", 0.0)
    avg_tokens = f"{tokens / turns:.1f}" if turns > 0 else "0"

    table.add_row("Conversation Turns", str(turns))
    table.add_row("Total Accumulated Tokens", str(tokens))
    table.add_row("Average Tokens / Turn", avg_tokens)
    table.add_row("Latest Generation Speed", f"{speed:.1f} tok/s" if speed > 0 else "N/A")

    console.print(table)


def _handle_thoughts(arg: str, context: dict[str, Any], console: Console) -> None:
    """Handle /thoughts display or toggle."""
    renderer = context.get("renderer")
    if arg == "toggle" and renderer is not None:
        renderer.show_raw_thoughts = not renderer.show_raw_thoughts
        status = "ON (verbose)" if renderer.show_raw_thoughts else "OFF (compact animated)"
        console.print(f"[bold #70d6ff]Raw Thoughts Stream:[/bold #70d6ff] [cyan]{status}[/cyan]")
    elif renderer is not None:
        renderer.print_last_thoughts()
