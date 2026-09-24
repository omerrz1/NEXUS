"""Getting text out of a session: copying the last code block and saving the transcript."""

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console

from nexus.messages import Role


def copy_last_code(context: dict[str, Any], console: Console) -> None:
    """Copy the last code block of the last reply (or the whole reply) to the clipboard."""
    last_reply = context.get("last_reply", "")
    if not last_reply:
        console.print("[dim]No previous response available to copy.[/dim]")
        return

    code_blocks = re.findall(r"```(?:\w+)?\n(.*?)```", last_reply, re.DOTALL)
    target_text = code_blocks[-1].strip() if code_blocks else last_reply.strip()

    try:
        proc = subprocess.run(["pbcopy"], input=target_text.encode("utf-8"), check=False)
    except OSError:
        console.print("[dim]Clipboard copy failed (pbcopy not available).[/dim]")
        return
    if proc.returncode == 0:
        console.print("  [bold #70d6ff]✔[/bold #70d6ff] [cyan]Copied to clipboard.[/cyan]")
    else:
        console.print("[dim]Clipboard copy failed.[/dim]")


def save_session(arg: str, context: dict[str, Any], console: Console) -> None:
    """Export the conversation (without the system prompt) to a Markdown file."""
    messages = [m for m in context.get("messages", []) if m.role != Role.SYSTEM]
    if not messages:
        console.print("[dim]No messages to export yet.[/dim]")
        return

    filename = arg or f"nexus_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    target = Path(filename)

    lines = ["# Nexus Session Log\n\n"]
    for msg in messages:
        lines.append(f"### {msg.role.value.upper()}\n\n{msg.content}\n\n")

    target.write_text("".join(lines), encoding="utf-8")
    console.print(
        f"  [bold #70d6ff]✔[/bold #70d6ff] [cyan]Session saved to "
        f"[bold white]{target}[/bold white][/cyan]"
    )
