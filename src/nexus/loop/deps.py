"""Everything the loop needs, passed in explicitly so tests can swap any part."""

from dataclasses import dataclass, field

from nexus.brain.base import Brain
from nexus.guardrails.approval import Approver
from nexus.session.memory import SessionMemory
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
    # The same object the memory tools in `tools` were built with: compaction reads it to
    # keep the todo list and notes when it summarizes.
    memory: SessionMemory = field(default_factory=SessionMemory)
