"""User settings: their options, saving them between sessions, and the menus to change them."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rich.console import Console

from nexus.brain.base import Depth
from nexus.cli.picker import Choice, pick
from nexus.cli.theme import CYAN, MUTED, SKY
from nexus.guardrails.modes import Mode

SETTINGS_PATH = Path.home() / ".nexus" / "settings.json"

MODE_CHOICES: tuple[Choice[Mode], ...] = (
    Choice(Mode.READ_ONLY, "read-only", "look but never change anything"),
    Choice(Mode.ASK, "ask", "ask before every change or command"),
    Choice(Mode.AUTO, "auto", "change files without asking"),
)

DEPTH_CHOICES: tuple[Choice[Depth], ...] = (
    Choice(Depth.FAST, "fast", "no thinking · answers in about a second"),
    Choice(Depth.BALANCED, "balanced", "the model's default thinking"),
    Choice(Depth.DEEP, "deep", "thinks longest · slowest, most careful"),
)

THINKING_CHOICES: tuple[Choice[bool], ...] = (
    Choice(False, "hidden", "show a one-line summary; view with /thoughts"),
    Choice(True, "shown", "print the model's reasoning after it thinks"),
)


@dataclass(frozen=True)
class Settings:
    """User choices that persist from one session to the next."""

    mode: Mode = Mode.ASK
    depth: Depth = Depth.BALANCED
    show_thinking: bool = False


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    """Read saved settings, falling back to defaults for anything missing or invalid."""
    try:
        saved: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()

    defaults = Settings()
    try:
        return Settings(
            mode=Mode(saved.get("mode", defaults.mode)),
            depth=Depth(saved.get("depth", defaults.depth)),
            show_thinking=bool(saved.get("show_thinking", defaults.show_thinking)),
        )
    except ValueError:
        return defaults  # A hand-edited file with a bad value should not stop startup.


def save_settings(settings: Settings, path: Path = SETTINGS_PATH) -> None:
    """Write settings to disk; failures are ignored because they only cost convenience."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def next_choice(choices: tuple[Choice[Any], ...], current: object) -> Any:
    """Return the value after `current` in `choices`, wrapping around; used by hotkeys."""
    values = [choice.value for choice in choices]
    index = values.index(current) if current in values else -1
    return values[(index + 1) % len(values)]


# The choices offered for each setting, keyed by the name used in the session state.
SETTING_CHOICES: dict[str, tuple[Choice[Any], ...]] = {
    "mode": MODE_CHOICES,
    "depth": DEPTH_CHOICES,
    "show_thinking": THINKING_CHOICES,
}

SETTING_TITLES: dict[str, str] = {
    "mode": "Permission mode",
    "depth": "Thinking depth",
    "show_thinking": "Model reasoning",
}


def label_for(key: str, value: object) -> str:
    """Return the display label of `value` for the setting `key`."""
    return next((c.label for c in SETTING_CHOICES[key] if c.value == value), str(value))


def settings_from_session(session: dict[str, Any]) -> Settings:
    """Collect the persistent settings out of the REPL's session state."""
    defaults = Settings()
    return Settings(
        mode=session.get("mode", defaults.mode),
        depth=session.get("depth", defaults.depth),
        show_thinking=session.get("show_thinking", defaults.show_thinking),
    )


def apply_setting(session: dict[str, Any], key: str, value: object) -> None:
    """Change one setting for this session and remember it for the next one."""
    session[key] = value
    renderer = session.get("renderer")
    if key == "show_thinking" and renderer is not None:
        renderer.show_raw_thoughts = bool(value)
    # Only the real REPL sets a path, so tests and one-off contexts never touch disk.
    path = session.get("settings_path")
    if path is not None:
        save_settings(settings_from_session(session), path)


# The commands behind /depth, /mode, /settings, and /thoughts.


def choose_setting(key: str, arg: str, context: dict[str, Any], console: Console) -> None:
    """Set a setting from the typed argument, or let the user pick it with the arrow keys."""
    choices = SETTING_CHOICES[key]
    if arg:
        value = next((c.value for c in choices if c.label == arg), None)
        if value is None:
            names = ", ".join(c.label for c in choices)
            console.print(f"[bold red]Unknown {key}:[/bold red] {arg} [{MUTED}]({names})[/{MUTED}]")
            return
    elif console.is_terminal:
        value = pick(SETTING_TITLES[key], choices, current=context.get(key))
        if value is None:
            return
    else:
        console.print(f"{SETTING_TITLES[key]}: [bold {CYAN}]{context.get(key)}[/bold {CYAN}]")
        return

    apply_setting(context, key, value)
    console.print(
        f"  [bold {CYAN}]✔[/bold {CYAN}] {SETTING_TITLES[key]} → "
        f"[bold {SKY}]{label_for(key, value)}[/bold {SKY}]"
    )


def open_settings_menu(context: dict[str, Any], console: Console) -> None:
    """A menu of all settings; picking one opens its options, Esc closes the menu."""
    if not console.is_terminal:
        for key, title in SETTING_TITLES.items():
            console.print(f"{title}: [bold {CYAN}]{label_for(key, context.get(key))}[/bold {CYAN}]")
        return

    last_key: str | None = None
    while True:
        rows = [
            Choice(key, f"{title:<17}", label_for(key, context.get(key)))
            for key, title in SETTING_TITLES.items()
        ]
        last_key = pick("Settings", rows, current=last_key)
        if last_key is None:
            return
        choose_setting(last_key, "", context, console)


def handle_thoughts(arg: str, context: dict[str, Any], console: Console) -> None:
    """Show the last reasoning trace, or toggle printing the reasoning after each turn."""
    if arg == "toggle":
        apply_setting(context, "show_thinking", not context.get("show_thinking", False))
        state = label_for("show_thinking", context["show_thinking"])
        console.print(
            f"  [bold {CYAN}]✔[/bold {CYAN}] Model reasoning → [bold {SKY}]{state}[/bold {SKY}]"
        )
        return

    renderer = context.get("renderer")
    if renderer is None:
        console.print(f"[{MUTED}]No reasoning trace available.[/{MUTED}]")
        return
    renderer.print_last_thoughts()
