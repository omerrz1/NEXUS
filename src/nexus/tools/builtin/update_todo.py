"""update_todo: a task list the model keeps as working memory on multi-step work."""

from pydantic import BaseModel, Field

from nexus.session.memory import MAX_TODO_ITEMS, SessionMemory, TodoItem, TodoStatus
from nexus.tools.base import Risk, Tool, ToolContext, ToolResult


class TodoEntry(BaseModel):
    text: str = Field(max_length=200, description="The task, in a few words.")
    status: TodoStatus = Field(description="pending, in_progress, or done.")


class UpdateTodoArgs(BaseModel):
    items: list[TodoEntry] = Field(
        max_length=MAX_TODO_ITEMS,
        description="The complete list, in order. It replaces the previous list.",
    )


class UpdateTodo(Tool[UpdateTodoArgs]):
    name = "update_todo"
    description = (
        "Keep a task list for work with several steps. Send the whole list each time, "
        "marking tasks in_progress and done as you go."
    )
    args_model = UpdateTodoArgs
    risk = Risk.NONE  # It only changes Nexus's own session memory, never the user's files.

    def __init__(self, memory: SessionMemory) -> None:
        self._memory = memory

    def run(self, args: UpdateTodoArgs, ctx: ToolContext) -> ToolResult:
        self._memory.set_todo([TodoItem(entry.text.strip(), entry.status) for entry in args.items])
        if not self._memory.todo:
            return ToolResult.success("Todo list cleared.")
        return ToolResult.success(f"Todo list saved:\n{self._memory.render_todo()}")
