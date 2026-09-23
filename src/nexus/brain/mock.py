"""Scripted and programmable brain implementation for deterministic unit testing."""

from collections.abc import Callable

from nexus.brain.base import BrainReply
from nexus.messages import Message, ToolCall, ToolSpec, Usage


class MockBrain:
    """A mock model brain returning predetermined replies for tests."""

    def __init__(
        self,
        replies: list[BrainReply] | None = None,
        context_window: int = 16384,
        responder: Callable[[list[Message]], BrainReply] | None = None,
    ) -> None:
        self._replies: list[BrainReply] = list(replies) if replies is not None else []
        self._context_window: int = context_window
        self._responder: Callable[[list[Message]], BrainReply] | None = responder
        self.calls: list[tuple[list[Message], list[ToolSpec] | None]] = []

    @property
    def context_window(self) -> int:
        """The configured mock context window size."""
        return self._context_window

    def queue_reply(self, message: Message, tool_calls: tuple[ToolCall, ...] = ()) -> None:
        """Queue a scripted brain reply."""
        self._replies.append(
            BrainReply(
                message=message,
                tool_calls=tool_calls,
                usage=Usage.empty(),
            )
        )

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ) -> BrainReply:
        """Record the call and return the next scripted or generated reply."""
        self.calls.append((list(messages), list(tools) if tools is not None else None))

        if self._responder is not None:
            reply = self._responder(messages)
        elif self._replies:
            reply = self._replies.pop(0)
        else:
            reply = BrainReply(
                message=Message.assistant("Mock brain: no replies left."),
                tool_calls=(),
                usage=Usage.empty(),
            )

        if on_delta is not None and reply.message.content:
            on_delta(reply.message.content)

        return reply
