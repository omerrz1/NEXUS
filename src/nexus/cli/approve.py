"""Interactive terminal confirmation prompt implementing the Approver interface."""

from enum import StrEnum
from typing import Protocol

from rich.console import Console
from rich.panel import Panel

from nexus.messages import ToolCall


class Approval(StrEnum):
    """The decision options for approving a guarded action."""

    ONCE = "once"
    SESSION = "session"
    DENY = "deny"


class Approver(Protocol):
    """Protocol for asking user consent before executing guarded operations."""

    def approve(self, call: ToolCall, preview: str | None = None) -> Approval:
        """Prompt user for confirmation on a tool execution."""
        ...


class CliApprover:
    """Prompts the user interactively in the terminal with styled blue panels."""

    def __init__(self, console: Console | None = None) -> None:
        self.console: Console = console or Console()
        self._session_grants: set[str] = set()

    def approve(self, call: ToolCall, preview: str | None = None) -> Approval:
        """Prompt user with y/a/n choices, checking existing session grants first."""
        if call.name in self._session_grants:
            return Approval.SESSION

        preview_text = preview or f"Tool: {call.name}\nArgs: {call.arguments}"
        panel = Panel(
            preview_text,
            title=f"[bold #ffb703]⚠ Approval Requested:[/bold #ffb703] [white]{call.name}[/white]",
            border_style="#0096c7",
            padding=(0, 1),
        )
        self.console.print(panel)

        while True:
            try:
                choice = (
                    self.console.input(
                        "[bold #70d6ff]Allow action?[/bold #70d6ff] "
                        "([bold green]y[/bold green]es / "
                        "[bold cyan]a[/bold cyan]lways this session / "
                        "[bold red]n[/bold red]o): "
                    )
                    .strip()
                    .lower()
                )
            except (KeyboardInterrupt, EOFError):
                self.console.print("\n[red]Action declined by user interrupt.[/red]")
                return Approval.DENY

            if choice in ("y", "yes"):
                return Approval.ONCE
            if choice in ("a", "always"):
                self._session_grants.add(call.name)
                return Approval.SESSION
            if choice in ("n", "no", ""):
                return Approval.DENY
            self.console.print("[dim]Please enter 'y', 'a', or 'n'.[/dim]")
