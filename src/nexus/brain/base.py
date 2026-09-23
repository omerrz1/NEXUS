"""Protocols and plain data models defining the brain interface."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from nexus.messages import Message, ToolCall, ToolSpec, Usage


@dataclass(frozen=True)
class BrainReply:
    """The reply returned by a model brain after completing a turn."""

    message: Message
    tool_calls: tuple[ToolCall, ...]
    usage: Usage


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
    ) -> BrainReply:
        """Send conversation history and optional tools, streaming tokens via callbacks."""
        ...
