"""An inline arrow-key menu for choosing one option, used for settings and questions."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import FormattedTextControl, Layout, Window
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style

from nexus.cli.theme import CYAN, GLOW, MUTED, SKY

Value = TypeVar("Value")


@dataclass(frozen=True)
class Choice(Generic[Value]):
    """One row in a picker: the value it returns, its label, an optional hint, and a hotkey.

    Pressing the hotkey picks the row at once. Keep hotkeys apart from j, k, and q, which
    the picker uses itself.
    """

    value: Value
    label: str
    hint: str = ""
    key: str = ""


_STYLE = Style.from_dict(
    {
        "title": f"bold {SKY}",
        "pointer": f"bold {CYAN}",
        "selected": f"bold {GLOW}",
        "label": "#d0e4ee",
        "hint": f"italic {MUTED}",
        "current": f"{CYAN}",
        "keys": f"{MUTED}",
    }
)


class _PickerState(Generic[Value]):
    """Which row is highlighted; kept apart from the UI so the logic stays testable."""

    def __init__(self, choices: Sequence[Choice[Value]], current: Value | None) -> None:
        self.choices = choices
        self.current = current
        values = [choice.value for choice in choices]
        self.index = values.index(current) if current in values else 0

    def move(self, step: int) -> None:
        self.index = (self.index + step) % len(self.choices)

    def render(self, title: str) -> StyleAndTextTuples:
        rows: StyleAndTextTuples = [("class:title", f" {title}\n")]
        for position, choice in enumerate(self.choices):
            is_selected = position == self.index
            rows.append(("class:pointer", " ❯ " if is_selected else "   "))
            rows.append(("class:selected" if is_selected else "class:label", choice.label))
            if choice.key:
                rows.append(("class:keys", f" ({choice.key})"))
            if choice.value == self.current:
                rows.append(("class:current", " ✔"))
            if choice.hint:
                rows.append(("class:hint", f"  {choice.hint}"))
            rows.append(("", "\n"))
        rows.append(("class:keys", " ↑/↓ move · enter select · esc cancel"))
        return rows


def pick(
    title: str,
    choices: Sequence[Choice[Value]],
    current: Value | None = None,
    input: Input | None = None,
    output: Output | None = None,
) -> Value | None:
    """Show the menu under the cursor and return the chosen value, or None if cancelled."""
    state = _PickerState(choices, current)
    bindings = KeyBindings()

    @bindings.add("up")
    @bindings.add("k")
    @bindings.add("s-tab")
    def _up(event: KeyPressEvent) -> None:
        state.move(-1)

    @bindings.add("down")
    @bindings.add("j")
    @bindings.add("tab")
    def _down(event: KeyPressEvent) -> None:
        state.move(1)

    @bindings.add("enter")
    def _select(event: KeyPressEvent) -> None:
        event.app.exit(result=state.choices[state.index].value)

    @bindings.add("escape", eager=True)
    @bindings.add("c-c")
    @bindings.add("q")
    def _cancel(event: KeyPressEvent) -> None:
        event.app.exit(result=None)

    for number in range(1, min(len(choices), 9) + 1):
        bindings.add(str(number))(_make_jump(state, number - 1))
    for choice in choices:
        if choice.key:
            bindings.add(choice.key)(_make_pick(choice.value))

    control = FormattedTextControl(lambda: state.render(title), show_cursor=False)
    app: Application[Value | None] = Application(
        layout=Layout(Window(control, height=len(choices) + 2)),
        key_bindings=bindings,
        style=_STYLE,
        full_screen=False,
        erase_when_done=True,
        input=input,
        output=output,
    )
    return app.run()


def _make_pick(value: Value) -> Callable[[KeyPressEvent], None]:
    """Build the handler that returns `value` when a choice's hotkey is pressed."""

    def pick_value(event: KeyPressEvent) -> None:
        event.app.exit(result=value)

    return pick_value


def _make_jump(state: _PickerState[Value], index: int) -> Callable[[KeyPressEvent], None]:
    """Build the handler that selects row `index` immediately when its number is pressed."""

    def jump(event: KeyPressEvent) -> None:
        event.app.exit(result=state.choices[index].value)

    return jump
