"""Tests for the tools that keep the model's todo list and session notes."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from nexus.session.memory import MAX_NOTE_CHARS, MAX_NOTES, SessionMemory, TodoStatus
from nexus.tools.base import ToolContext, ToolResult
from nexus.tools.registry import default_registry


@pytest.fixture
def memory() -> SessionMemory:
    return SessionMemory()


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext.for_window(tmp_path, 16384)


def run(memory: SessionMemory, ctx: ToolContext, name: str, **arguments: Any) -> ToolResult:
    tool = default_registry(memory).get(name)
    assert tool is not None
    return tool.run(tool.args_model(**arguments), ctx)


def todo(*entries: tuple[str, str]) -> list[dict[str, str]]:
    return [{"text": text, "status": status} for text, status in entries]


# ---- update_todo


def test_update_todo_replaces_the_whole_list_and_echoes_it(
    memory: SessionMemory, ctx: ToolContext
) -> None:
    items = todo(("read the code", "done"), ("fix it", "in_progress"), ("test it", "pending"))
    result = run(memory, ctx, "update_todo", items=items)
    assert result.ok and result.output == (
        "Todo list saved:\n1. [done] read the code\n2. [in_progress] fix it\n3. [pending] test it"
    )
    assert [item.status for item in memory.todo] == [
        TodoStatus.DONE,
        TodoStatus.IN_PROGRESS,
        TodoStatus.PENDING,
    ]

    run(memory, ctx, "update_todo", items=todo(("only this", "pending")))
    assert [item.text for item in memory.todo] == ["only this"]


def test_an_empty_list_clears_the_todo(memory: SessionMemory, ctx: ToolContext) -> None:
    run(memory, ctx, "update_todo", items=todo(("x", "pending")))
    result = run(memory, ctx, "update_todo", items=[])
    assert result.ok and "cleared" in result.output and memory.todo == []


def test_update_todo_rejects_what_a_small_model_might_send(
    memory: SessionMemory, ctx: ToolContext
) -> None:
    tool = default_registry(memory).get("update_todo")
    assert tool is not None
    with pytest.raises(ValidationError):
        tool.args_model(items=todo(("x", "someday")))
    with pytest.raises(ValidationError):
        tool.args_model(items=todo(*[(f"task {n}", "pending") for n in range(16)]))
    with pytest.raises(ValidationError):
        tool.args_model(items=todo(("x" * 201, "pending")))


def test_update_todo_schema_is_flat_and_lists_the_statuses() -> None:
    spec = default_registry().get("update_todo").spec()  # type: ignore[union-attr]
    entry = spec.parameters["properties"]["items"]["items"]
    assert entry["properties"]["status"]["enum"] == ["pending", "in_progress", "done"]
    assert "pending, in_progress, or done" in entry["properties"]["status"]["description"]


# ---- remember and forget


def test_remember_saves_numbered_notes(memory: SessionMemory, ctx: ToolContext) -> None:
    assert run(memory, ctx, "remember", note="prefers tabs").output == "Saved as note 1."
    assert run(memory, ctx, "remember", note="uses zsh").output == "Saved as note 2."
    assert memory.notes == ["prefers tabs", "uses zsh"]


def test_remember_refuses_when_memory_is_full_and_says_how_to_make_room(
    memory: SessionMemory, ctx: ToolContext
) -> None:
    for number in range(MAX_NOTES):
        run(memory, ctx, "remember", note=f"note {number}")
    result = run(memory, ctx, "remember", note="one too many")
    assert not result.ok and "forget" in result.output and len(memory.notes) == MAX_NOTES


def test_remember_rejects_empty_and_oversized_notes(memory: SessionMemory) -> None:
    tool = default_registry(memory).get("remember")
    assert tool is not None
    with pytest.raises(ValidationError):
        tool.args_model(note="")
    with pytest.raises(ValidationError):
        tool.args_model(note="x" * (MAX_NOTE_CHARS + 1))


def test_forget_deletes_a_note_and_the_rest_are_renumbered(
    memory: SessionMemory, ctx: ToolContext
) -> None:
    for note in ("a", "b", "c"):
        run(memory, ctx, "remember", note=note)
    result = run(memory, ctx, "forget", number=2)
    assert result.ok and "Deleted note 2: b" in result.output
    assert memory.notes == ["a", "c"]


def test_forget_with_a_wrong_number_says_how_many_notes_there_are(
    memory: SessionMemory, ctx: ToolContext
) -> None:
    run(memory, ctx, "remember", note="only one")
    result = run(memory, ctx, "forget", number=5)
    assert not result.ok and "no note 5" in result.output and "You have 1 note." in result.output
    with pytest.raises(ValidationError):
        default_registry(memory).get("forget").args_model(number=0)  # type: ignore[union-attr]


def test_the_tools_use_the_memory_they_were_given_not_a_shared_one() -> None:
    mine, other = SessionMemory(), SessionMemory()
    tool = default_registry(mine).get("remember")
    assert tool is not None
    tool.run(tool.args_model(note="x"), ToolContext(workspace=Path("/")))
    assert mine.notes == ["x"] and other.notes == []
