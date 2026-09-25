"""Tests for the session memory: the todo list and the notes."""

from nexus.session.memory import MAX_NOTES, SessionMemory, TodoItem, TodoStatus


def filled_memory() -> SessionMemory:
    memory = SessionMemory()
    memory.set_todo(
        [
            TodoItem("read the config", TodoStatus.DONE),
            TodoItem("fix the bug", TodoStatus.IN_PROGRESS),
            TodoItem("run the tests"),
        ]
    )
    memory.add_note("The user prefers tabs")
    return memory


def test_a_new_memory_is_empty_and_renders_nothing() -> None:
    memory = SessionMemory()
    assert memory.is_empty() and memory.render() == ""


def test_the_todo_list_and_notes_render_as_numbered_lines() -> None:
    memory = filled_memory()
    assert memory.render_todo().splitlines() == [
        "1. [done] read the config",
        "2. [in_progress] fix the bug",
        "3. [pending] run the tests",
    ]
    assert memory.render_notes() == "1. The user prefers tabs"
    pinned = memory.render()
    assert pinned.startswith("Todo list:\n1.") and "\n\nSession notes:\n1." in pinned


def test_setting_the_todo_list_replaces_the_old_one() -> None:
    memory = filled_memory()
    memory.set_todo([TodoItem("only task")])
    assert [item.text for item in memory.todo] == ["only task"]


def test_notes_are_numbered_from_one_and_can_be_removed() -> None:
    memory = SessionMemory()
    assert memory.add_note("  first  ") == 1 and memory.add_note("second") == 2
    assert memory.notes[0] == "first"  # surrounding spaces are dropped
    assert memory.remove_note(1) == "first"
    assert memory.notes == ["second"]
    assert memory.remove_note(0) is None and memory.remove_note(5) is None


def test_notes_have_a_limit() -> None:
    memory = SessionMemory()
    for number in range(MAX_NOTES):
        assert not memory.notes_are_full()
        memory.add_note(f"note {number}")
    assert memory.notes_are_full()


def test_memory_survives_saving_and_loading() -> None:
    saved = filled_memory().to_data()
    restored = SessionMemory()
    restored.add_note("left over from another session")
    restored.load(saved)
    assert restored.to_data() == saved  # and the leftover note is gone


def test_loading_skips_entries_that_cannot_be_read() -> None:
    memory = SessionMemory()
    memory.load(
        {
            "todo": [
                {"text": "good", "status": "done"},
                {"text": "bad status", "status": "someday"},
                {"status": "done"},
                "not even a dict",
            ],
            "notes": ["kept"],
        }
    )
    assert [item.text for item in memory.todo] == ["good"] and memory.notes == ["kept"]


def test_clear_forgets_everything() -> None:
    memory = filled_memory()
    memory.clear()
    assert memory.is_empty()
