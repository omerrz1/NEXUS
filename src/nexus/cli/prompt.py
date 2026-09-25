"""The input line: a completion menu for / commands and @ files, history, and a status bar."""

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.styles import Style

from nexus.cli.settings import DEPTH_CHOICES, MODE_CHOICES
from nexus.cli.slash import SLASH_COMMANDS, find_command
from nexus.cli.status import context_meter
from nexus.cli.theme import BLUE, CYAN, GLOW, MUTED, OCEAN, SKY

HISTORY_PATH = Path.home() / ".nexus" / "history"

_ARGUMENT_HINTS: dict[str, dict[str, str]] = {
    "/mode": {str(choice.value): choice.hint for choice in MODE_CHOICES},
    "/depth": {str(choice.value): choice.hint for choice in DEPTH_CHOICES},
    "/thoughts": {"toggle": "turn showing the model's reasoning on or off"},
    "/memory": {"add": "save a note yourself", "forget": "delete a note by its number"},
}

_STYLE = Style.from_dict(
    {
        "prompt": f"bold {CYAN}",
        "completion-menu": f"bg:#0b2233 {SKY}",
        "completion-menu.completion": f"bg:#0b2233 {SKY}",
        "completion-menu.completion.current": f"bg:{OCEAN} bold {GLOW}",
        "completion-menu.meta.completion": f"bg:#0b2233 {MUTED}",
        "completion-menu.meta.completion.current": f"bg:{OCEAN} {GLOW}",
        "scrollbar.background": "bg:#0b2233",
        "scrollbar.button": f"bg:{BLUE}",
        "auto-suggestion": f"italic {MUTED}",
        "bottom-toolbar": f"noreverse bg:default {MUTED}",
    }
)


class NexusCompleter(Completer):
    """Suggests slash commands and their arguments, @file mentions, and paths."""

    def __init__(self, workspace: Path, tool_names: list[str]) -> None:
        self.workspace = workspace
        self.tool_names = tool_names

    def get_completions(self, document: Document, event: CompleteEvent) -> Iterable[Completion]:
        line = document.text_before_cursor
        word = document.get_word_before_cursor(WORD=True)
        if line.startswith("/"):
            yield from self._complete_slash(line, word)
        elif word.startswith("@"):
            for path in self._complete_paths(word[1:]):
                yield Completion("@" + path, start_position=-len(word), display=path)

    def _complete_slash(self, line: str, word: str) -> Iterable[Completion]:
        """Complete a command name, or the argument of the command already typed."""
        if " " not in line:
            for listed in SLASH_COMMANDS:
                if listed.name.startswith(line):
                    yield Completion(listed.name, -len(line), display_meta=listed.description)
                    continue
                # Aliases only appear when the user is typing one, to keep the menu short.
                for alias in listed.aliases:
                    if alias.startswith(line):
                        meta = f"same as {listed.name}"
                        yield Completion(alias, -len(line), display_meta=meta)
            return

        command = find_command(line.split(maxsplit=1)[0].lower())
        if command is None:
            return
        if command.name == "/save":
            candidates = dict.fromkeys(self._complete_paths(word), "")
        elif command.name == "/tool":
            candidates = dict.fromkeys(self.tool_names, "")
        else:
            candidates = _ARGUMENT_HINTS.get(command.name, {})
        for value, hint in candidates.items():
            if value.startswith(word):
                yield Completion(value, -len(word), display_meta=hint)

    def _complete_paths(self, prefix: str) -> list[str]:
        """Complete file and directory names, keeping the directory part the user typed."""
        typed_dir = prefix[: prefix.rfind("/") + 1]  # "" when there is no slash
        partial = prefix[len(typed_dir) :]
        try:
            entries = sorted((self.workspace / Path(typed_dir).expanduser()).iterdir())
        except OSError:
            return []

        matches: list[str] = []
        for entry in entries:
            # Hidden files are only offered once the user starts typing a dot.
            if entry.name.startswith(".") and not partial.startswith("."):
                continue
            if entry.name.startswith(partial):
                matches.append(typed_dir + entry.name + ("/" if entry.is_dir() else ""))
        return matches


def build_prompt_session(
    session: dict[str, Any],
    tool_names: list[str],
    on_hotkey: Callable[[str], None],
) -> PromptSession[str]:
    """Create the input line. `on_hotkey` receives "mode" or "depth" when a hotkey cycles it."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    return PromptSession(
        message=FormattedText([("class:prompt", "› ")]),
        completer=NexusCompleter(Path.cwd(), tool_names),
        complete_while_typing=True,
        auto_suggest=AutoSuggestFromHistory(),
        history=FileHistory(str(HISTORY_PATH)),
        bottom_toolbar=lambda: _status_bar(session),
        key_bindings=_hotkeys(on_hotkey),
        style=_STYLE,
        reserve_space_for_menu=8,
    )


def _hotkeys(on_hotkey: Callable[[str], None]) -> KeyBindings:
    """Shift-Tab cycles the permission mode and Ctrl-T cycles the thinking depth."""
    bindings = KeyBindings()

    @bindings.add("s-tab")
    def _cycle_mode(event: KeyPressEvent) -> None:
        on_hotkey("mode")
        event.app.invalidate()

    @bindings.add("c-t")
    def _cycle_depth(event: KeyPressEvent) -> None:
        on_hotkey("depth")
        event.app.invalidate()

    return bindings


def _status_bar(session: dict[str, Any]) -> FormattedText:
    """The line under the input showing the live settings and the main shortcuts."""
    divider = (MUTED, "  │  ")
    percent, meter_color = context_meter(
        int(session.get("context_used", 0)), int(session.get("context_window", 0))
    )
    return FormattedText(
        [
            (SKY, f" ◈ {session.get('model')}"),
            divider,
            (MUTED, "mode "),
            (f"bold {CYAN}", str(session.get("mode"))),
            divider,
            (MUTED, "depth "),
            (f"bold {CYAN}", str(session.get("depth"))),
            divider,
            (MUTED, "context "),
            (f"bold {meter_color}", f"{percent}%"),
            divider,
            (MUTED, f"{int(session.get('tokens', 0)):,} tok"),
            (f"{MUTED} italic", "      / commands · @ files · ⇧⇥ mode · ^T depth"),
        ]
    )
