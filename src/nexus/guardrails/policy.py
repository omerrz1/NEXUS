"""Decides whether a tool call may run, needs the user's approval, or is refused."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from nexus.guardrails.commands import denied_reason, is_safe_command
from nexus.guardrails.modes import Mode
from nexus.tools.base import Risk, Tool, ToolContext


class Decision(StrEnum):
    """What to do with a tool call."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Verdict:
    """A decision plus, for a denial, the reason the model is told."""

    decision: Decision
    reason: str = ""


ALLOW = Verdict(Decision.ALLOW)
ASK = Verdict(Decision.ASK)


def check_tool_call(tool: Tool[Any], args: BaseModel, mode: Mode, ctx: ToolContext) -> Verdict:
    """Apply the always-on command rules, then the mode's policy for this tool's risk.

    Reading is allowed anywhere so the agent can browse the computer. Writing outside the
    working directory always asks, even in auto mode.
    """
    commands = [str(getattr(args, field)) for field in tool.command_fields]
    for command in commands:
        reason = denied_reason(command, ctx.workspace)
        if reason:
            return Verdict(Decision.DENY, reason)

    if tool.risk is Risk.NETWORK:
        # What leaves the computer could include things the model read, so the user sees it
        # first, in every mode except auto.
        return ALLOW if mode is Mode.AUTO else ASK
    if tool.risk in (Risk.NONE, Risk.READ):
        return ALLOW
    if commands and all(is_safe_command(command) for command in commands):
        return ALLOW  # Read-only commands such as `ls` or `git status` never need asking.

    if mode is Mode.READ_ONLY:
        return Verdict(
            Decision.DENY,
            f"{tool.name} is blocked because the session is in read-only mode. "
            "Tell the user they can allow it with /mode.",
        )
    if mode is Mode.AUTO and _stays_in_workspace(tool, args, ctx):
        return ALLOW
    return ASK


def _stays_in_workspace(tool: Tool[Any], args: BaseModel, ctx: ToolContext) -> bool:
    """True if every path the tool touches is inside the working directory."""
    if tool.risk is Risk.EXEC:
        return True  # Commands are judged by the deny-list, not by where they point.
    paths: list[Path] = [ctx.resolve(str(getattr(args, field))) for field in tool.path_fields]
    return all(ctx.contains(path) for path in paths)
