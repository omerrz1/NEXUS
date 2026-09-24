"""The permission modes a session can run in."""

from enum import StrEnum


class Mode(StrEnum):
    """How much the agent may do without asking the user first."""

    READ_ONLY = "read-only"
    ASK = "ask"
    AUTO = "auto"
