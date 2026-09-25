"""Draws what a tool call is about to do: colored code for a new file, a diff for a change."""

import difflib
from dataclasses import dataclass
from enum import Enum, auto

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from nexus.cli.theme import BLUE, CYAN, ERROR, MUTED, OK, WARN
from nexus.tools.base import Preview

VISIBLE_LINES = 40  # Enough to judge most changes without pushing the question off screen.
_CONTEXT_LINES = 3  # Unchanged lines shown around each change.
_TAB_WIDTH = 4
_EXACT_DIFF_LINE_LIMIT = 3000  # Above this, the diff trades some tidiness for speed.


def lines_phrase(count: int) -> str:
    """ "1 line" or "12 lines"."""
    return f"{count} line" if count == 1 else f"{count} lines"


@dataclass(frozen=True)
class PreviewCard:
    """A drawn preview, and how many of its lines were left out to keep it short."""

    renderable: RenderableType
    hidden_lines: int


def build_card(preview: Preview, visible_lines: int | None = VISIBLE_LINES) -> PreviewCard:
    """Draw `preview` in a panel.

    With `visible_lines` set, a long preview is cut and the number of hidden lines is
    reported so the caller can offer to show them. `None` draws everything.
    """
    if preview.after is None:
        text, hidden = _plain_body(preview.body, visible_lines)
        return PreviewCard(_panel(preview.title, "⚠", WARN, text, None, hidden), hidden)
    body: RenderableType
    if preview.before is None:
        body, hidden, subtitle = _new_code_body(preview, visible_lines)
    else:
        body, hidden, subtitle = _diff_body(preview.before, preview.after, visible_lines)
    return PreviewCard(_panel(preview.title, "✎", BLUE, body, subtitle, hidden), hidden)


def _panel(
    title: str,
    icon: str,
    color: str,
    body: RenderableType,
    subtitle: Text | None,
    hidden_lines: int,
) -> Panel:
    parts: list[RenderableType] = [body]
    if hidden_lines:
        noun = "line" if hidden_lines == 1 else "lines"
        parts.append(Text(f"… {hidden_lines} more {noun}", style=f"italic {MUTED}"))
    return Panel(
        Group(*parts),
        title=Text.assemble((f"{icon} ", f"bold {color}"), (title, "bold")),
        title_align="left",
        subtitle=subtitle,
        subtitle_align="right",
        border_style=color,
        padding=(0, 1),
    )


def _plain_body(text: str, visible_lines: int | None) -> tuple[Text, int]:
    """A command or a search: shown as it is, with the command line picked out."""
    lines = text.splitlines()
    shown = lines if visible_lines is None else lines[:visible_lines]
    body = Text()
    for line in shown:
        style = f"bold {CYAN}" if line.startswith("$ ") else MUTED if line.startswith("(") else ""
        body.append(line + "\n", style=style)
    body.rstrip()
    return body, len(lines) - len(shown)


def _new_code_body(preview: Preview, visible_lines: int | None) -> tuple[RenderableType, int, Text]:
    """A file that does not exist yet: its code with syntax colors and line numbers."""
    code = preview.after or ""
    lines = code.splitlines()
    subtitle = Text(f"{lines_phrase(len(lines))} · new file", style=MUTED)
    if not lines:
        return Text("(an empty file)", style=MUTED), 0, subtitle

    shown = lines if visible_lines is None else lines[:visible_lines]
    lexer = Syntax.guess_lexer(preview.path, code)
    # Only the lines on screen are highlighted, so a huge file cannot slow the prompt down.
    syntax = Syntax(
        "\n".join(shown),
        lexer,
        theme="monokai",
        line_numbers=True,
        word_wrap=True,
        background_color="default",
    )
    body: list[RenderableType] = [syntax]
    if preview.body:
        body.insert(0, Text(preview.body, style=f"italic {MUTED}"))
    return Group(*body), len(lines) - len(shown), subtitle


class _Kind(Enum):
    CONTEXT = auto()
    ADDED = auto()
    REMOVED = auto()
    GAP = auto()  # Where unchanged lines between two changes were left out.


@dataclass(frozen=True)
class _Row:
    kind: _Kind
    number: int = 0
    text: str = ""


def _diff_body(
    before: str, after: str, visible_lines: int | None
) -> tuple[RenderableType, int, Text]:
    """A changed file: only the changed lines and a little around them, with line numbers."""
    rows = _diff_rows(before, after)
    if not rows:
        return Text("The file already has this content.", style=MUTED), 0, Text("no changes")

    added = sum(row.kind is _Kind.ADDED for row in rows)
    removed = sum(row.kind is _Kind.REMOVED for row in rows)
    subtitle = Text.assemble((f"+{added}", OK), " ", (f"−{removed}", ERROR))
    shown = rows if visible_lines is None else rows[:visible_lines]
    return (
        _diff_text(shown, digits=len(str(max(row.number for row in rows)))),
        (len(rows) - len(shown)),
        subtitle,
    )


def _diff_rows(before: str, after: str) -> list[_Row]:
    old, new = before.splitlines(), after.splitlines()
    exact = len(old) + len(new) <= _EXACT_DIFF_LINE_LIMIT
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=not exact)
    rows: list[_Row] = []
    for group in matcher.get_grouped_opcodes(_CONTEXT_LINES):
        if rows:
            rows.append(_Row(_Kind.GAP))
        for tag, old_start, old_end, new_start, new_end in group:
            if tag == "equal":
                rows += [_Row(_Kind.CONTEXT, n + 1, new[n]) for n in range(new_start, new_end)]
                continue
            rows += [_Row(_Kind.REMOVED, n + 1, old[n]) for n in range(old_start, old_end)]
            rows += [_Row(_Kind.ADDED, n + 1, new[n]) for n in range(new_start, new_end)]
    return rows


def _diff_text(rows: list[_Row], digits: int) -> Text:
    """Additions in green and removals in red, each with its line number in the gutter."""
    text = Text()
    for row in rows:
        if row.kind is _Kind.GAP:
            text.append(" " * digits + "  ⋯\n", style=MUTED)
        elif row.kind is _Kind.ADDED:
            text.append(f"{row.number:>{digits}} ", style=f"dim {OK}")
            text.append("+ ", style=f"bold {OK}")
            text.append(row.text + "\n", style=OK)
        elif row.kind is _Kind.REMOVED:
            text.append(f"{row.number:>{digits}} ", style=f"dim {ERROR}")
            text.append("- ", style=f"bold {ERROR}")
            text.append(row.text + "\n", style=ERROR)
        else:
            text.append(f"{row.number:>{digits}}   ", style=f"dim {MUTED}")
            text.append(row.text + "\n", style=MUTED)
    text.rstrip()
    text.expand_tabs(_TAB_WIDTH)
    return text
