"""Interactive question prompts, multiple-choice menus, and confirmations."""

from rich.console import Console
from rich.panel import Panel


def ask_choice(
    question: str,
    options: list[str],
    default: int = 0,
    console: Console | None = None,
) -> int:
    """Prompt the user with an interactive multiple-choice question in a blue card."""
    out = console or Console()
    lines = [f"[bold white]{question}[/bold white]\n"]
    for i, opt in enumerate(options, start=1):
        marker = f"[bold cyan][{i}][/bold cyan]"
        desc = f"[white]{opt}[/white]"
        lines.append(f"  {marker} {desc}")

    panel = Panel(
        "\n".join(lines),
        title="[bold #70d6ff]❓ Nexus Question[/bold #70d6ff]",
        border_style="#0096c7",
        padding=(1, 2),
    )
    out.print(panel)

    prompt = (
        f"[bold #70d6ff]Choose [1-{len(options)}][/bold #70d6ff] "
        f"[dim](default {default + 1})[/dim] [bold #00b4d8]›[/bold #00b4d8] "
    )

    while True:
        try:
            choice = out.input(prompt).strip()
            if not choice:
                return default
            if choice.isdigit():
                val = int(choice)
                if 1 <= val <= len(options):
                    return val - 1
            # Check for exact option text match
            for idx, opt in enumerate(options):
                if choice.lower() in opt.lower():
                    return idx
            out.print(f"[dim]Please enter a number between 1 and {len(options)}.[/dim]")
        except (KeyboardInterrupt, EOFError):
            out.print("\n[dim]Default selection applied.[/dim]")
            return default


def ask_confirm(
    prompt: str,
    default: bool = True,
    console: Console | None = None,
) -> bool:
    """Prompt the user with a stylized y/n confirmation."""
    out = console or Console()
    suffix = "[Y/n]" if default else "[y/N]"
    formatted_prompt = (
        f"[bold #70d6ff]{prompt}[/bold #70d6ff] "
        f"[cyan]{suffix}[/cyan] [bold #00b4d8]›[/bold #00b4d8] "
    )
    try:
        ans = out.input(formatted_prompt).strip().lower()
        if not ans:
            return default
        return ans in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        out.print()
        return default
