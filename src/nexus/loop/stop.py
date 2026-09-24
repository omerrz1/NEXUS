"""Stop conditions that keep a small model from looping forever."""

import json
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto

from nexus.loop.events import HaltReason
from nexus.messages import ToolCall
from nexus.tools.base import ToolResult

_REPEATS_BEFORE_WARNING = 3
_REPEATS_BEFORE_HALT = 4
_ERRORS_BEFORE_HALT = 5
_EMPTY_REPLIES_BEFORE_HALT = 2


class Signal(Enum):
    """What the loop should do after a tool call."""

    CONTINUE = auto()
    WARN_REPEAT = auto()
    HALT = auto()


@dataclass
class StopTracker:
    """Counts repeated calls and failures during one user turn."""

    halt_reason: HaltReason | None = None
    _repeats: Counter[str] = field(default_factory=Counter)
    _error_streak: int = 0
    _empty_replies: int = 0

    def record_call(self, call: ToolCall, result: ToolResult) -> Signal:
        """Note a finished tool call and say whether the loop should warn or stop."""
        self._empty_replies = 0  # The model is making progress again.
        self._error_streak = 0 if result.ok else self._error_streak + 1
        if self._error_streak >= _ERRORS_BEFORE_HALT:
            return self._halt(HaltReason.ERROR_STREAK)

        # The same call with the same result means no progress. The same call with a new
        # result (running the tests again after a fix) is normal work.
        key = json.dumps([call.name, call.arguments, result.output], sort_keys=True, default=str)
        self._repeats[key] += 1
        if self._repeats[key] >= _REPEATS_BEFORE_HALT:
            return self._halt(HaltReason.REPEATED_CALL)
        if self._repeats[key] >= _REPEATS_BEFORE_WARNING:
            return Signal.WARN_REPEAT
        return Signal.CONTINUE

    def record_unparseable_call(self) -> Signal:
        """Note that the model produced a tool call that could not be read at all."""
        self._error_streak += 1
        if self._error_streak >= _ERRORS_BEFORE_HALT:
            return self._halt(HaltReason.ERROR_STREAK)
        return Signal.CONTINUE

    def record_empty_reply(self) -> Signal:
        """Note a reply with no answer and no tool call. One retry is allowed."""
        self._empty_replies += 1
        if self._empty_replies >= _EMPTY_REPLIES_BEFORE_HALT:
            return self._halt(HaltReason.EMPTY_REPLY)
        return Signal.CONTINUE

    def _halt(self, reason: HaltReason) -> Signal:
        self.halt_reason = reason
        return Signal.HALT
