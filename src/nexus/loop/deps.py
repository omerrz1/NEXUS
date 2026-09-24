"""Everything the loop needs, passed in explicitly so tests can swap any part."""

from dataclasses import dataclass

from nexus.brain.base import Brain
from nexus.guardrails.approval import Approver
from nexus.tools.base import ToolContext
from nexus.tools.registry import ToolRegistry


@dataclass(frozen=True)
class Deps:
    """The parts the loop is wired from."""

    brain: Brain
    tools: ToolRegistry
    approver: Approver
    ctx: ToolContext
    max_steps: int = 40
