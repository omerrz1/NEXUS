"""Terminal rendering engine with blue-themed styling, ASCII banners, and animated loading."""

import time
from typing import Any

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

_NEXUS_ASCII_ART: tuple[str, ...] = (
    r" ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗",
    r" ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝",
    r" ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗",
    r" ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║",
    r" ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║",
    r" ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝",
)

_BLUE_GRADIENT: tuple[str, ...] = (
    "#70d6ff",
    "#00b4d8",
    "#0096c7",
    "#0077b6",
    "#1e90ff",
    "#4361ee",
)

_SPINNER_FRAMES: tuple[str, ...] = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")


class CliRenderer:
    """Handles terminal formatting, animations, status HUDs, and message rendering."""

    def __init__(self, console: Console | None = None) -> None:
        self.console: Console = console or Console()
        self._is_streaming: bool = False
        self._in_reasoning: bool = False
        self._header_printed: bool = False
        self.show_raw_thoughts: bool = False
        self.last_reasoning_trace: str = ""

        self._reasoning_start: float = 0.0
        self._reasoning_tokens: int = 0
        self._reasoning_buffer: list[str] = []
        self._spinner_idx: int = 0
        self._last_spinner_update: float = 0.0
        self._turn_start: float = 0.0
        self._turn_tokens: int = 0

    def print_banner(self, animate: bool = True) -> None:
        """Render the animated glowing blue NEXUS ASCII banner."""
        if not animate or not self.console.is_terminal:
            self._print_static_banner()
            return

        with Live(console=self.console, refresh_per_second=20, transient=False) as live:
            accumulated: list[Text] = []
            for i, line in enumerate(_NEXUS_ASCII_ART):
                color = _BLUE_GRADIENT[i % len(_BLUE_GRADIENT)]
                text = Text(line, style=f"bold {color}")
                accumulated.append(text)
                live.update(Group(*accumulated))
                time.sleep(0.04)

            for step in range(3):
                shimmer_group: list[Text] = []
                for i, line in enumerate(_NEXUS_ASCII_ART):
                    color = _BLUE_GRADIENT[(i + step) % len(_BLUE_GRADIENT)]
                    shimmer_group.append(Text(line, style=f"bold {color}"))
                live.update(Group(*shimmer_group))
                time.sleep(0.06)

            subtitle = Text(
                "─── LOCAL-FIRST TERMINAL CODING AGENT ───",
                style="bold deep_sky_blue1 justify-center",
            )
            live.update(Group(*accumulated, Text(""), subtitle, Text("")))

    def _print_static_banner(self) -> None:
        """Render static banner without delay."""
        banner_lines: list[Text] = []
        for i, line in enumerate(_NEXUS_ASCII_ART):
            color = _BLUE_GRADIENT[i % len(_BLUE_GRADIENT)]
            banner_lines.append(Text(line, style=f"bold {color}"))
        banner_lines.append(Text(""))
        banner_lines.append(
            Text("─── LOCAL-FIRST TERMINAL CODING AGENT ───", style="bold deep_sky_blue1")
        )
        self.console.print(Group(*banner_lines))

    def print_hud(
        self,
        model: str,
        base_url: str,
        mode: str = "ask",
        tokens: int = 0,
        speed: float = 0.0,
    ) -> None:
        """Render a sleek high-tech blue dashboard showing system parameters."""
        speed_str = f"{speed:.1f} tok/s" if speed > 0 else "idle"
        line1 = (
            f"[bold #70d6ff]◈ MODEL:[/bold #70d6ff] [white]{model}[/white]   "
            f"[bold #00b4d8]⚡ RUNTIME:[/bold #00b4d8] [white]{base_url}[/white]   "
            f"[bold #1e90ff]🔒 MODE:[/bold #1e90ff] [cyan]{mode}[/cyan]"
        )
        line2 = (
            "[bold #0077b6]📊 CTX:[/bold #0077b6] [white]4,096 tok[/white]   "
            f"[bold #0096c7]⚡ SPEED:[/bold #0096c7] [white]{speed_str}[/white]   "
            f"[bold #4361ee]💬 SESSION:[/bold #4361ee] [white]{tokens} tok[/white]"
        )
        panel = Panel(
            f"{line1}\n{line2}",
            border_style="#0096c7",
            padding=(0, 2),
            title="[bold #70d6ff]NEXUS AGENT HUD[/bold #70d6ff]",
            title_align="left",
        )
        self.console.print(panel)

    def start_stream(self) -> None:
        """Prepare console for streaming token outputs."""
        self._is_streaming = True
        self._in_reasoning = False
        self._header_printed = False
        self._reasoning_tokens = 0
        self._reasoning_buffer = []
        self._turn_tokens = 0
        self._turn_start = time.perf_counter()
        self.console.print()

    def print_reasoning_chunk(self, chunk: str) -> None:
        """Process reasoning chunks with animated loading spinner or verbose output."""
        self._reasoning_buffer.append(chunk)
        self._reasoning_tokens += 1
        self._turn_tokens += 1

        if self.show_raw_thoughts:
            if not self._in_reasoning:
                self._in_reasoning = True
                self.console.print("[dim #0077b6]Thinking[/dim #0077b6] [dim]›[/dim] ", end="")
            self.console.file.write(chunk)
            self.console.file.flush()
            return

        now = time.perf_counter()
        if not self._in_reasoning:
            self._in_reasoning = True
            self._reasoning_start = now
            self._last_spinner_update = now

        is_tty = bool(
            self.console.is_terminal and getattr(self.console.file, "isatty", lambda: False)()
        )
        if is_tty and (now - self._last_spinner_update >= 0.08):
            self._last_spinner_update = now
            frame = _SPINNER_FRAMES[self._spinner_idx % len(_SPINNER_FRAMES)]
            self._spinner_idx += 1
            elapsed = now - self._reasoning_start
            anim_text = (
                f"\r  \033[38;2;0;212;255m{frame}\033[0m "
                f"\033[1;38;2;0;180;216mThinking...\033[0m "
                f"\033[2;38;2;112;214;255m({elapsed:.1f}s • {self._reasoning_tokens} tok)\033[0m   "
            )
            self.console.file.write(anim_text)
            self.console.file.flush()

    def print_chunk(self, chunk: str) -> None:
        """Print a streaming token delta to console output."""
        is_tty = bool(
            self.console.is_terminal and getattr(self.console.file, "isatty", lambda: False)()
        )
        if self._in_reasoning:
            self._in_reasoning = False
            elapsed = max(0.1, time.perf_counter() - self._reasoning_start)
            if not self.show_raw_thoughts:
                if is_tty:
                    self.console.file.write("\r\033[K")
                self.console.print(
                    f"  [dim #0077b6]╭─[/dim #0077b6] "
                    f"[cyan]✔ Thought for {elapsed:.1f}s[/cyan] "
                    f"[dim]({self._reasoning_tokens} tokens)[/dim]"
                )
            self.console.print("[bold #00b4d8]Nexus[/bold #00b4d8] [cyan]›[/cyan] ", end="")
            self._header_printed = True
        elif not self._header_printed:
            self.console.print("[bold #00b4d8]Nexus[/bold #00b4d8] [cyan]›[/cyan] ", end="")
            self._header_printed = True

        self.console.file.write(chunk)
        self.console.file.flush()
        self._turn_tokens += 1

    def end_stream(self) -> float:
        """Conclude the streaming output and display turn telemetry speed."""
        self.last_reasoning_trace = "".join(self._reasoning_buffer)
        if self._in_reasoning and self.console.is_terminal and not self.show_raw_thoughts:
            self.console.file.write("\r\033[K")

        elapsed = max(0.01, time.perf_counter() - self._turn_start)
        speed = self._turn_tokens / elapsed

        if self._header_printed:
            self.console.print()
            self.console.print(
                f"  [dim #0077b6]╰─[/dim #0077b6] "
                f"[dim]⚡ {elapsed:.1f}s • {self._turn_tokens} tokens ({speed:.1f} tok/s)[/dim]"
            )

        self._is_streaming = False
        self._in_reasoning = False
        self._header_printed = False
        self.console.print()
        return speed

    def print_last_thoughts(self) -> None:
        """Display the reasoning thoughts from the last turn in a bordered modal panel."""
        if not self.last_reasoning_trace.strip():
            self.console.print("[dim]No reasoning thoughts recorded for the last turn.[/dim]")
            return
        panel = Panel(
            self.last_reasoning_trace.strip(),
            title="[bold #70d6ff]🧠 Model Thinking Trace[/bold #70d6ff]",
            border_style="#0077b6",
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_assistant_markdown(self, markdown_text: str) -> None:
        """Render assistant content in formatted markdown."""
        md = Markdown(markdown_text, code_theme="monokai")
        self.console.print(md)

    def print_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        """Render a formatted blue card for a requested tool call."""
        import json

        args_str = json.dumps(arguments, indent=2)
        code = Syntax(args_str, "json", theme="monokai", line_numbers=False)
        panel = Panel(
            code,
            title=f"[bold #70d6ff]🛠️  Tool Request:[/bold #70d6ff] [bold white]{name}[/bold white]",
            border_style="#0077b6",
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_tool_result(self, name: str, output: str, ok: bool) -> None:
        """Render the output returned from a tool execution."""
        status_color = "#70d6ff" if ok else "#ff4d6d"
        title = f"[{status_color}]Result: {name} ({'OK' if ok else 'ERROR'})[/{status_color}]"
        panel = Panel(
            output.strip() or "(empty)",
            title=title,
            border_style=status_color,
            padding=(0, 1),
        )
        self.console.print(panel)

    def print_info(self, message: str) -> None:
        """Display an informational notification."""
        self.console.print(f"[bold #00b4d8]ℹ[/bold #00b4d8] {message}")

    def print_error(self, message: str) -> None:
        """Display an error notification."""
        self.console.print(f"[bold red]✖ Error:[/bold red] {message}")
