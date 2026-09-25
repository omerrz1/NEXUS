"""The terminal prompt that asks the user before a guarded tool call runs."""

import json
import sys
import termios
from collections.abc import Callable, Sequence
from enum import Enum, auto

from prompt_toolkit import prompt as prompt_for_line
from rich.console import Console
from rich.markup import escape
from rich.text import Text

from nexus.cli.picker import Choice, pick
from nexus.cli.preview import PreviewCard, build_card, lines_phrase
from nexus.cli.theme import CYAN, ERROR, MUTED, OK, SKY
from nexus.guardrails.approval import Answer, Approval
from nexus.messages import ToolCall
from nexus.tools.base import Preview


class _Reply(Enum):
    """The rows of the approval menu."""

    YES = auto()
    ALWAYS = auto()
    NO = auto()
    INSTEAD = auto()  # No, and here is what to do instead.
    VIEW = auto()  # Show the whole change first.


Chooser = Callable[[str, Sequence[Choice[_Reply]]], _Reply | None]
LineReader = Callable[[str], str]


class CliApprover:
    """Shows what a tool call will do and asks whether to allow it.

    On a terminal the answer is one keypress in a menu: arrows and enter, a number, or a
    letter. The user can read the whole change first, and can decline with a note that goes
    back to the model. Without a terminal (a pipe), it falls back to typing y, a, or n.
    """

    def __init__(
        self,
        console: Console | None = None,
        choose: Chooser | None = None,
        read_line: LineReader | None = None,
    ) -> None:
        self.console: Console = console or Console()
        self._choose: Chooser = choose or _choose_from_menu
        self._read_line: LineReader = read_line or _read_line
        self._session_grants: set[str] = set()

    def approve(
        self, call: ToolCall, preview: Preview | None = None, scope: str | None = None
    ) -> Answer:
        """Ask about one call. "Always" is remembered for `scope` until the session ends."""
        scope = call.name if scope is None else scope
        if scope and scope in self._session_grants:
            return Answer(Approval.SESSION)

        preview = preview or Preview(f"Run {call.name}", body=json.dumps(call.arguments, indent=2))
        card = build_card(preview)
        self.console.print(card.renderable)
        if self.console.is_terminal and sys.stdin.isatty():
            answer = self._ask_with_menu(preview, card, scope)
        else:
            answer = self._ask_by_typing(scope)

        if answer.approval is Approval.SESSION and scope:
            self._session_grants.add(scope)
        self._say_what_was_decided(answer, scope)
        return answer

    def _ask_with_menu(self, preview: Preview, card: PreviewCard, scope: str) -> Answer:
        # Keys typed while the model was working must not be able to answer for the user.
        _discard_typed_ahead_keys()
        while True:
            reply = self._choose("Allow this?", _menu_rows(scope, card.hidden_lines))
            if reply is _Reply.VIEW:
                self._show_everything(preview)
            elif reply is _Reply.YES:
                return Answer(Approval.ONCE)
            elif reply is _Reply.ALWAYS:
                return Answer(Approval.SESSION)
            elif reply is _Reply.INSTEAD:
                return Answer(Approval.DENY, self._ask_what_instead())
            else:
                return Answer(Approval.DENY)  # "No", or the menu was cancelled with esc.

    def _ask_by_typing(self, scope: str) -> Answer:
        always = (
            f"[bold {CYAN}]a[/bold {CYAN}][{MUTED}]lways: {escape(scope)}[/{MUTED}]  "
            if scope
            else ""
        )
        prompt = (
            f"  [bold {OK}]y[/bold {OK}][{MUTED}]es[/{MUTED}]  {always}"
            f"[bold {ERROR}]n[/bold {ERROR}][{MUTED}]o[/{MUTED}]  [bold {SKY}]›[/bold {SKY}] "
        )
        while True:
            try:
                choice = self.console.input(prompt).strip().lower()
            except (KeyboardInterrupt, EOFError):
                return Answer(Approval.DENY)
            if choice in ("y", "yes"):
                return Answer(Approval.ONCE)
            if choice in ("a", "always") and scope:
                return Answer(Approval.SESSION)
            if choice in ("n", "no", ""):
                return Answer(Approval.DENY)
            options = "y, a, or n" if scope else "y or n"
            self.console.print(f"  [{MUTED}]Please type {options}.[/{MUTED}]")

    def _ask_what_instead(self) -> str:
        self.console.print(f"  [{MUTED}]What should Nexus do instead? (enter to skip)[/{MUTED}]")
        try:
            return self._read_line("  › ").strip()
        except (KeyboardInterrupt, EOFError):
            return ""

    def _show_everything(self, preview: Preview) -> None:
        """Open the whole change in a pager, or print it if there is no pager."""
        everything = build_card(preview, visible_lines=None).renderable
        try:
            with self.console.pager(styles=True):
                self.console.print(everything)
        except OSError:
            self.console.print(everything)

    def _say_what_was_decided(self, answer: Answer, scope: str) -> None:
        line = Text("  ")
        if answer.approval is Approval.DENY:
            line.append("✖ Declined", style=f"bold {ERROR}")
            if answer.instead:
                line.append(f' — you told Nexus: "{answer.instead}"', style=MUTED)
        elif answer.approval is Approval.SESSION:
            line.append("✔ Allowed", style=f"bold {OK}")
            line.append(f" — won't ask again for {scope}", style=MUTED)
        else:
            line.append("✔ Allowed", style=f"bold {OK}")
        self.console.print(line)


def _menu_rows(scope: str, hidden_lines: int) -> list[Choice[_Reply]]:
    rows = [Choice(_Reply.YES, "Yes", key="y")]
    if scope:  # Some tools can never be allowed for the rest of the session.
        rows.append(Choice(_Reply.ALWAYS, f"Yes, and don't ask again for {scope}", key="a"))
    rows += [
        Choice(_Reply.NO, "No", key="n"),
        Choice(_Reply.INSTEAD, "No, and tell Nexus what to do instead", key="t"),
    ]
    if hidden_lines:
        # First, so that pressing enter reads the rest instead of approving unseen code.
        label = f"View the {lines_phrase(hidden_lines)} not shown"
        rows.insert(0, Choice(_Reply.VIEW, label, key="v"))
    return rows


def _choose_from_menu(title: str, choices: Sequence[Choice[_Reply]]) -> _Reply | None:
    return pick(title, choices)


def _read_line(message: str) -> str:
    return prompt_for_line(message)


def _discard_typed_ahead_keys() -> None:
    if sys.stdin.isatty():
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
