"""The events the loop reports while it works. The terminal turns them into output."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from nexus.messages import ToolCall, Usage
from nexus.tools.base import ToolResult


class HaltReason(StrEnum):
    """Why the loop stopped before the model gave a final answer."""

    MAX_STEPS = "max_steps"
    REPEATED_CALL = "repeated_call"
    ERROR_STREAK = "error_streak"
    CONTEXT_FULL = "context_full"
    REPLY_CUT_OFF = "reply_cut_off"
    EMPTY_REPLY = "empty_reply"


@dataclass(frozen=True)
class ModelStarted:
    """The model is about to be asked for its next reply."""

    step: int


@dataclass(frozen=True)
class ReasoningDelta:
    """A piece of the model's reasoning."""

    text: str


@dataclass(frozen=True)
class TextDelta:
    """A piece of the model's answer."""

    text: str


@dataclass(frozen=True)
class ModelFinished:
    """The model's reply is complete."""

    usage: Usage


@dataclass(frozen=True)
class ToolRequested:
    """The model asked for a tool. Approval, if needed, happens after this."""

    call: ToolCall


@dataclass(frozen=True)
class ToolStarted:
    """A tool is running now (it was allowed or approved)."""

    call: ToolCall


@dataclass(frozen=True)
class ToolFinished:
    """A tool call ended: it ran, or it was refused, or its arguments were invalid."""

    call: ToolCall
    result: ToolResult


@dataclass(frozen=True)
class Notice:
    """Something the user should know about that is not an error, such as a retry."""

    text: str


@dataclass(frozen=True)
class Compacted:
    """Older messages were replaced by a summary so the conversation can keep going."""

    replaced: int
    tokens_before: int
    tokens_after: int


@dataclass(frozen=True)
class Halted:
    """The loop gave up. `message` explains why in words for the user."""

    reason: HaltReason
    message: str


Event = (
    ModelStarted
    | ReasoningDelta
    | TextDelta
    | ModelFinished
    | ToolRequested
    | ToolStarted
    | ToolFinished
    | Notice
    | Compacted
    | Halted
)
EventHandler = Callable[[Event], None]
