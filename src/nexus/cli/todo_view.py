"""Draws the model's task list as a checklist."""

from collections.abc import Sequence

from rich.text import Text

from nexus.cli.theme import CYAN, MUTED, OK
from nexus.session.memory import TodoItem, TodoStatus


def todo_text(items: Sequence[TodoItem], indent: str = "  ") -> Text:
    """The tasks one per line, finished ones dimmed and the current one highlighted.

    Built from Text pieces rather than markup, so brackets in a task are shown as written.
    """
    text = Text()
    for item in items:
        if item.status is TodoStatus.DONE:
            text.append(f"{indent}✔ ", style=OK)
            text.append(item.text + "\n", style=f"dim {MUTED}")
        elif item.status is TodoStatus.IN_PROGRESS:
            text.append(f"{indent}◐ ", style=f"bold {CYAN}")
            text.append(item.text + "\n", style="bold")
        else:
            text.append(f"{indent}○ ", style=MUTED)
            text.append(item.text + "\n")
    text.rstrip()
    return text


def todo_progress(items: Sequence[TodoItem]) -> str:
    """How far along the list is, such as "2 of 5 done"."""
    done = sum(item.status is TodoStatus.DONE for item in items)
    return f"{done} of {len(items)} done"
