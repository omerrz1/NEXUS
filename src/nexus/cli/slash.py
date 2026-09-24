"""Slash command parser and handlers for the interactive CLI REPL."""

import json
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from nexus.brain.base import DEFAULT_BASE_URL, DEFAULT_MODEL
from nexus.cli.export import copy_last_code, save_session
from nexus.cli.render import CliRenderer, hud_from_session
from nexus.cli.settings import choose_setting, handle_thoughts, open_settings_menu
from nexus.cli.status import probe_server
from nexus.cli.theme import CYAN, MUTED, SKY
from nexus.tools.base import Risk
from nexus.tools.registry import ToolRegistry, default_registry


@dataclass(frozen=True)
class SlashCommand:
    """One slash command as shown in /help and offered by tab completion."""

    name: str
    usage: str
    description: str
    aliases: tuple[str, ...] = ()


# The single list of commands. /help, tab completion, and the dispatcher all read it,
# so a command that is not listed here does not exist.
SLASH_COMMANDS: tuple[SlashCommand, ...] = (
    SlashCommand("/help", "/help", "Show this command guide"),
    SlashCommand("/settings", "/settings", "Change mode, depth, and reasoning display"),
    SlashCommand("/depth", "/depth [level]", "How long the model thinks: fast, balanced, deep"),
    SlashCommand("/mode", "/mode [name]", "Permission mode: read-only, ask, auto"),
    SlashCommand(
        "/thoughts", "/thoughts [toggle]", "Show the last reasoning, or toggle showing it"
    ),
    SlashCommand("/model", "/model", "Check the server and show the model's details"),
    SlashCommand("/tools", "/tools", "List the tools the model can call"),
    SlashCommand("/tool", "/tool <name>", "Show the parameters of one tool"),
    SlashCommand("/copy", "/copy", "Copy the last code block to the clipboard"),
    SlashCommand("/save", "/save [file]", "Export this conversation to Markdown", ("/export",)),
    SlashCommand("/stats", "/stats", "Show turn and token statistics"),
    SlashCommand("/tokens", "/tokens", "Show session token usage"),
    SlashCommand("/doctor", "/doctor", "Run diagnostic checks on the local model server"),
    SlashCommand("/new", "/new", "Start a new conversation (frees up the model's memory)"),
    SlashCommand("/clear", "/clear", "Clear the screen"),
    SlashCommand("/exit", "/exit", "Exit Nexus", ("/quit",)),
)

_RISK_COLORS: dict[Risk, str] = {
    Risk.NONE: "dim",
    Risk.READ: "green",
    Risk.WRITE: "yellow",
    Risk.EXEC: "red",
}


def find_command(keyword: str) -> SlashCommand | None:
    """Return the command named `keyword`, or the only command it is a prefix of."""
    for command in SLASH_COMMANDS:
        if keyword == command.name or keyword in command.aliases:
            return command
    # Accepting prefixes means "/dep" works even if the menu was dismissed.
    matches = [command for command in SLASH_COMMANDS if command.name.startswith(keyword)]
    return matches[0] if len(matches) == 1 and len(keyword) > 1 else None


def handle_slash_command(
    command_line: str,
    context: dict[str, Any],
    console: Console,
) -> bool:
    """Handle a user slash command. Returns True if the REPL should exit."""
    parts = command_line.strip().split(maxsplit=1)
    command = find_command(parts[0].lower())
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command is None:
        console.print(
            f"[bold red]Unknown command:[/bold red] {parts[0]}. "
            "Type [bold cyan]/help[/bold cyan] for available commands."
        )
        return False
    if command.name == "/exit":
        console.print("[bold #70d6ff]Exiting Nexus. Goodbye![/bold #70d6ff]")
        return True

    _run_command(command.name, argument, context, console)
    return False


def _run_command(name: str, argument: str, context: dict[str, Any], console: Console) -> None:
    """Dispatch a known, non-exit command to its handler."""
    # An empty registry is falsy, so test for None rather than using `or`.
    tools: ToolRegistry | None = context.get("tools")
    if tools is None:
        tools = default_registry()
    match name:
        case "/help":
            _show_help(console)
        case "/tools":
            _show_tools(tools, console)
        case "/tool":
            _show_tool_detail(argument, tools, console)
        case "/copy":
            copy_last_code(context, console)
        case "/save":
            save_session(argument, context, console)
        case "/thoughts":
            handle_thoughts(argument, context, console)
        case "/settings":
            open_settings_menu(context, console)
        case "/doctor":
            _run_doctor(context, console)
        case "/model":
            _show_model_info(context, console)
        case "/tokens":
            console.print(
                f"[bold #70d6ff]Total Session Tokens:[/bold #70d6ff] "
                f"[white]{context.get('tokens', 0)}[/white]"
            )
        case "/stats":
            _show_stats(context, console)
        case "/mode":
            choose_setting("mode", argument, context, console)
        case "/depth":
            choose_setting("depth", argument, context, console)
        case "/clear":
            _clear_screen(context, console)
        case "/new":
            _start_new_conversation(context, console)


