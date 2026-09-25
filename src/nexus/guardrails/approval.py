"""The interface for asking the user before a guarded action runs."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from nexus.messages import ToolCall
from nexus.tools.base import Preview


class Approval(StrEnum):
    """The user's decision on an approval request."""

    ONCE = "once"
    SESSION = "session"
    DENY = "deny"


@dataclass(frozen=True)
class Answer:
    """The user's reply to an approval request: the decision, and for a refusal, what they
    want Nexus to do instead, so the model can act on it."""

    approval: Approval
    instead: str = ""


class Approver(Protocol):
    """Anything that can ask the user for consent, such as the terminal prompt."""

    def approve(self, call: ToolCall, preview: Preview | None, scope: str) -> Answer:
        """Ask about one tool call. `scope` says what "always allow" would cover."""
        ...
