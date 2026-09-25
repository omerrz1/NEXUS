"""Shared test helpers: a scripted approver and a quick way to build the loop's dependencies."""

from pathlib import Path

from nexus.brain.mock import MockBrain
from nexus.guardrails.approval import Answer, Approval
from nexus.loop import Deps
from nexus.messages import ToolCall
from nexus.session.memory import SessionMemory
from nexus.tools.base import Preview, ToolContext
from nexus.tools.registry import default_registry


class ScriptedApprover:
    """Answers every approval request the same way and remembers what it was asked."""

    def __init__(self, answer: Approval = Approval.ONCE, instead: str = "") -> None:
        self.answer = answer
        self.instead = instead
        self.requests: list[tuple[str, Preview | None, str]] = []

    def approve(self, call: ToolCall, preview: Preview | None, scope: str) -> Answer:
        self.requests.append((call.name, preview, scope))
        return Answer(self.answer, self.instead)


def make_deps(
    workspace: Path,
    brain: MockBrain | None = None,
    approver: ScriptedApprover | None = None,
    max_steps: int = 40,
) -> Deps:
    """Build loop dependencies around a temporary workspace and a mock brain."""
    brain = brain or MockBrain()
    memory = SessionMemory()
    return Deps(
        brain=brain,
        tools=default_registry(memory),
        approver=approver or ScriptedApprover(),
        ctx=ToolContext.for_window(workspace, brain.context_window),
        max_steps=max_steps,
        memory=memory,
    )