def _show_help(console: Console) -> None:
    """Print the slash commands as a two-column list."""
    table = Table.grid(padding=(0, 3))
    table.add_column(style=f"bold {CYAN}", no_wrap=True)
    table.add_column(style="#d0e4ee")
    for command in SLASH_COMMANDS:
        aliases = (
            f" [{MUTED}](or {', '.join(command.aliases)})[/{MUTED}]" if command.aliases else ""
        )
        table.add_row(command.usage, command.description + aliases)

    console.print(f"\n[bold {SKY}]Commands[/bold {SKY}]")
    console.print(table)
    console.print(
        f"\n[{MUTED}]Type / to open this list as a menu · "
        f"⇧⇥ cycles mode · ^T cycles depth[/{MUTED}]\n"
    )


def _show_tools(tools: ToolRegistry, console: Console) -> None:
    """Display every registered tool with its risk level."""
    if len(tools) == 0:
        console.print("[dim]No tools are registered yet. The model can only chat for now.[/dim]")
        return

    table = Table(
        title="[bold #70d6ff]AVAILABLE TOOLS[/bold #70d6ff]",
        border_style="#0077b6",
        header_style="bold #70d6ff",
    )
    table.add_column("Tool", style="bold cyan")
    table.add_column("Risk", justify="center")
    table.add_column("Description", style="white")

    for tool in tools:
        color = _RISK_COLORS[tool.risk]
        table.add_row(
            tool.name, f"[bold {color}]{tool.risk.upper()}[/bold {color}]", tool.description
        )

    console.print(table)
    console.print("[dim]Tip: type '/tool <name>' for its parameters.[/dim]\n")


def _show_tool_detail(name: str, tools: ToolRegistry, console: Console) -> None:
    """Show the description, risk, and JSON Schema of one tool."""
    if not name:
        _show_tools(tools, console)
        return

    tool = tools.get(name)
    if tool is None:
        console.print(f"[bold red]Unknown tool:[/bold red] {name}")
        return

    schema = json.dumps(tool.spec().parameters, indent=2)
    console.print(
        Panel(
            Syntax(schema, "json", theme="monokai"),
            title=f"[bold #70d6ff]{tool.name}[/bold #70d6ff] [dim]({tool.risk})[/dim]",
            subtitle=tool.description,
            border_style="#0096c7",
            padding=(0, 1),
        )
    )


def _run_doctor(context: dict[str, Any], console: Console) -> None:
    """Run the same diagnostics as `nexus doctor` against the active model."""
    # Imported here so the slash module stays importable without the HTTP client.
    from nexus.cli.doctor import run_doctor

    run_doctor(
        base_url=context.get("base_url", DEFAULT_BASE_URL),
        model=context.get("model", DEFAULT_MODEL),
        console=console,
    )


def _start_new_conversation(context: dict[str, Any], console: Console) -> None:
    """Forget the conversation, keeping only the system prompt, and reset the counters."""
    messages = context.get("messages", [])
    del messages[1:]
    context.update(tokens=0, turns=0, speed=0.0, last_reply="")
    console.print(f"  [bold {CYAN}]✔[/bold {CYAN}] Started a new conversation.")


def _clear_screen(context: dict[str, Any], console: Console) -> None:
    """Clear the screen and redraw the banner and details card."""
    console.clear()
    renderer = context.get("renderer")
    if renderer is not None:
        renderer.print_banner(animate=False)
        renderer.print_hud(hud_from_session(context))


def _show_model_info(context: dict[str, Any], console: Console) -> None:
    """Re-check the model server and show the details card with the fresh result."""
    context["server"] = probe_server(
        context.get("base_url", ""), context.get("model", ""), timeout_sec=3.0
    )
    renderer = context.get("renderer") or CliRenderer(console)
    renderer.print_hud(hud_from_session(context))


def _show_stats(context: dict[str, Any], console: Console) -> None:
    """Display session throughput metrics in a table."""
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
