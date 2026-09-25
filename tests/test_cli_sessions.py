"""Tests for the session, memory, and compaction commands, and for saving as the REPL runs."""

import io
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from nexus.brain.base import BrainReply
from nexus.brain.mock import MockBrain
from nexus.cli.agent_events import EventPrinter
from nexus.cli.render import CliRenderer
from nexus.cli.repl import _run_agent_turn
from nexus.cli.session_commands import attach_session, open_session
from nexus.cli.slash import handle_slash_command
from nexus.context.compaction import is_summary
from nexus.loop import Deps
from nexus.messages import Message, Role, Usage
from nexus.session.memory import TodoItem, TodoStatus
from nexus.session.store import Session, SessionStore
from tests.helpers import make_deps


class Screen:
    """A console that records what it prints, plus the command dispatcher bound to it."""

    def __init__(self) -> None:
        self.output = io.StringIO()
        self.console = Console(file=self.output, width=110, force_terminal=False, color_system=None)

    def text(self) -> str:
        return self.output.getvalue()


@pytest.fixture
def screen() -> Screen:
    return Screen()


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


@pytest.fixture
def deps(tmp_path: Path) -> Deps:
    (tmp_path / "work").mkdir()
    return make_deps(tmp_path / "work", MockBrain(responder=lambda messages: summary()))


def summary(text: str = "- summarized") -> BrainReply:
    return BrainReply(Message.assistant(text), (), Usage(3, 2, 5))


def start(deps: Deps, store: SessionStore | None, resume: str | None = None) -> dict[str, Any]:
    """The state the REPL keeps, for a new session or a resumed one."""
    session, _ = open_session(deps, store, resume)
    context: dict[str, Any] = {"deps": deps, "store": store, "mode": "ask", "depth": "balanced"}
    attach_session(context, session)
    return context


def finish_turn(context: dict[str, Any], question: str, answer: str = "ok") -> None:
    """Add a finished turn to the current session and save it, as the REPL does."""
    current: Session = context["current"]
    current.title = current.title or question
    current.messages += [Message.user(question), Message.assistant(answer)]
    current.turns += 1
    context["store"].save(current)


def command(screen: Screen, line: str, context: dict[str, Any]) -> str:
    """Run a slash command and return only what that command printed."""
    screen.output.seek(0)
    screen.output.truncate()
    handle_slash_command(line, context, screen.console)
    return screen.text()


# ---- /new


