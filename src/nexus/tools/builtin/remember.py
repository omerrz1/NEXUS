"""remember: save a short note that lasts for the whole session, even after summarizing."""

from pydantic import BaseModel, Field

from nexus.session.memory import MAX_NOTE_CHARS, MAX_NOTES, SessionMemory
from nexus.tools.base import Risk, Tool, ToolContext, ToolResult


class RememberArgs(BaseModel):
    note: str = Field(
        min_length=1,
        max_length=MAX_NOTE_CHARS,
        description="One fact worth keeping, such as a preference or a decision.",
    )


class Remember(Tool[RememberArgs]):
    name = "remember"
    description = (
        "Save a short note for the rest of this session, such as a user preference or a "
        "decision made. Notes are kept word for word when older conversation is summarized."
    )
    args_model = RememberArgs
    risk = Risk.NONE  # It only changes Nexus's own session memory, never the user's files.

    def __init__(self, memory: SessionMemory) -> None:
        self._memory = memory

    def run(self, args: RememberArgs, ctx: ToolContext) -> ToolResult:
        if self._memory.notes_are_full():
            return ToolResult.error(
                f"Memory is full ({MAX_NOTES} notes). Delete one with forget, then try again."
            )
        number = self._memory.add_note(args.note)
        return ToolResult.success(f"Saved as note {number}.")
