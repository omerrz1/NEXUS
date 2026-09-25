"""Terminal rendering: the animated banner, the welcome card, and message cards."""

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from nexus import __version__
from nexus.brain.base import DEFAULT_CONTEXT_WINDOW
from nexus.cli.preview import lines_phrase
from nexus.cli.status import ServerStatus
from nexus.cli.stream import TurnView
from nexus.cli.theme import (
    CYAN,
    ERROR,
    GLOW,
    MUTED,
    OCEAN,
    OK,
    SKY,
    WARN,
    blend,
    gradient_at,
)

_NEXUS_ASCII_ART: tuple[str, ...] = (
    r" ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗",
    r" ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝",
    r" ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗",
    r" ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║",
    r" ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║",
    r" ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
)
_TAGLINE = f"local-first AI agent for your terminal  ·  v{__version__}"
_ART_WIDTH = max(len(line) for line in _NEXUS_ASCII_ART)
_FRAME_SECONDS = 1 / 60
_RESULT_PREVIEW_LINES = 6
_SMALL_WINDOW = 8192  # Below this, tool output fills the model's context quickly.


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


@dataclass(frozen=True)
class HudInfo:
    """Everything the details card shows. `server` is None when it was not checked."""

    model: str
    base_url: str
    mode: str = "ask"
    depth: str = "balanced"
    context_window: int = DEFAULT_CONTEXT_WINDOW
    tool_count: int = 0
    branch: str | None = None
    server: ServerStatus | None = None
    tokens: int = 0
    speed: float = 0.0


def hud_from_session(session: dict[str, Any]) -> HudInfo:
    """Collect the card's details from the REPL's session state."""
    tools = session.get("tools")
    return HudInfo(
        model=str(session.get("model", "unknown")),
        base_url=str(session.get("base_url", "unknown")),
        mode=str(session.get("mode", "ask")),
        depth=str(session.get("depth", "balanced")),
        context_window=int(session.get("context_window", DEFAULT_CONTEXT_WINDOW)),
        tool_count=len(tools) if tools is not None else 0,
        branch=session.get("branch"),
        server=session.get("server"),
        tokens=int(session.get("tokens", 0)),
        speed=float(session.get("speed", 0.0)),
    )


def _status_line(info: HudInfo) -> Text:
    """One line saying whether the model server is reachable and has the chosen model."""
    server = info.server
    line = Text(" ")
    if server is None or not server.online:
        line.append("● server not responding", style=f"bold {ERROR}")
        line.append("  run `nexus doctor` to find out why", style=MUTED)
    elif not server.model_found:
        line.append(f"● connected, but the server has no model named '{info.model}'", style=WARN)
    else:
        line.append("● connected", style=f"bold {OK}")
        line.append(f"  {server.latency_ms:.0f} ms", style=MUTED)
    return line


def _border_color(info: HudInfo) -> str:
    """The card's border warns at a glance when something is wrong with the server."""
    if info.server is None:
        return OCEAN
    if not info.server.online:
        return ERROR
    return OCEAN if info.server.model_found else WARN


def _summarize_arguments(arguments: dict[str, Any], max_chars: int) -> str:
    """A single-line view of a tool call's arguments that fits within `max_chars`."""

    def short(value: Any, limit: int) -> str:
        text = value if isinstance(value, str) else json.dumps(value)
        first, *rest = text.splitlines() or [""]
        if len(first) > limit and first.startswith(("/", "~")):
            first = "…" + first[-(limit - 1) :]  # For paths the end (the filename) matters.
        elif len(first) > limit:
            first = first[: limit - 1] + "…"
        return f"{first} (+{len(rest)} lines)" if rest else first

    if len(arguments) == 1:
        return short(next(iter(arguments.values())), max_chars)

    # The first argument is what the call is about (a path, a command, a query), so it needs
    # no label. Text with several lines, such as file contents, is reduced to its size.
    (_, main), *others = arguments.items()
    share = max(12, max_chars // len(arguments))
    parts = [short(main, share)]
    for key, value in others:
        is_multiline = isinstance(value, str) and "\n" in value.rstrip("\n")
        shown = (
            lines_phrase(len(value.splitlines()))
            if is_multiline
            else short(value, share - len(key) - 1)
        )
        parts.append(f"{key}={shown}")
    return "  ".join(parts)


def _server_address(base_url: str) -> str:
    """Show host and port only; the /v1 path is noise."""
    return urlparse(base_url).netloc or base_url


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

    def print_hud(self, info: "HudInfo") -> None:
        """Show the details card: connection status, settings, and where Nexus is running."""
        settings = Table.grid(padding=(0, 2))
        settings.add_column(style=MUTED, justify="right", min_width=8)
        settings.add_column(style=f"bold {SKY}", min_width=18)
        settings.add_column(style=MUTED, justify="right")
        settings.add_column(style=f"bold {SKY}")
        tools = f"{info.tool_count} available" if info.tool_count else "none (chat only)"
        settings.add_row("model", info.model, "mode", info.mode)
        settings.add_row("server", _server_address(info.base_url), "depth", info.depth)
        context = Text(f"{info.context_window:,} tok")
        if info.context_window < _SMALL_WINDOW:
            context.append("  small: see README", style=f"not bold {WARN}")
        settings.add_row("context", context, "tools", tools)
        if info.tokens:
            speed = f"{info.speed:.1f} tok/s" if info.speed > 0 else "idle"
            settings.add_row("session", f"{info.tokens:,} tok", "speed", speed)

        # Folder and branch can be long, so they get their own grid instead of widening
        # the columns above.
        place = Table.grid(padding=(0, 2))
        place.add_column(style=MUTED, justify="right", min_width=8)
        place.add_column()
        location = Text(_short_path(Path.cwd()), style=f"bold {SKY}")
        if info.branch:
            location.append(f"  git:{info.branch}", style=CYAN)
        place.add_row("folder", location)

        parts: list[RenderableType] = []
        if info.server is not None:
            parts += [_status_line(info), Text()]
        parts += [settings, place]
        self.console.print(
            Panel(Group(*parts), border_style=_border_color(info), padding=(0, 1), expand=False)
        )

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
        """Show a tool the model asked to run, on one line."""
        line = Text("  ⚙ ", style=f"bold {OCEAN}")
        line.append(name, style=f"bold {SKY}")
        room = max(20, self.console.width - len(name) - 8)  # What is left after "  ⚙ name  ".
        line.append("  " + _summarize_arguments(arguments, room), style=MUTED)
        self.console.print(line, no_wrap=True, overflow="ellipsis")

    def print_tool_result(self, output: str, ok: bool) -> None:
        """Show the start of what a tool returned, indented under its call."""
        color = MUTED if ok else ERROR
        # Only newlines are stripped: leading spaces on line 1 keep the numbers aligned.
        lines = output.strip("\n").rstrip().splitlines() or ["(no output)"]
        for index, text in enumerate(lines[:_RESULT_PREVIEW_LINES]):
            mark = ("✔" if ok else "✖") if index == 0 else " "
            self.console.print(
                Text(f"    {mark} {text}", style=color), overflow="ellipsis", no_wrap=True
            )
        if len(lines) > _RESULT_PREVIEW_LINES:
            more = len(lines) - _RESULT_PREVIEW_LINES
            self.console.print(Text(f"      … {more} more lines", style=f"dim {MUTED}"))

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
