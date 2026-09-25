"""Turns the events the agent loop reports into terminal output."""

from rich.status import Status
from rich.text import Text

from nexus.cli.render import CliRenderer
from nexus.cli.theme import CYAN, MUTED
from nexus.cli.todo_view import todo_progress, todo_text
from nexus.loop.events import (
    Compacted,
    Event,
    Halted,
    ModelFinished,
    ModelStarted,
    Notice,
    ReasoningDelta,
    TextDelta,
    ToolFinished,
    ToolRequested,
    ToolStarted,
)
from nexus.session.memory import SessionMemory


class EventPrinter:
    """Handles loop events. Call close() if a turn is cut short so nothing is left running."""

    def __init__(self, out: CliRenderer, memory: SessionMemory | None = None) -> None:
        self.out = out
        self.speed = 0.0  # Tokens per second of the last model reply.
        self.context_tokens = 0  # How much of the context window the last request used.
        self._memory = memory
        self._status: Status | None = None

    def __call__(self, event: Event) -> None:
        match event:
            case ModelStarted():
                self.out.start_stream()
            case ReasoningDelta(text):
                self.out.print_reasoning_chunk(text)
            case TextDelta(text):
                self.out.print_chunk(text)
            case ModelFinished(usage):
                self.speed = self.out.end_stream() or self.speed
                if usage.prompt_tokens:
                    self.context_tokens = usage.prompt_tokens + usage.completion_tokens
            case ToolRequested(call):
                self.out.print_tool_call(call.name, call.arguments)
            case ToolStarted(call):
                self._start_spinner(call.name)
            case ToolFinished(call, result):
                self._stop_spinner()
                if call.name == "update_todo" and result.ok and self._memory is not None:
                    self._print_plan(self._memory)
                else:
                    self.out.print_tool_result(result.output, result.ok)
            case Notice(text):
                self.out.print_info(text)
            case Compacted(replaced, before, after):
                self.out.print_info(
                    f"Summarized {replaced} older messages ({before:,} → {after:,} tokens)."
                )
            case Halted(_, message):
                self.out.print_error(message)

    def close(self) -> None:
        """Stop the spinner and any stream that is still being drawn."""
        self._stop_spinner()
        self.out.end_stream()

    def _print_plan(self, memory: SessionMemory) -> None:
        """Show the task list as a checklist instead of the tool's plain-text reply."""
        if not memory.todo:
            self.out.print_info("Plan cleared.")
            return
        heading = Text("    ☰ Plan  ", style="bold")
        heading.append(todo_progress(memory.todo), style=MUTED)
        self.out.console.print(heading)
        self.out.console.print(todo_text(memory.todo, indent="      "))

    def _start_spinner(self, tool_name: str) -> None:
        self._status = self.out.console.status(
            f"running {tool_name}…  ctrl-c to stop", spinner="dots", spinner_style=CYAN
        )
        self._status.start()

    def _stop_spinner(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None
