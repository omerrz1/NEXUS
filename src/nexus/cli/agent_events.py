"""Turns the events the agent loop reports into terminal output."""

from rich.status import Status

from nexus.cli.render import CliRenderer
from nexus.cli.theme import CYAN
from nexus.loop.events import (
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


class EventPrinter:
    """Handles loop events. Call close() if a turn is cut short so nothing is left running."""

    def __init__(self, out: CliRenderer) -> None:
        self.out = out
        self.speed = 0.0  # Tokens per second of the last model reply.
        self._status: Status | None = None

    def __call__(self, event: Event) -> None:
        match event:
            case ModelStarted():
                self.out.start_stream()
            case ReasoningDelta(text):
                self.out.print_reasoning_chunk(text)
            case TextDelta(text):
                self.out.print_chunk(text)
            case ModelFinished():
                self.speed = self.out.end_stream() or self.speed
            case ToolRequested(call):
                self.out.print_tool_call(call.name, call.arguments)
            case ToolStarted(call):
                self._start_spinner(call.name)
            case ToolFinished(call, result):
                self._stop_spinner()
                self.out.print_tool_result(result.output, result.ok)
            case Notice(text):
                self.out.print_info(text)
            case Halted(_, message):
                self.out.print_error(message)

    def close(self) -> None:
        """Stop the spinner and any stream that is still being drawn."""
        self._stop_spinner()
        self.out.end_stream()

    def _start_spinner(self, tool_name: str) -> None:
        self._status = self.out.console.status(
            f"running {tool_name}…  ctrl-c to stop", spinner="dots", spinner_style=CYAN
        )
        self._status.start()

    def _stop_spinner(self) -> None:
        if self._status is not None:
            self._status.stop()
            self._status = None
