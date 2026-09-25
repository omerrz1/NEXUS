"""Tests for saving, listing, resuming, and deleting sessions."""

import json
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nexus.messages import Message, Role, ToolCall
from nexus.session.memory import SessionMemory, TodoItem, TodoStatus
from nexus.session.store import Session, SessionStore, make_title


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(tmp_path / "sessions")


def make_session(
    title: str = "Fix the bug", workspace: str = "/work/app", turns: int = 1
) -> Session:
    session = Session.start(Path(workspace), "system prompt", SessionMemory())
    session.title = title
    session.turns = turns
    call = ToolCall("c1", "read_file", {"path": "a.py"})
    session.messages += [
        Message.user("please fix it"),
        Message.assistant("", (call,)),
        Message.tool("c1", "print('hi')", "read_file"),
        Message.assistant("Done."),
    ]
    return session


def test_a_saved_session_comes_back_exactly(store: SessionStore) -> None:
    session = make_session()
    session.memory.add_note("prefers tabs")
    session.memory.set_todo([TodoItem("ship it", TodoStatus.IN_PROGRESS)])
    store.save(session)

    memory = SessionMemory()
    loaded = store.load(session.id, memory)
    assert loaded is not None
    assert loaded.messages == session.messages  # including the tool call and its result
    assert (loaded.id, loaded.title, loaded.turns) == (session.id, "Fix the bug", 1)
    assert memory.notes == ["prefers tabs"] and memory.todo == session.memory.todo


def test_a_session_with_no_finished_turn_is_not_saved(store: SessionStore) -> None:
    store.save(make_session(turns=0))
    assert store.list_sessions() == []


def test_saved_files_can_only_be_read_by_their_owner(store: SessionStore, tmp_path: Path) -> None:
    session = make_session()
    store.save(session)
    path = tmp_path / "sessions" / f"{session.id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert list(path.parent.glob("*.tmp")) == []  # the temporary file was moved into place


def test_saving_again_replaces_the_file_and_moves_the_session_up(store: SessionStore) -> None:
    older, newer = make_session("older"), make_session("newer")
    store.save(older)
    store.save(newer)
    assert [info.title for info in store.list_sessions()] == ["newer", "older"]
    older.turns = 2
    store.save(older)
    assert [info.title for info in store.list_sessions()] == ["older", "newer"]
    assert store.list_sessions()[0].turns == 2


def test_loading_a_missing_or_damaged_session_returns_none(
    store: SessionStore, tmp_path: Path
) -> None:
    session = make_session()
    store.save(session)
    assert store.load("20200101-000000-abcd", SessionMemory()) is None  # never saved
    path = tmp_path / "sessions" / f"{session.id}.json"
    path.write_text("{ not json")
    assert store.load(session.id, SessionMemory()) is None
    assert store.list_sessions() == []  # and a damaged file does not break the list


def test_a_damaged_session_leaves_the_memory_untouched(store: SessionStore, tmp_path: Path) -> None:
    session = make_session()
    store.save(session)
    path = tmp_path / "sessions" / f"{session.id}.json"
    data = json.loads(path.read_text())
    del data["messages"]
    path.write_text(json.dumps(data))
    memory = SessionMemory()
    memory.add_note("mine")
    assert store.load(session.id, memory) is None and memory.notes == ["mine"]


@pytest.mark.parametrize("bad_id", ["../../etc/passwd", "..", "a/b", "", "20200101-000000-XYZ1"])
def test_ids_that_are_not_ours_never_reach_the_filesystem(
    store: SessionStore, tmp_path: Path, bad_id: str
) -> None:
    outside = tmp_path / "secret.json"
    outside.write_text("{}")
    assert store.load(bad_id, SessionMemory()) is None
    assert store.delete(bad_id) is False
    assert outside.exists()


def test_find_by_list_number_or_id_prefix(store: SessionStore) -> None:
    first, second = make_session("first"), make_session("second")
    first.id, second.id = "20260101-100000-aaaa", "20260101-110000-bbbb"
    store.save(first)
    store.save(second)  # saved last, so it is number 1

    assert store.find("1") is not None and store.find("1").title == "second"  # type: ignore[union-attr]
    assert store.find("2") is not None and store.find("2").title == "first"  # type: ignore[union-attr]
    assert store.find("3") is None and store.find("0") is None
    assert store.find("20260101-11") is not None  # a prefix is enough when it is unique
    assert store.find("20260101") is None  # ambiguous
    assert store.find("nothing") is None


def test_latest_in_only_considers_sessions_from_that_folder(store: SessionStore) -> None:
    mine = make_session("mine", workspace="/work/app")
    other = make_session("other", workspace="/work/elsewhere")
    store.save(mine)
    store.save(other)  # newer, but from another folder
    latest = store.latest_in(Path("/work/app"))
    assert latest is not None and latest.title == "mine"
    assert store.latest_in(Path("/nowhere")) is None


def test_delete_removes_the_session(store: SessionStore) -> None:
    session = make_session()
    store.save(session)
    assert store.delete(session.id) is True
    assert store.list_sessions() == [] and store.delete(session.id) is False


def test_a_resumed_session_gets_a_fresh_system_prompt() -> None:
    session = make_session()
    session.refresh_system_prompt("today's prompt")
    assert session.messages[0] == Message.system("today's prompt")
    assert session.messages[1].role is Role.USER  # nothing else moved

    headless = Session.start(Path("/w"), "x", SessionMemory())
    headless.messages.clear()
    headless.refresh_system_prompt("prompt")
    assert headless.messages == [Message.system("prompt")]


def test_new_session_ids_are_a_date_a_time_and_four_hex_digits() -> None:
    session_id = Session.start(Path("/w"), "s", SessionMemory()).id
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", session_id)


def test_titles_come_from_the_first_line_and_are_cut_to_fit() -> None:
    assert make_title("  fix the   login bug\nand also the logout  ") == "fix the login bug"
    assert make_title("") == ""
    long_title = make_title("word " * 40)
    assert len(long_title) == 60 and long_title.endswith("…")


def test_timestamps_survive_a_round_trip(store: SessionStore) -> None:
    session = make_session()
    session.created_at = datetime.now() - timedelta(days=2)
    store.save(session)
    loaded = store.load(session.id, SessionMemory())
    assert loaded is not None and loaded.created_at == session.created_at
