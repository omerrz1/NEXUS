"""The /tools and /tool views: what the model can call, and the parameters of each tool."""

import json

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from nexus.cli.theme import MUTED
from nexus.tools.base import Risk
from nexus.tools.custom.script_tool import ScriptTool
from nexus.tools.registry import ToolRegistry

_RISK_COLORS: dict[Risk, str] = {
    Risk.NONE: "dim",
    Risk.READ: "green",
    Risk.WRITE: "yellow",
    Risk.EXEC: "red",
    Risk.NETWORK: "magenta",
}


def show_tools(tools: ToolRegistry, console: Console) -> None:
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
        made = f" [{MUTED}](made by Nexus)[/{MUTED}]" if isinstance(tool, ScriptTool) else ""
        table.add_row(
            tool.name,
            f"[bold {color}]{tool.risk.upper()}[/bold {color}]",
            escape(tool.description) + made,
        )

    console.print(table)
    console.print("[dim]Tip: type '/tool <name>' for its parameters.[/dim]\n")


def show_tool_detail(name: str, tools: ToolRegistry, console: Console) -> None:
    """Show the description, risk, and JSON Schema of one tool."""
    if not name:
        show_tools(tools, console)
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
