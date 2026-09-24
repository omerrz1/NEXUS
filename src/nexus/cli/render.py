"""Terminal rendering: the animated banner, the welcome card, and message cards."""

import json
import time
from pathlib import Path
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from nexus.cli.stream import TurnView
from nexus.cli.theme import CYAN, ERROR, GLOW, MUTED, OCEAN, SKY, blend, gradient_at

_NEXUS_ASCII_ART: tuple[str, ...] = (
    r" ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗",
    r" ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝",
    r" ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗",
    r" ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║",
    r" ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║",
    r" ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
)
_TAGLINE = "local-first terminal coding agent"
_ART_WIDTH = max(len(line) for line in _NEXUS_ASCII_ART)
_FRAME_SECONDS = 1 / 60


def _banner_frame(revealed: float, glow_at: float | None) -> Group:
    """One banner frame: columns up to `revealed` are drawn; `glow_at` is a light band."""
    lines: list[Text] = []
    for row, line in enumerate(_NEXUS_ASCII_ART):
        text = Text()
        for column, char in enumerate(line):
            # Rows are offset so the reveal edge is diagonal, which reads as motion.
            if column > revealed - row * 1.5:
                text.append(" ")
                continue
            color = gradient_at((column + row * 2) / (_ART_WIDTH + 12))
            if glow_at is not None:
                color = blend(color, GLOW, 1 - abs(column + row - glow_at) / 5)
            text.append(char, style=f"bold {color}")
        lines.append(text)
    tagline = Text(f"  {_TAGLINE}", style=f"italic {MUTED}")
    return Group(*lines, tagline, Text())


class CliRenderer:
    """Everything the REPL shows, apart from the input line."""

    def __init__(self, console: Console | None = None) -> None:
        self.console: Console = console or Console()
        self.show_raw_thoughts: bool = False
        self.last_reasoning_trace: str = ""
        self._turn: TurnView | None = None

    def print_banner(self, animate: bool = True) -> None:
        """Draw the banner: a diagonal wipe in, then a light sweep across the letters."""
        if not animate or not self.console.is_terminal:
            self.console.print(_banner_frame(revealed=_ART_WIDTH * 3, glow_at=None))
            return

        with Live(console=self.console, refresh_per_second=60, transient=False) as live:
            for step in range(36):
                live.update(_banner_frame(revealed=step * 2.0, glow_at=None), refresh=True)
                time.sleep(_FRAME_SECONDS)
            for step in range(30):
                glow = -6 + step * (_ART_WIDTH + 12) / 30
                live.update(_banner_frame(revealed=_ART_WIDTH * 3, glow_at=glow), refresh=True)
                time.sleep(_FRAME_SECONDS)
            live.update(_banner_frame(revealed=_ART_WIDTH * 3, glow_at=None), refresh=True)

    def print_hud(
        self,
        model: str,
        base_url: str,
        mode: str = "ask",
        depth: str = "balanced",
        tokens: int = 0,
        speed: float = 0.0,
        context_window: int = 4096,
    ) -> None:
        """Show the session's settings in a compact card."""
        grid = Table.grid(padding=(0, 2))
        grid.add_column(style=MUTED, justify="right")
        grid.add_column(style=f"bold {SKY}")
        grid.add_column(style=MUTED, justify="right")
        grid.add_column(style=f"bold {SKY}")
        speed_text = f"{speed:.1f} tok/s" if speed > 0 else "idle"
        grid.add_row("model", model, "mode", mode)
        grid.add_row("server", base_url, "depth", depth)
        grid.add_row(
            "context", f"{context_window:,} tok", "session", f"{tokens} tok · {speed_text}"
        )
        grid.add_row("folder", _short_path(Path.cwd()), "", "")
        self.console.print(Panel(grid, border_style=OCEAN, padding=(0, 1), expand=False))

    def print_tips(self) -> None:
        """Show the handful of shortcuts a new user needs."""
        tips = Text("  ")
        for key, action in (("/", "commands"), ("@", "files"), ("⇧⇥", "mode"), ("^T", "depth")):
            tips.append(key, style=f"bold {CYAN}")
            tips.append(f" {action}   ", style=MUTED)
        tips.append("ctrl-d", style=f"bold {CYAN}")
        tips.append(" exit", style=MUTED)
        self.console.print(tips)
        self.console.print()

    def start_stream(self) -> None:
        """Begin showing a new model turn."""
        self._turn = TurnView(self.console, show_thinking=self.show_raw_thoughts)
        self._turn.start()

    def print_reasoning_chunk(self, chunk: str) -> None:
        """Feed a piece of the model's reasoning to the live view."""
        if self._turn is not None:
            self._turn.add_reasoning(chunk)

    def print_chunk(self, chunk: str) -> None:
        """Feed a piece of the model's answer to the live view."""
        if self._turn is not None:
            self._turn.add_answer(chunk)

    def end_stream(self) -> float:
        """Finish the turn and return its generation speed in tokens per second."""
        if self._turn is None:
            return 0.0
        turn, self._turn = self._turn, None
        self.last_reasoning_trace = turn.reasoning
        _, speed = turn.finish()
        return speed

    def print_last_thoughts(self) -> None:
        """Show the reasoning from the last turn."""
        if not self.last_reasoning_trace.strip():
            self.console.print(f"[{MUTED}]No reasoning recorded for the last turn.[/{MUTED}]")
            return
        self.console.print(
            Panel(
                Text(self.last_reasoning_trace.strip(), style=f"italic {MUTED}"),
                title=f"[bold {SKY}]✻ Last reasoning[/bold {SKY}]",
                title_align="left",
                border_style=OCEAN,
                padding=(0, 1),
            )
        )

    def print_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Show a tool the model asked to run."""
        code = Syntax(json.dumps(arguments, indent=2), "json", theme="monokai")
        self.console.print(
            Panel(
                code,
                title=f"[bold {SKY}]⚙ {name}[/bold {SKY}]",
                title_align="left",
                border_style=OCEAN,
                padding=(0, 1),
            )
        )

    def print_tool_result(self, name: str, output: str, ok: bool) -> None:
        """Show what a tool returned."""
        color = CYAN if ok else ERROR
        self.console.print(
            Panel(
                output.strip() or "(empty)",
                title=f"[{color}]{'✔' if ok else '✖'} {name}[/{color}]",
                title_align="left",
                border_style=color,
                padding=(0, 1),
            )
        )

    def print_info(self, message: str) -> None:
        """Show a short notice."""
        self.console.print(f"  [bold {CYAN}]●[/bold {CYAN}] {message}")

    def print_error(self, message: str) -> None:
        """Show an error."""
        self.console.print(f"  [bold {ERROR}]✖[/bold {ERROR}] {message}")


def _short_path(path: Path) -> str:
    """Show the home directory as ~ to keep the card narrow."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
