"""forget: delete one saved session note."""

from pydantic import BaseModel, Field

from nexus.session.memory import SessionMemory
from nexus.tools.base import Risk, Tool, ToolContext, ToolResult


class ForgetArgs(BaseModel):
    number: int = Field(ge=1, description="The note's number, as shown when it was saved.")


class Forget(Tool[ForgetArgs]):
    name = "forget"
    description = "Delete a saved note by its number, for example when it is wrong or out of date."
    args_model = ForgetArgs
    risk = Risk.NONE  # It only changes Nexus's own session memory, never the user's files.

    def __init__(self, memory: SessionMemory) -> None:
        self._memory = memory

    def run(self, args: ForgetArgs, ctx: ToolContext) -> ToolResult:
        removed = self._memory.remove_note(args.number)
        if removed is None:
            count = len(self._memory.notes)
            plural = "" if count == 1 else "s"
            return ToolResult.error(
                f"There is no note {args.number}. You have {count} note{plural}."
            )
        return ToolResult.success(f"Deleted note {args.number}: {removed}")
