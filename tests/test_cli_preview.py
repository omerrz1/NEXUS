"""Tests for drawing what a tool call is about to do: new code, a diff, or a command."""

import io
import time

from rich.console import Console

from nexus.cli.preview import VISIBLE_LINES, build_card
from nexus.tools.base import Preview


def draw(preview: Preview, visible_lines: int | None = VISIBLE_LINES) -> tuple[str, int]:
    """The card as plain text, and how many lines it hid."""
    console = Console(file=io.StringIO(), width=100, force_terminal=False, color_system=None)
    card = build_card(preview, visible_lines)
    console.print(card.renderable)
    assert isinstance(console.file, io.StringIO)
    return console.file.getvalue(), card.hidden_lines


def numbered(count: int, word: str = "line") -> str:
    return "\n".join(f"{word} {n}" for n in range(1, count + 1)) + "\n"


# ---- a new file


def test_a_new_file_shows_numbered_code_under_a_short_title() -> None:
    preview = Preview(
        "Create src/app.py", path="/w/src/app.py", after="import os\nprint(os.name)\n"
    )
    text, hidden = draw(preview)
    assert "✎ Create src/app.py" in text and "2 lines · new file" in text
    assert "1 import os" in text and "2 print(os.name)" in text and hidden == 0


def test_a_long_new_file_is_cut_and_says_how_much_is_hidden() -> None:
    preview = Preview("Create big.py", path="/w/big.py", after=numbered(100))
    text, hidden = draw(preview)
    assert hidden == 100 - VISIBLE_LINES
    assert f"line {VISIBLE_LINES}" in text and f"line {VISIBLE_LINES + 1}\n" not in text
    assert f"… {hidden} more lines" in text and "100 lines · new file" in text


def test_asking_for_everything_shows_every_line() -> None:
    preview = Preview("Create big.py", path="/w/big.py", after=numbered(100))
    text, hidden = draw(preview, visible_lines=None)
    assert hidden == 0 and "line 100" in text and "more lines" not in text


def test_counts_read_naturally_in_the_singular() -> None:
    text, _ = draw(Preview("Create one.txt", path="/w/one.txt", after="only\n"))
    assert "1 line · new file" in text and "1 lines" not in text
    text, hidden = draw(Preview("Create f.txt", path="/w/f.txt", after=numbered(VISIBLE_LINES + 1)))
    assert hidden == 1 and "… 1 more line" in text and "1 more lines" not in text


def test_an_empty_new_file_is_said_to_be_empty() -> None:
    text, _ = draw(Preview("Create empty.txt", path="/w/empty.txt", after=""))
    assert "(an empty file)" in text and "0 lines · new file" in text


def test_the_note_about_an_unreadable_current_file_is_shown() -> None:
    preview = Preview("Replace a.txt", body="The current contents could not be read.", after="x\n")
    text, _ = draw(preview)
    assert "could not be read" in text and "x" in text


# ---- a changed file


def test_a_change_shows_only_the_changed_lines_with_a_little_around_them() -> None:
    before = numbered(30)
    after = before.replace("line 15\n", "LINE 15 CHANGED\n")
    text, hidden = draw(Preview("Replace f.txt", path="/w/f.txt", before=before, after=after))

    assert hidden == 0 and "+1 −1" in text
    assert "15 - line 15" in text and "15 + LINE 15 CHANGED" in text
    assert "12   line 12" in text and "18   line 18" in text  # three lines of context each side
    assert "line 11\n" not in text and "line 19" not in text
    assert "---" not in text and "+++" not in text and "@@" not in text  # no diff-file noise


def test_distant_changes_are_separated_by_a_gap_marker() -> None:
    before = numbered(60)
    after = before.replace("line 5\n", "FIVE\n").replace("line 50\n", "FIFTY\n")
    text, _ = draw(Preview("Replace f.txt", path="/w/f.txt", before=before, after=after))
    assert "⋯" in text and "5 + FIVE" in text and "50 + FIFTY" in text
    assert "line 25" not in text


def test_the_summary_counts_added_and_removed_lines() -> None:
    before = "a\nb\nc\n"
    after = "a\nB\nc\nd\ne\n"
    text, _ = draw(Preview("Replace f.txt", path="/w/f.txt", before=before, after=after))
    assert "+3 −1" in text


def test_a_long_diff_is_cut_like_new_code() -> None:
    before = numbered(200)
    after = numbered(200, word="new")
    _, hidden = draw(Preview("Replace f.txt", path="/w/f.txt", before=before, after=after))
    assert hidden > 0
    text, none_hidden = draw(
        Preview("Replace f.txt", path="/w/f.txt", before=before, after=after), None
    )
    assert none_hidden == 0 and "200 + new 200" in text


def test_replacing_a_file_with_the_same_content_says_so() -> None:
    text, hidden = draw(Preview("Replace f.txt", path="/w/f.txt", before="same\n", after="same\n"))
    assert "already has this content" in text and "no changes" in text and hidden == 0


def test_tabs_in_code_are_shown_as_spaces() -> None:
    preview = Preview("Replace f.go", path="/w/f.go", before="x\n", after="x\n\treturn 1\n")
    text, _ = draw(preview)
    assert "\t" not in text and "    return 1" in text


def test_square_brackets_in_code_and_paths_are_shown_literally_not_as_markup() -> None:
    tricky = "print('[bold red]not markup[/bold red]')\n"
    new_file, _ = draw(Preview("Create [x]/a.py", path="/w/a.py", after=tricky))
    assert "[bold red]not markup[/bold red]" in new_file and "Create [x]/a.py" in new_file
    change, _ = draw(Preview("Replace a.py", path="/w/a.py", before="x\n", after=tricky))
    assert "[bold red]not markup[/bold red]" in change


def test_a_big_file_does_not_make_the_prompt_wait() -> None:
    before = numbered(5000)
    after = before.replace("line 2500\n", "changed\n")
    started = time.perf_counter()
    text, _ = draw(Preview("Replace big.txt", path="/w/big.txt", before=before, after=after))
    assert time.perf_counter() - started < 3.0
    assert "2500 + changed" in text


# ---- a command or a search


def test_a_command_is_shown_as_typed_without_line_numbers() -> None:
    preview = Preview("Run a command", body="$ git status\n(in /work/app)")
    text, hidden = draw(preview)
    assert "⚠ Run a command" in text and "$ git status" in text and "(in /work/app)" in text
    assert hidden == 0 and "1 $" not in text


def test_a_very_long_command_is_cut_and_says_so() -> None:
    body = "$ " + "\n".join(f"echo {n}" for n in range(80))
    text, hidden = draw(Preview("Run a command", body=body))
    assert hidden == 80 - VISIBLE_LINES and f"… {hidden} more lines" in text
