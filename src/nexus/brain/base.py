"""Protocols and plain data models defining the brain interface."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from nexus.messages import Message, ToolCall, ToolSpec, Usage

# Where Nexus looks for a model when nothing else is said. The window is the context size the
# model server should be running with; Nexus sizes tool output and old history to fit it.
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"
DEFAULT_MODEL = "nexus-qwen"
DEFAULT_CONTEXT_WINDOW = 16384


class Depth(StrEnum):
    """How long the model may think before it answers. Less thinking is faster."""

    FAST = "fast"  # no thinking: the answer starts almost immediately
    BALANCED = "balanced"  # the model's own default amount of thinking
    DEEP = "deep"  # the most thinking the server allows; slowest


@dataclass(frozen=True)
class BrainReply:
    """The reply returned by a model brain after completing a turn."""

    message: Message
    tool_calls: tuple[ToolCall, ...]
    usage: Usage
    tool_call_errors: tuple[str, ...] = ()  # tool calls the model made that could not be read
    cut_off: bool = False  # the server stopped the reply because it ran out of room


class Brain(Protocol):
    """Protocol for local model adapters turning conversations into replies."""

    @property
    def context_window(self) -> int:
        """The total token context window size for this brain."""
        ...

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        depth: Depth = Depth.BALANCED,
    ) -> BrainReply:
        """Send conversation history and optional tools, streaming tokens via callbacks."""
        ...
