"""Live view of one model turn: an animated status line, then the answer as Markdown."""

import sys
import termios
import threading
import time
from enum import Enum, auto
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.text import Text

from nexus.cli.theme import CYAN, MUTED, OCEAN, SKY, shimmer, spinner_frame

_THOUGHT_PEEK_LINES = 4


class QuietKeyboard:
    """Stops the terminal from echoing keys while a turn streams.

    Echoed keys would be drawn over the live area and break its redraws. The keys are not
    lost: they stay in the input buffer and show up in the next prompt.
    """

    def __init__(self) -> None:
        self._saved: list[Any] | None = None

    def __enter__(self) -> "QuietKeyboard":
        if sys.stdin.isatty():
            fd = sys.stdin.fileno()
            self._saved = termios.tcgetattr(fd)
            quiet = termios.tcgetattr(fd)
            quiet[3] &= ~(termios.ECHO | termios.ICANON)  # ISIG stays on, so Ctrl-C works.
            termios.tcsetattr(fd, termios.TCSANOW, quiet)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._saved is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, self._saved)
            self._saved = None


class Phase(Enum):
    """Where the turn is: waiting for the first token, thinking, or writing the answer."""

    WAITING = auto()
    THINKING = auto()
    ANSWERING = auto()


def split_finished_blocks(markdown: str) -> tuple[str, str]:
    """Split Markdown into finished blocks and the block still being written.

    A block is finished at a blank line outside a code fence, or when a fence closes.
    Printing finished blocks for good keeps the live area small, so long answers
    scroll normally instead of fighting the terminal height.
    """
    in_fence = False
    cut = 0
    position = 0
    for line in markdown.splitlines(keepends=True):
        position += len(line)
        if not line.endswith("\n"):
            break  # The last line is still streaming.
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if not in_fence:
                cut = position
        elif not in_fence and not line.strip():
            cut = position
    return markdown[:cut], markdown[cut:]


class TurnView:
    """Renders one turn. Rich redraws it on a timer, which is what drives the animation."""

    def __init__(self, console: Console, show_thinking: bool) -> None:
        self.console = console
        self.show_thinking = show_thinking
        self.phase = Phase.WAITING
        self.reasoning = ""
        self.answer_tail = ""
        self.tokens = 0
        self.started = time.perf_counter()
        self.first_token_at: float | None = None
        self.thinking_seconds = 0.0
        self._lock = threading.Lock()  # Rich's refresh thread renders while tokens arrive.
        self._live: Live | None = None
        self._keyboard = QuietKeyboard()

    @property
    def is_animated(self) -> bool:
        return self.console.is_terminal

    def start(self) -> None:
        if self.is_animated:
            self._keyboard.__enter__()
            self._live = Live(self, console=self.console, refresh_per_second=20, transient=True)
            self._live.start()

    def add_reasoning(self, chunk: str) -> None:
        with self._lock:
            self._count_token()
            self.reasoning += chunk
            self.phase = Phase.THINKING

    def add_answer(self, chunk: str) -> None:
        # Printing happens after the lock is released: rich's refresh thread holds its own
        # lock while it renders this view, so printing under ours could deadlock.
        finished = ""
        with self._lock:
            self._count_token()
            is_first_chunk = self.phase is not Phase.ANSWERING
            if is_first_chunk:
                self.thinking_seconds = self._elapsed()
                self.phase = Phase.ANSWERING
            if self.is_animated:
                finished, self.answer_tail = split_finished_blocks(self.answer_tail + chunk)

        if is_first_chunk:
            self._print_answer_header()
        if not self.is_animated:
            self.console.file.write(chunk)  # Piped output stays plain text.
        elif finished.strip():
            # Blocks are rendered one at a time, so the gap between them is added here.
            self.console.print(_answer_markdown(finished))
            self.console.print()

    def finish(self) -> tuple[float, float]:
        """Stop the animation, print what is left, and return (elapsed, tokens per second)."""
        if self._live is not None:
            self._live.stop()
        self._keyboard.__exit__()
        if self.phase is not Phase.ANSWERING:
            self._print_thinking_summary()
        if self.answer_tail.strip():
            self.console.print(_answer_markdown(self.answer_tail))
        elif not self.is_animated and self.phase is Phase.ANSWERING:
            self.console.print()
        return self._print_footer()

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        with self._lock:
            yield from self._live_renderables()

    def _live_renderables(self) -> list[RenderableType]:
        elapsed = time.perf_counter() - self.started
        if self.phase is Phase.ANSWERING:
            parts: list[RenderableType] = []
            if self.answer_tail.strip():
                parts.append(_answer_markdown(self.answer_tail))
            parts.append(Text(f"  {spinner_frame(elapsed)} writing", style=f"dim {CYAN}"))
            return parts

        label = "Thinking" if self.phase is Phase.THINKING else "Reading your prompt"
        status = Text("  ")
        status.append(spinner_frame(elapsed) + " ", style=f"bold {SKY}")
        status.append_text(shimmer(label + "…", elapsed))
        status.append(f"  {elapsed:.1f}s", style=MUTED)
        if self.tokens:
            status.append(f" · {self.tokens} tok", style=MUTED)
        status.append("  ctrl-c to stop", style=f"dim {MUTED}")
        parts = [status]
        if self.show_thinking and self.reasoning.strip():
            peek = self.reasoning.strip().splitlines()[-_THOUGHT_PEEK_LINES:]
            parts.append(Padding(Text("\n".join(peek), style=f"italic {MUTED}"), (0, 0, 0, 4)))
        return parts

    def _count_token(self) -> None:
        if self.first_token_at is None:
            self.first_token_at = time.perf_counter()
        self.tokens += 1

    def _print_answer_header(self) -> None:
        """Mark the switch from thinking to answering: a thinking summary, then a header."""
        self._print_thinking_summary()
        header = Text("● ", style=f"bold {CYAN}")
        header.append("Nexus", style=f"bold {SKY}")
        self.console.print(header)

    def _print_thinking_summary(self) -> None:
        if not self.reasoning.strip():
            return
        summary = Text("  ✻ ", style=f"bold {OCEAN}")
        summary.append(f"Thought for {self.thinking_seconds or self._elapsed():.1f}s", CYAN)
        if not self.show_thinking:
            summary.append("  /thoughts to view", style=f"dim {MUTED}")
        self.console.print(summary)
        if self.show_thinking:
            thought = Text(self.reasoning.strip(), style=f"italic {MUTED}")
            self.console.print(Padding(thought, (0, 0, 0, 4)))

    def _print_footer(self) -> tuple[float, float]:
        elapsed = max(self._elapsed(), 0.01)
        generating = time.perf_counter() - (self.first_token_at or self.started)
        speed = self.tokens / max(generating, 0.01)
        if self.tokens:
            footer = Text(f"  ✔ {elapsed:.1f}s · {self.tokens} tok · {speed:.1f} tok/s", MUTED)
            self.console.print(footer)
        self.console.print()
        return elapsed, speed

    def _elapsed(self) -> float:
        return time.perf_counter() - self.started


def _answer_markdown(text: str) -> RenderableType:
    """Answer text is indented under the header so the conversation reads as a thread."""
    return Padding(Group(Markdown(text.strip("\n"), code_theme="monokai")), (0, 0, 0, 2))
