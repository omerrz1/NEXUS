"""Tests for the interactive pieces of the CLI: completion, pickers, settings, streaming."""

from pathlib import Path

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from nexus.brain.base import Depth
from nexus.cli.picker import Choice, pick
from nexus.cli.prompt import NexusCompleter
from nexus.cli.settings import Settings, apply_setting, load_settings, save_settings
from nexus.cli.slash import find_command
from nexus.cli.stream import split_finished_blocks
from nexus.guardrails.modes import Mode


def complete(completer: NexusCompleter, line: str) -> list[str]:
    completions = completer.get_completions(Document(line), CompleteEvent())
    return [completion.text for completion in completions]


def test_typing_slash_lists_every_command_with_a_description() -> None:
    completer = NexusCompleter(Path.cwd(), tool_names=[])
    completions = list(completer.get_completions(Document("/"), CompleteEvent()))
    names = [completion.text for completion in completions]
    assert "/help" in names and "/depth" in names and "/settings" in names
    assert all(completion.display_meta_text for completion in completions)


def test_command_names_filter_as_you_type() -> None:
    completer = NexusCompleter(Path.cwd(), tool_names=[])
    assert complete(completer, "/dep") == ["/depth"]
    assert complete(completer, "/de") == ["/depth", "/delete"]
    assert complete(completer, "/qu") == ["/quit"]


def test_command_arguments_are_offered() -> None:
    completer = NexusCompleter(Path.cwd(), tool_names=[])
    assert complete(completer, "/depth ") == ["fast", "balanced", "deep"]
    assert complete(completer, "/mode a") == ["ask", "auto"]
    assert complete(completer, "/memory ") == ["add", "forget"]


def test_only_registered_tools_are_offered() -> None:
    assert complete(NexusCompleter(Path.cwd(), tool_names=[]), "/tool ") == []
    completer = NexusCompleter(Path.cwd(), tool_names=["read_file", "run_command"])
    assert complete(completer, "/tool re") == ["read_file"]


def test_at_mentions_complete_file_paths(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("")
    (tmp_path / ".hidden").write_text("")
    completer = NexusCompleter(tmp_path, tool_names=[])
    assert complete(completer, "explain @s") == ["@src/"]
    assert complete(completer, "explain @src/") == ["@src/app.py"]
    assert complete(completer, "explain @.h") == ["@.hidden"]
    assert complete(completer, "plain words") == []


def test_find_command_accepts_unambiguous_prefixes() -> None:
    assert find_command("/dep") is not None
    assert find_command("/t") is None  # /tools, /tool, /thoughts, /tokens
    assert find_command("/re") is None  # /resume, /rename
    assert find_command("/res") is not None
    assert find_command("/quit") is not None


def test_picker_moves_with_arrows_and_selects_with_enter() -> None:
    choices = [Choice(Depth.FAST, "fast"), Choice(Depth.BALANCED, "balanced")]
    with create_pipe_input() as keys:
        keys.send_text("\x1b[B\r")  # down, enter
        result = pick("Depth", choices, current=Depth.FAST, input=keys, output=DummyOutput())
    assert result == Depth.BALANCED


def test_picker_number_keys_and_cancel() -> None:
    choices = [Choice("a", "a"), Choice("b", "b"), Choice("c", "c")]
    with create_pipe_input() as keys:
        keys.send_text("3")
        assert pick("Pick", choices, input=keys, output=DummyOutput()) == "c"
    with create_pipe_input() as keys:
        keys.send_text("q")
        assert pick("Pick", choices, input=keys, output=DummyOutput()) is None


def test_a_choice_can_be_picked_with_its_own_key() -> None:
    choices = [
        Choice("yes", "Yes", key="y"),
        Choice("always", "Always", key="a"),
        Choice("no", "No", key="n"),
    ]
    for pressed, expected in (("y", "yes"), ("a", "always"), ("n", "no")):
        with create_pipe_input() as keys:
            keys.send_text(pressed)
            assert pick("Allow?", choices, input=keys, output=DummyOutput()) == expected


def test_hotkeys_are_shown_next_to_their_choices() -> None:
    from nexus.cli.picker import _PickerState

    rows = _PickerState([Choice("y", "Yes", key="y"), Choice("x", "Other")], None).render("Allow?")
    text = "".join(fragment[1] for fragment in rows)
    assert "Yes (y)" in text and "Other (" not in text


def test_settings_round_trip_and_bad_files(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert load_settings(path) == Settings()
    save_settings(Settings(mode=Mode.AUTO, depth=Depth.FAST, show_thinking=True), path)
    assert load_settings(path) == Settings(Mode.AUTO, Depth.FAST, True)
    path.write_text('{"depth": "turbo"}')
    assert load_settings(path) == Settings()


def test_apply_setting_saves_only_when_a_path_is_given(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    session: dict[str, object] = {"mode": Mode.ASK, "depth": Depth.BALANCED}
    apply_setting(session, "depth", Depth.FAST)
    assert not path.exists()
    session["settings_path"] = path
    apply_setting(session, "mode", Mode.AUTO)
    assert load_settings(path) == Settings(mode=Mode.AUTO, depth=Depth.FAST)


def test_split_finished_blocks_keeps_open_code_fences_together() -> None:
    assert split_finished_blocks("Intro.\n\nStill typ") == ("Intro.\n\n", "Still typ")
    text = "```py\nx = 1\n\ny = 2\n"
    assert split_finished_blocks(text) == ("", text)
    assert split_finished_blocks("```py\nx = 1\n```\nmore") == ("```py\nx = 1\n```\n", "more")