def test_new_saves_the_current_session_and_starts_an_empty_one(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    finish_turn(context, "first question")
    deps.memory.add_note("prefers tabs")
    old_id = context["current"].id

    output = command(screen, "/new", context)

    assert "Started a new session" in output
    current: Session = context["current"]
    assert current.id != old_id and [m.role for m in current.messages] == [Role.SYSTEM]
    assert context["messages"] is current.messages and deps.memory.is_empty()
    assert (context["tokens"], context["turns"]) == (0, 0)
    saved = store.list_sessions()
    assert [info.id for info in saved] == [old_id]  # the empty new one is not saved


# ---- /sessions and /resume


def two_sessions(deps: Deps, store: SessionStore, screen: Screen) -> dict[str, Any]:
    context = start(deps, store)
    finish_turn(context, "explain the parser")
    deps.memory.add_note("parser note")
    command(screen, "/new", context)
    finish_turn(context, "fix the login bug")
    return context


def test_sessions_lists_newest_first_and_marks_the_current_one(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = two_sessions(deps, store, screen)
    output = command(screen, "/sessions", context)
    assert output.index("fix the login bug") < output.index("explain the parser")
    assert "●" in output and "/resume <number>" in output


def test_sessions_says_so_when_there_are_none(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    assert "No saved sessions yet" in command(screen, "/sessions", start(deps, store))


def test_resume_brings_back_the_messages_and_memory_and_saves_the_current_one_first(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = two_sessions(deps, store, screen)
    deps.memory.set_todo([TodoItem("ship it", TodoStatus.IN_PROGRESS)])
    finish_turn(context, "another question")  # saves the todo list with the second session
    second_id = context["current"].id

    output = command(screen, "/resume 2", context)  # 2 = the older one

    assert "Resumed" in output and "explain the parser" in output
    current: Session = context["current"]
    assert current.title == "explain the parser" and context["messages"] is current.messages
    assert deps.memory.notes == ["parser note"] and deps.memory.todo == []
    assert current.messages[0].role is Role.SYSTEM  # a fresh system prompt
    assert context["turns"] == current.turns == 1
    # And the one we left is intact, todo list included.
    loaded = store.load(second_id, deps.memory.__class__())
    assert loaded is not None and loaded.turns == 2


def test_resume_shows_where_the_conversation_left_off(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = two_sessions(deps, store, screen)
    output = command(screen, "/resume 2", context)
    assert "you:   explain the parser" in output and "nexus: ok" in output


def test_resume_by_id_prefix_and_unknown_and_current(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = two_sessions(deps, store, screen)
    older_id = store.list_sessions()[1].id
    # Both sessions were made in the same second, so only the random end tells them apart.
    assert "Resumed" in command(screen, f"/resume {older_id[:-1]}", context)

    assert "No saved session matches 'nothing'" in command(screen, "/resume nothing", context)
    current_id = context["current"].id
    assert "already in that session" in command(screen, f"/resume {current_id}", context)


def test_resume_without_an_argument_opens_a_menu(
    deps: Deps, store: SessionStore, screen: Screen, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = two_sessions(deps, store, screen)
    offered: list[str] = []

    def choose(title: str, choices: Any) -> Any:
        offered.extend(choice.label for choice in choices)
        return choices[1].value

    monkeypatch.setattr("nexus.cli.session_commands.pick", choose)
    command(screen, "/resume", context)
    assert offered == ["fix the login bug", "explain the parser"]
    assert context["current"].title == "explain the parser"


def test_cancelling_the_menu_changes_nothing(
    deps: Deps, store: SessionStore, screen: Screen, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = two_sessions(deps, store, screen)
    before = context["current"]
    monkeypatch.setattr("nexus.cli.session_commands.pick", lambda title, choices: None)
    command(screen, "/resume", context)
    assert context["current"] is before


def test_a_damaged_session_cannot_be_resumed_and_leaves_things_as_they_were(
    deps: Deps, store: SessionStore, screen: Screen, tmp_path: Path
) -> None:
    context = two_sessions(deps, store, screen)
    older = store.list_sessions()[1]
    (tmp_path / "sessions" / f"{older.id}.json").write_text("{ broken")
    before = context["current"]
    # The damaged file no longer lists, so it cannot even be picked by number 2.
    assert "No saved session matches" in command(screen, "/resume 2", context)
    assert context["current"] is before


def test_sessions_are_not_available_when_nothing_is_being_saved(deps: Deps, screen: Screen) -> None:
    context = start(deps, None)
    for line in ("/sessions", "/resume", "/delete"):
        assert "not being saved" in command(screen, line, context)


# ---- starting up


def test_startup_resumes_the_latest_session_from_this_folder(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = two_sessions(deps, store, screen)
    expected = context["current"].id
    session, warning = open_session(deps, store, "")
    assert warning is None and session.id == expected
    assert deps.memory.notes == []  # the newer session had no notes


def test_startup_resume_by_number(deps: Deps, store: SessionStore, screen: Screen) -> None:
    two_sessions(deps, store, screen)
    session, warning = open_session(deps, store, "2")
    assert warning is None and session.title == "explain the parser"
    assert deps.memory.notes == ["parser note"]


def test_startup_falls_back_to_a_new_session_with_a_warning(
    deps: Deps, store: SessionStore
) -> None:
    fresh, warning = open_session(deps, store, "")
    assert fresh.turns == 0 and warning == "No earlier session here; starting a new one."
    _, warning = open_session(deps, store, "zzz")
    assert warning == "No saved session matches 'zzz'; starting a new one."


def test_startup_without_resume_is_always_a_fresh_session(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    two_sessions(deps, store, screen)
    deps.memory.add_note("stale")
    session, warning = open_session(deps, store, None)
    assert warning is None and session.turns == 0 and deps.memory.is_empty()


# ---- /rename and /delete


def test_rename_changes_the_title_and_saves(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    finish_turn(context, "old title")
    assert "Renamed to new name" in command(screen, "/rename new name", context)
    assert [info.title for info in store.list_sessions()] == ["new name"]
    assert "Usage: /rename" in command(screen, "/rename", context)


def test_delete_removes_another_session_but_never_the_current_one(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = two_sessions(deps, store, screen)
    assert "session you are in" in command(screen, "/delete 1", context)
    assert len(store.list_sessions()) == 2

    assert "Deleted explain the parser" in command(screen, "/delete 2", context)
    assert [info.title for info in store.list_sessions()] == ["fix the login bug"]
    assert "No saved session matches '9'" in command(screen, "/delete 9", context)


# ---- /memory and /todo


def test_memory_shows_adds_and_forgets_notes(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    finish_turn(context, "hello")
    assert "No notes yet" in command(screen, "/memory", context)

    assert "Saved as note 1" in command(screen, "/memory add the user prefers tabs", context)
    assert deps.memory.notes == ["the user prefers tabs"]
    assert "1. the user prefers tabs" in command(screen, "/memory", context)
    assert store.load(context["current"].id, deps.memory.__class__()).memory.notes == [  # type: ignore[union-attr]
        "the user prefers tabs"
    ]  # saved straight away

    assert "Deleted note 1" in command(screen, "/memory forget 1", context)
    assert deps.memory.notes == []


def test_memory_reports_bad_input_instead_of_failing(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    assert "Usage: /memory add" in command(screen, "/memory add", context)
    assert "too long" in command(screen, f"/memory add {'x' * 301}", context)
    assert "Usage: /memory forget" in command(screen, "/memory forget two", context)
    assert "no note 3" in command(screen, "/memory forget 3", context)
    assert "Usage: /memory [add" in command(screen, "/memory wipe", context)
    for number in range(20):
        deps.memory.add_note(f"note {number}")
    assert "Memory is full" in command(screen, "/memory add one more", context)


def test_notes_with_square_brackets_are_shown_as_written(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    deps.memory.add_note("use [bold]markup[/bold] literally")
    assert "use [bold]markup[/bold] literally" in command(screen, "/memory", context)


def test_todo_shows_the_task_list_with_marks(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    assert "No task list yet" in command(screen, "/todo", context)
    deps.memory.set_todo(
        [
            TodoItem("read", TodoStatus.DONE),
            TodoItem("fix [it]", TodoStatus.IN_PROGRESS),
            TodoItem("test"),
        ]
    )
    output = command(screen, "/todo", context)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    assert lines[:3] == ["✔ read", "◐ fix [it]", "○ test"] and lines[3] == "1 of 3 done"


# ---- /compact


def test_compact_summarizes_the_older_conversation_and_saves(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    context = start(deps, store)
    for number in range(12):
        finish_turn(context, f"question {number} " + "word " * 300, "answer " + "word " * 300)
    before = len(context["messages"])

    output = command(screen, "/compact", context)

    assert "Summarized" in output and "→" in output
    assert len(context["messages"]) < before and is_summary(context["messages"][1])
    assert context["tokens"] > 0  # the summarizing was counted
    loaded = store.load(context["current"].id, deps.memory.__class__())
    assert loaded is not None and len(loaded.messages) == len(context["messages"])


def test_compact_with_nothing_old_says_so(deps: Deps, store: SessionStore, screen: Screen) -> None:
    context = start(deps, store)
    assert "Nothing old enough" in command(screen, "/compact", context)


def test_compact_survives_a_model_that_cannot_be_reached(
    store: SessionStore, screen: Screen, tmp_path: Path
) -> None:
    def down(messages: list[Message]) -> BrainReply:
        raise ConnectionError("server is down")

    (tmp_path / "w").mkdir()
    deps = make_deps(tmp_path / "w", MockBrain(responder=down))
    context = start(deps, store)
    for number in range(12):
        finish_turn(context, f"question {number} " + "word " * 300, "answer " + "word " * 300)
    before = list(context["messages"])
    assert "Could not summarize: server is down" in command(screen, "/compact", context)
    assert context["messages"] == before


# ---- the REPL saving as it goes


def run_turn(text: str, deps: Deps, context: dict[str, Any], screen: Screen) -> None:
    _run_agent_turn(text, deps, CliRenderer(screen.console), context)


def test_a_finished_turn_is_titled_counted_and_saved(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    deps = make_deps(deps.ctx.workspace, MockBrain(responder=lambda messages: summary("Hi!")))
    context = start(deps, store)
    assert store.list_sessions() == []  # nothing yet: no finished turn

    run_turn("Hello there,\nsecond line", deps, context, screen)

    (info,) = store.list_sessions()
    assert (info.title, info.turns) == ("Hello there,", 1) and context["turns"] == 1
    run_turn("and again", deps, context, screen)
    assert store.list_sessions()[0].turns == 2
    assert store.list_sessions()[0].title == "Hello there,"  # the title stays


def test_an_interrupted_turn_is_dropped_and_not_saved(
    deps: Deps, store: SessionStore, screen: Screen
) -> None:
    def interrupted(messages: list[Message]) -> BrainReply:
        raise KeyboardInterrupt

    deps = make_deps(deps.ctx.workspace, MockBrain(responder=interrupted))
    context = start(deps, store)
    run_turn("please do it", deps, context, screen)
    assert [m.role for m in context["messages"]] == [Role.SYSTEM]  # the request is gone
    assert store.list_sessions() == [] and "Stopped." in screen.text()


def test_an_interrupted_turn_is_dropped_even_after_summarizing_shortened_the_history(
    store: SessionStore, screen: Screen, tmp_path: Path
) -> None:
    """Summarizing during a turn moves messages around, so undoing by position would go wrong."""
    (tmp_path / "w").mkdir()
    calls = {"answers": 0}

    def brain(messages: list[Message]) -> BrainReply:
        if "running summary" in messages[0].content:
            return summary()
        calls["answers"] += 1
        raise KeyboardInterrupt

    deps = make_deps(tmp_path / "w", MockBrain(context_window=8000, responder=brain))
    context = start(deps, store)
    for number in range(12):
        finish_turn(context, f"question {number} " + "word " * 300, "answer " + "word " * 300)

    run_turn("the new request", deps, context, screen)

    messages: list[Message] = context["messages"]
    assert any(is_summary(m) for m in messages)  # summarizing did happen mid-turn
    assert all(m.content != "the new request" for m in messages)  # and the request was dropped
    assert messages[-1].role is Role.ASSISTANT  # the history still ends on a finished turn
    assert context["current"].turns == 12 and "Stopped." in screen.text()


def test_an_error_during_a_turn_is_reported_and_the_turn_dropped(
    store: SessionStore, screen: Screen, tmp_path: Path
) -> None:
    def broken(messages: list[Message]) -> BrainReply:
        raise RuntimeError("model exploded")

    (tmp_path / "w").mkdir()
    deps = make_deps(tmp_path / "w", MockBrain(responder=broken))
    context = start(deps, store)
    run_turn("hello", deps, context, screen)
    assert "Inference error: model exploded" in screen.text()
    assert [m.role for m in context["messages"]] == [Role.SYSTEM]


def test_a_failing_disk_does_not_end_the_session(
    deps: Deps, store: SessionStore, screen: Screen, monkeypatch: pytest.MonkeyPatch
) -> None:
    deps = make_deps(deps.ctx.workspace, MockBrain(responder=lambda messages: summary("Hi!")))
    context = start(deps, store)

    def full_disk(session: Session) -> None:
        raise OSError("No space left on device")

    monkeypatch.setattr(store, "save", full_disk)
    run_turn("hello", deps, context, screen)
    assert "Could not save the session: No space left on device" in screen.text()
    assert context["turns"] == 1  # the conversation carried on


def test_the_event_printer_reports_a_summary(screen: Screen) -> None:
    from nexus.loop.events import Compacted

    EventPrinter(CliRenderer(screen.console))(
        Compacted(replaced=14, tokens_before=9000, tokens_after=2500)
    )
    assert "Summarized 14 older messages (9,000 → 2,500 tokens)" in screen.text()
