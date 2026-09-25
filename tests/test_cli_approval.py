"""Tests for the approval prompt: the menu, declining with a note, and the typed fallback."""

import io
from collections.abc import Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from rich.console import Console

from nexus.cli.approve import CliApprover, _Reply
from nexus.cli.picker import Choice
from nexus.guardrails.approval import Answer, Approval
from nexus.messages import ToolCall
from nexus.tools.base import Preview

CALL = ToolCall("1", "write_file", {"path": "a.py", "content": "x"})
SMALL = Preview("Create a.py", path="/w/a.py", after="print('hi')\n")
LARGE = Preview("Create big.py", path="/w/big.py", after="\n".join(f"line {n}" for n in range(100)))


class FakeMenu:
    """Stands in for the arrow-key menu: gives scripted replies and remembers what it showed."""

    def __init__(self, *replies: _Reply | None) -> None:
        self.replies = list(replies)
        self.shown: list[list[Choice[_Reply]]] = []

    def __call__(self, title: str, choices: Sequence[Choice[_Reply]]) -> _Reply | None:
        self.shown.append(list(choices))
        return self.replies.pop(0)


@pytest.fixture
def on_a_terminal(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make the approver believe it has a real terminal. Returns a log of discarded input."""
    log: list[str] = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr("nexus.cli.approve._discard_typed_ahead_keys", lambda: log.append("flush"))
    return log


def make_approver(menu: FakeMenu, typed: str = "") -> tuple[CliApprover, io.StringIO]:
    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100, color_system=None)
    return CliApprover(console, choose=menu, read_line=lambda prompt: typed), output


# ---- the menu


def test_yes_allows_once(on_a_terminal: list[str]) -> None:
    approver, output = make_approver(FakeMenu(_Reply.YES))
    assert approver.approve(CALL, SMALL, "write_file") == Answer(Approval.ONCE)
    assert "✔ Allowed" in output.getvalue()


def test_the_change_is_shown_before_the_question(on_a_terminal: list[str]) -> None:
    approver, output = make_approver(FakeMenu(_Reply.YES))
    approver.approve(CALL, SMALL, "write_file")
    assert "✎ Create a.py" in output.getvalue() and "print('hi')" in output.getvalue()


def test_always_allows_and_is_remembered_for_that_scope_only(on_a_terminal: list[str]) -> None:
    menu = FakeMenu(_Reply.ALWAYS, _Reply.YES)
    approver, output = make_approver(menu)
    assert approver.approve(CALL, SMALL, "write_file in the working directory").approval is (
        Approval.SESSION
    )
    assert "won't ask again for write_file in the working directory" in output.getvalue()

    # The same scope is not asked again, and nothing more is drawn for it.
    drawn = output.getvalue()
    assert approver.approve(CALL, SMALL, "write_file in the working directory").approval is (
        Approval.SESSION
    )
    assert len(menu.shown) == 1 and output.getvalue() == drawn
    # A different scope is asked.
    assert approver.approve(CALL, SMALL, "write_file /etc/x").approval is Approval.ONCE
    assert len(menu.shown) == 2


@pytest.mark.parametrize("reply", [_Reply.NO, None])  # "No", or esc
def test_no_and_escape_both_decline(on_a_terminal: list[str], reply: _Reply | None) -> None:
    approver, output = make_approver(FakeMenu(reply))
    assert approver.approve(CALL, SMALL, "write_file") == Answer(Approval.DENY)
    assert "✖ Declined" in output.getvalue()


def test_declining_with_a_note_passes_the_note_to_the_model(on_a_terminal: list[str]) -> None:
    approver, output = make_approver(FakeMenu(_Reply.INSTEAD), typed="  use tabs instead  ")
    answer = approver.approve(CALL, SMALL, "write_file")
    assert answer == Answer(Approval.DENY, "use tabs instead")
    assert 'you told Nexus: "use tabs instead"' in output.getvalue()


def test_declining_with_an_empty_note_is_just_a_no(on_a_terminal: list[str]) -> None:
    approver, output = make_approver(FakeMenu(_Reply.INSTEAD), typed="")
    assert approver.approve(CALL, SMALL, "write_file") == Answer(Approval.DENY, "")
    assert "you told Nexus" not in output.getvalue()


def test_interrupting_the_note_prompt_is_a_plain_no(on_a_terminal: list[str]) -> None:
    def interrupted(prompt: str) -> str:
        raise KeyboardInterrupt

    output = io.StringIO()
    console = Console(file=output, force_terminal=True, width=100, color_system=None)
    approver = CliApprover(console, choose=FakeMenu(_Reply.INSTEAD), read_line=interrupted)
    assert approver.approve(CALL, SMALL, "write_file") == Answer(Approval.DENY, "")


def test_the_menu_offers_one_key_for_each_answer(on_a_terminal: list[str]) -> None:
    menu = FakeMenu(_Reply.YES)
    make_approver(menu)[0].approve(CALL, SMALL, "write_file in the working directory")
    rows = menu.shown[0]
    assert [row.key for row in rows] == ["y", "a", "n", "t"]
    assert rows[0].label == "Yes"
    assert "write_file in the working directory" in rows[1].label
    assert "tell Nexus what to do instead" in rows[3].label


def test_keys_typed_while_the_model_worked_cannot_answer_the_prompt(
    on_a_terminal: list[str],
) -> None:
    make_approver(FakeMenu(_Reply.YES))[0].approve(CALL, SMALL, "write_file")
    assert on_a_terminal == ["flush"]


# ---- long changes


def test_a_cut_change_puts_viewing_it_first_so_enter_cannot_approve_unseen_code(
    on_a_terminal: list[str],
) -> None:
    menu = FakeMenu(_Reply.YES)
    make_approver(menu)[0].approve(CALL, LARGE, "write_file")
    rows = menu.shown[0]
    assert rows[0].key == "v" and "60 lines not shown" in rows[0].label
    assert [row.key for row in rows[1:]] == ["y", "a", "n", "t"]


def test_a_change_that_fits_has_nothing_to_view(on_a_terminal: list[str]) -> None:
    menu = FakeMenu(_Reply.YES)
    make_approver(menu)[0].approve(CALL, SMALL, "write_file")
    assert all(row.key != "v" for row in menu.shown[0])


def test_viewing_shows_the_whole_change_in_a_pager_then_asks_again(
    on_a_terminal: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    menu = FakeMenu(_Reply.VIEW, _Reply.YES)
    approver, output = make_approver(menu)
    opened: list[str] = []

    @contextmanager
    def fake_pager(**options: Any):  # type: ignore[no-untyped-def]
        opened.append("opened")
        yield

    monkeypatch.setattr(approver.console, "pager", fake_pager)
    answer = approver.approve(CALL, LARGE, "write_file")

    assert answer.approval is Approval.ONCE and opened == ["opened"] and len(menu.shown) == 2
    assert "line 99" in output.getvalue()  # the last line, which the first card cut off
    assert output.getvalue().count("✔ Allowed") == 1  # only the real decision is announced


def test_without_a_pager_the_change_is_printed_instead(
    on_a_terminal: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    menu = FakeMenu(_Reply.VIEW, _Reply.NO)
    approver, output = make_approver(menu)

    @contextmanager
    def broken_pager(**options: Any):  # type: ignore[no-untyped-def]
        raise OSError("no pager")
        yield

    monkeypatch.setattr(approver.console, "pager", broken_pager)
    approver.approve(CALL, LARGE, "write_file")
    assert "line 99" in output.getvalue()


# ---- no terminal (a pipe, or one-shot mode)


def type_answers(monkeypatch: pytest.MonkeyPatch, *answers: str) -> CliApprover:
    replies = iter(answers)
    monkeypatch.setattr("rich.console.Console.input", lambda self, prompt="": next(replies))
    console = Console(file=io.StringIO(), force_terminal=False)
    return CliApprover(console)


def test_without_a_terminal_the_answer_is_typed(monkeypatch: pytest.MonkeyPatch) -> None:
    approver = type_answers(monkeypatch, "y", "yes", "n", "", "a")
    assert approver.approve(CALL, SMALL, "s1") == Answer(Approval.ONCE)
    assert approver.approve(CALL, SMALL, "s2") == Answer(Approval.ONCE)
    assert approver.approve(CALL, SMALL, "s3") == Answer(Approval.DENY)
    assert approver.approve(CALL, SMALL, "s4") == Answer(Approval.DENY)  # enter alone declines
    assert approver.approve(CALL, SMALL, "s5") == Answer(Approval.SESSION)


def test_typed_always_is_remembered_per_scope_not_per_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    approver = type_answers(monkeypatch, "a", "y")
    git = Preview("Run a command", body="$ git log")
    assert approver.approve(CALL, git, "run_command git ...").approval is Approval.SESSION
    assert approver.approve(CALL, git, "run_command git ...").approval is Approval.SESSION
    assert approver.approve(CALL, git, "run_command ls ...").approval is Approval.ONCE


def test_typing_something_unclear_asks_again(monkeypatch: pytest.MonkeyPatch) -> None:
    approver = type_answers(monkeypatch, "maybe", "y")
    assert approver.approve(CALL, SMALL, "s").approval is Approval.ONCE


def test_interrupting_the_typed_prompt_declines(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(self: Console, prompt: str = "") -> str:
        raise KeyboardInterrupt

    monkeypatch.setattr("rich.console.Console.input", interrupted)
    approver = CliApprover(Console(file=io.StringIO(), force_terminal=False))
    assert approver.approve(CALL, SMALL, "s") == Answer(Approval.DENY)


def test_a_call_with_no_preview_still_shows_what_it_will_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approver = type_answers(monkeypatch, "y")
    output = io.StringIO()
    approver.console = Console(file=output, force_terminal=False, width=80)
    approver.approve(ToolCall("1", "mystery", {"x": 1}), None, "mystery")
    assert "Run mystery" in output.getvalue() and '"x": 1' in output.getvalue()
