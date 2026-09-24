"""The interface for asking the user before a guarded action runs."""

from enum import StrEnum
from typing import Protocol

from nexus.messages import ToolCall


class Approval(StrEnum):
    """The user's answer to an approval request."""

    ONCE = "once"
    SESSION = "session"
    DENY = "deny"


class Approver(Protocol):
    """Anything that can ask the user for consent, such as the terminal prompt."""

    def approve(self, call: ToolCall, preview: str | None, scope: str) -> Approval:
        """Ask about one tool call. `scope` says what "always allow" would cover."""
        ...
