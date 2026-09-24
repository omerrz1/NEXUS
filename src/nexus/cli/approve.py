"""The terminal prompt that asks the user before a guarded tool call runs."""

import json

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from nexus.cli.theme import CYAN, ERROR, MUTED, OK, SKY, WARN
from nexus.guardrails.approval import Approval
from nexus.messages import ToolCall


class CliApprover:
    """Shows what a tool call will do and asks yes, always, or no."""

    def __init__(self, console: Console | None = None) -> None:
        self.console: Console = console or Console()
        self._session_grants: set[str] = set()

    def approve(
        self, call: ToolCall, preview: str | None = None, scope: str | None = None
    ) -> Approval:
        """Ask about one call. "Always" is remembered for `scope` until the session ends."""
        scope = scope or call.name
        if scope in self._session_grants:
            return Approval.SESSION

        self.console.print(
            Panel(
                _style_preview(preview or json.dumps(call.arguments, indent=2)),
                title=f"[bold {WARN}]⚠ Allow {call.name}?[/bold {WARN}]",
                title_align="left",
                border_style=WARN,
                padding=(0, 1),
            )
        )
        answer = self._ask(scope)
        if answer is Approval.SESSION:
            self._session_grants.add(scope)
        return answer

    def _ask(self, scope: str) -> Approval:
        prompt = (
            f"  [bold {OK}]y[/bold {OK}][{MUTED}]es[/{MUTED}]  "
            f"[bold {CYAN}]a[/bold {CYAN}][{MUTED}]lways: {scope}[/{MUTED}]  "
            f"[bold {ERROR}]n[/bold {ERROR}][{MUTED}]o[/{MUTED}]  [bold {SKY}]›[/bold {SKY}] "
        )
        while True:
            try:
                choice = self.console.input(prompt).strip().lower()
            except (KeyboardInterrupt, EOFError):
                self.console.print(f"\n  [{MUTED}]Declined.[/{MUTED}]")
                return Approval.DENY

            if choice in ("y", "yes"):
                return Approval.ONCE
            if choice in ("a", "always"):
                return Approval.SESSION
            if choice in ("n", "no", ""):
                return Approval.DENY
            self.console.print(f"  [{MUTED}]Please type y, a, or n.[/{MUTED}]")


def _style_preview(preview: str) -> Text:
    """Color diff lines so additions and removals stand out."""
    text = Text()
    for line in preview.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            style = OK
        elif line.startswith("-") and not line.startswith("---"):
            style = ERROR
        elif line.startswith("@@") or line.startswith("$ "):
            style = f"bold {CYAN}"
        else:
            style = ""
        text.append(line + "\n", style=style)
    text.rstrip()
    return text
