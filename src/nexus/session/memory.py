"""The model's working memory for one session: a todo list and a few durable notes."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

MAX_TODO_ITEMS = 15
MAX_NOTES = 20
MAX_NOTE_CHARS = 300


class TodoStatus(StrEnum):
    """Where one task stands."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


@dataclass(frozen=True)
class TodoItem:
    """One task on the model's todo list."""

    text: str
    status: TodoStatus = TodoStatus.PENDING


class SessionMemory:
    """What the model keeps for the whole session, however long the conversation grows.

    The tools change it, the CLI shows it, and compaction copies it into the summary so it
    survives every summarizing. It is one shared object: `/new` and `/resume` reload it in
    place, so the tools that hold it never point at stale data.
    """

    def __init__(self) -> None:
        self.todo: list[TodoItem] = []
        self.notes: list[str] = []

    def is_empty(self) -> bool:
        """True when there is no todo list and no notes."""
        return not self.todo and not self.notes

    def clear(self) -> None:
        """Forget everything, for a new session."""
        self.todo.clear()
        self.notes.clear()

    def set_todo(self, items: list[TodoItem]) -> None:
        """Replace the whole todo list."""
        self.todo[:] = items

    def notes_are_full(self) -> bool:
        """True when no more notes can be added."""
        return len(self.notes) >= MAX_NOTES

    def add_note(self, note: str) -> int:
        """Save a note and return its 1-based number."""
        self.notes.append(note.strip())
        return len(self.notes)

    def remove_note(self, number: int) -> str | None:
        """Delete the note with this 1-based number. Returns its text, or None if none matches."""
        if not 1 <= number <= len(self.notes):
            return None
        return self.notes.pop(number - 1)

    def render_todo(self) -> str:
        """The todo list as numbered lines, or an empty string if there is none."""
        return "\n".join(
            f"{number}. [{item.status.value}] {item.text}"
            for number, item in enumerate(self.todo, start=1)
        )

    def render_notes(self) -> str:
        """The notes as numbered lines, or an empty string if there are none."""
        return "\n".join(f"{number}. {note}" for number, note in enumerate(self.notes, start=1))

    def render(self) -> str:
        """Everything worth pinning into a summary, or an empty string if there is nothing."""
        sections = []
        if self.todo:
            sections.append(f"Todo list:\n{self.render_todo()}")
        if self.notes:
            sections.append(f"Session notes:\n{self.render_notes()}")
        return "\n\n".join(sections)

    def to_data(self) -> dict[str, Any]:
        """Plain JSON-friendly data, for saving with the session."""
        return {
            "todo": [{"text": item.text, "status": item.status.value} for item in self.todo],
            "notes": list(self.notes),
        }

    def load(self, data: dict[str, Any]) -> None:
        """Replace everything with data made by `to_data`. Unreadable entries are skipped."""
        self.clear()
        for entry in data.get("todo", []):
            try:
                self.todo.append(TodoItem(str(entry["text"]), TodoStatus(entry["status"])))
            except (KeyError, TypeError, ValueError):
                continue
        self.notes.extend(str(note) for note in data.get("notes", []))
