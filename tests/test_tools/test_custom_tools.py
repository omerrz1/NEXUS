"""Tests for tools that Nexus makes for itself: the manifest, the script runner, and the library."""

import stat
import sys
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.tools.base import Risk, ToolContext, ToolResult
from nexus.tools.custom import script_tool
from nexus.tools.custom.library import ToolLibrary
from nexus.tools.custom.manifest import ToolManifest
from nexus.tools.custom.script_tool import ScriptTool
from nexus.tools.registry import default_registry, load_custom_tools

WORD_COUNT = """\
import json, sys
inputs = json.load(sys.stdin)
print(len(inputs["text"].split()))
"""


@pytest.fixture
def library(tmp_path: Path) -> ToolLibrary:
    return ToolLibrary(tmp_path / "tools")


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    (tmp_path / "work").mkdir()
    return ToolContext.for_window(tmp_path / "work", 16384)


def make_tool(
    library: ToolLibrary, code: str = WORD_COUNT, name: str = "word_count", **parameters: str
) -> ScriptTool:
    parameters = parameters or {"text": "the text to count"}
    return library.save(ToolManifest(name, "Count the words in some text.", parameters), code)


def call(tool: ScriptTool, ctx: ToolContext, **inputs: str) -> ToolResult:
    return tool.run(tool.args_model(**inputs), ctx)


# ---- the manifest


def test_a_manifest_survives_being_saved_and_read() -> None:
    manifest = ToolManifest("word_count", "Count words.", {"text": "what to count"})
    assert ToolManifest.from_json(manifest.to_json()) == manifest


@pytest.mark.parametrize(
    "name", ["Ab", "ab", "9lives", "has space", "../evil", "a/b", "x" * 41, "", "CAPS_here"]
)
def test_tool_names_that_are_not_simple_lowercase_words_are_refused(name: str) -> None:
    with pytest.raises(ValueError, match="name"):
        ToolManifest(name, "Does something.", {})


def test_descriptions_and_inputs_are_limited() -> None:
    with pytest.raises(ValueError, match="description"):
        ToolManifest("some_tool", "  ", {})
    with pytest.raises(ValueError, match="description"):
        ToolManifest("some_tool", "x" * 201, {})
    with pytest.raises(ValueError, match="at most 6 inputs"):
        ToolManifest("some_tool", "Does it.", {f"input{n}": "meaning" for n in range(7)})
    with pytest.raises(ValueError, match="input name"):
        ToolManifest("some_tool", "Does it.", {"Bad Name": "meaning"})
    with pytest.raises(ValueError, match="meaning of input"):
        ToolManifest("some_tool", "Does it.", {"text": ""})


@pytest.mark.parametrize("reserved", ["json", "copy", "dict", "schema", "model_config", "model_x"])
def test_input_names_that_would_clash_with_the_argument_model_are_refused(reserved: str) -> None:
    with pytest.raises(ValueError, match="reserved"):
        ToolManifest("some_tool", "Does it.", {reserved: "meaning"})


@pytest.mark.parametrize(
    "text",
    [
        "{ not json",
        "[]",
        '{"name": "a_tool"}',
        '{"name": "a_tool", "description": "d", "parameters": 5}',
    ],
)
def test_a_damaged_manifest_is_a_readable_error(text: str) -> None:
    with pytest.raises(ValueError):
        ToolManifest.from_json(text)


# ---- running a script


def test_the_script_gets_its_inputs_as_json_and_its_output_comes_back(
    library: ToolLibrary, ctx: ToolContext
) -> None:
    result = call(make_tool(library), ctx, text="one two three")
    assert result.ok and result.output == "3"


def test_awkward_input_text_arrives_intact(library: ToolLibrary, ctx: ToolContext) -> None:
    code = "import json, sys\nprint(json.load(sys.stdin)['text'])\n"
    tool = make_tool(library, code)
    awkward = 'quote " backslash \\ newline\nunicode ☃ [markup] $HOME `cmd`'
    assert call(tool, ctx, text=awkward).output == awkward


def test_several_inputs_are_passed_by_name(library: ToolLibrary, ctx: ToolContext) -> None:
    code = "import json, sys\nd = json.load(sys.stdin)\nprint(d['a'] + '-' + d['b'])\n"
    tool = make_tool(library, code, a="first", b="second")
    assert call(tool, ctx, a="x", b="y").output == "x-y"


def test_a_failing_script_returns_its_error_so_the_model_can_fix_it(
    library: ToolLibrary, ctx: ToolContext
) -> None:
    tool = make_tool(library, "raise KeyError('oops')\n")
    result = call(tool, ctx, text="x")
    assert not result.ok and "exit code 1" in result.output and "KeyError" in result.output


def test_a_script_that_prints_nothing_says_so(library: ToolLibrary, ctx: ToolContext) -> None:
    assert call(make_tool(library, "pass\n"), ctx, text="x").output == "(no output)"


def test_the_script_runs_in_the_working_directory(library: ToolLibrary, ctx: ToolContext) -> None:
    tool = make_tool(library, "import os\nprint(os.getcwd())\n")
    assert call(tool, ctx, text="x").output == str(ctx.workspace)


def test_the_script_cannot_see_secrets_in_the_environment(
    library: ToolLibrary, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_API_TOKEN", "hunter2")
    monkeypatch.setenv("VISIBLE_SETTING", "fine")
    code = "import os\nprint(os.environ.get('MY_API_TOKEN'), os.environ.get('VISIBLE_SETTING'))\n"
    assert call(make_tool(library, code), ctx, text="x").output == "None fine"


def test_a_script_that_runs_too_long_is_stopped_with_everything_it_started(
    library: ToolLibrary, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(script_tool, "TIMEOUT_SEC", 1)
    marker = ctx.workspace / "still-running"
    code = (
        "import subprocess, time\n"
        f"subprocess.Popen(['sh', '-c', 'sleep 2; touch {marker}'])\n"
        "time.sleep(30)\n"
    )
    result = call(make_tool(library, code), ctx, text="x")
    assert not result.ok and "longer than 1s" in result.output
    time.sleep(2.5)
    assert not marker.exists()


def test_long_output_is_capped_for_a_small_context(library: ToolLibrary, tmp_path: Path) -> None:
    small = ToolContext(workspace=tmp_path, max_output_lines=5)
    tool = make_tool(library, "for n in range(100):\n    print(n)\n")
    result = call(tool, small, text="x")
    assert result.ok and result.truncated and "output cut at 5 lines" in result.output


def test_a_script_that_cannot_be_started_is_a_message_not_a_crash(
    library: ToolLibrary, ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = make_tool(library)
    monkeypatch.setattr(sys, "executable", "/nonexistent/python")
    result = call(tool, ctx, text="x")
    assert not result.ok and "Could not start the tool" in result.output


# ---- how a made tool looks to the model and the guardrails


def test_the_model_sees_one_required_text_field_per_input(library: ToolLibrary) -> None:
    tool = make_tool(library, a="the first", b="the second")
    spec = tool.spec()
    assert spec.name == "word_count" and spec.description == "Count the words in some text."
    assert spec.parameters["required"] == ["a", "b"]
    assert spec.parameters["properties"]["a"] == {"description": "the first", "type": "string"}
    assert "$ref" not in str(spec.parameters)


def test_missing_inputs_are_rejected_before_the_script_runs(library: ToolLibrary) -> None:
    with pytest.raises(ValidationError):
        make_tool(library).args_model()


def test_a_made_tool_always_counts_as_a_command(library: ToolLibrary) -> None:
    tool = make_tool(library)
    assert tool.risk is Risk.EXEC and not tool.always_ask
    assert tool.grant_scope(tool.args_model(text="x"), ToolContext(workspace=Path("/"))) == (
        "the tool word_count"
    )


def test_running_a_made_tool_previews_its_inputs(library: ToolLibrary, ctx: ToolContext) -> None:
    tool = make_tool(library, a="first", b="second")
    preview = tool.preview(tool.args_model(a="hello", b="it's"), ctx)
    assert preview is not None and preview.title == "Run the tool word_count"
    assert "a = 'hello'" in preview.body and 'b = "it\'s"' in preview.body


# ---- the library on disk


def test_a_saved_tool_is_private_and_leaves_no_temporary_files(
    library: ToolLibrary, tmp_path: Path
) -> None:
    make_tool(library)
    folder = tmp_path / "tools" / "word_count"
    assert sorted(path.name for path in folder.iterdir()) == ["run.py", "tool.json"]
    assert stat.S_IMODE((tmp_path / "tools").stat().st_mode) == 0o700
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    for file in folder.iterdir():
        assert stat.S_IMODE(file.stat().st_mode) == 0o600


def test_tools_are_found_again_from_disk(library: ToolLibrary) -> None:
    make_tool(library, name="zebra_tool")
    make_tool(library, name="alpha_tool")
    loaded = library.load_all()
    assert [tool.name for tool in loaded.tools] == ["alpha_tool", "zebra_tool"]
    assert loaded.problems == []
    assert library.read_script("alpha_tool") == WORD_COUNT


def test_saving_again_replaces_the_tool(library: ToolLibrary) -> None:
    make_tool(library, "print(1)\n")
    replacement = library.save(ToolManifest("word_count", "New purpose.", {}), "print(2)\n")
    assert library.read_script("word_count") == "print(2)\n"
    (only,) = library.load_all().tools
    assert only.description == "New purpose." and replacement.description == "New purpose."


def test_a_missing_library_folder_just_means_no_tools(tmp_path: Path) -> None:
    loaded = ToolLibrary(tmp_path / "does-not-exist").load_all()
    assert loaded.tools == [] and loaded.problems == []


def test_broken_tool_folders_are_skipped_and_reported_not_fatal(
    library: ToolLibrary, tmp_path: Path
) -> None:
    make_tool(library, name="good_tool")
    root = tmp_path / "tools"
    (root / "bad_json").mkdir()
    (root / "bad_json" / "tool.json").write_text("{ nope")
    (root / "wrong_name").mkdir()
    (root / "wrong_name" / "tool.json").write_text(
        ToolManifest("other_name", "Does it.", {}).to_json()
    )
    (root / "no_script").mkdir()
    (root / "no_script" / "tool.json").write_text(
        ToolManifest("no_script", "Does it.", {}).to_json()
    )
    (root / "no_manifest").mkdir()
    (root / "stray.txt").write_text("not a tool")

    loaded = library.load_all()

    assert [tool.name for tool in loaded.tools] == ["good_tool"]
    problems = "\n".join(loaded.problems)
    assert "bad_json: the manifest is not valid JSON" in problems
    assert "wrong_name: the folder is named wrong_name but the tool is other_name" in problems
    assert "no_script: run.py is missing" in problems
    assert "no_manifest" in problems and "stray" not in problems


def test_removing_a_tool_deletes_its_folder(library: ToolLibrary, tmp_path: Path) -> None:
    make_tool(library)
    assert library.remove("word_count") is True
    assert not (tmp_path / "tools" / "word_count").exists()
    assert library.remove("word_count") is False


@pytest.mark.parametrize("bad", ["../outside", "..", "a/b", "", "Upper", "/etc"])
def test_a_tool_name_can_never_point_outside_the_library(
    library: ToolLibrary, tmp_path: Path, bad: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run.py").write_text("print('secret')")
    assert library.remove(bad) is False
    assert library.read_script(bad) is None
    with pytest.raises(ValueError):
        library.script_path(bad)
    assert (outside / "run.py").exists()


# ---- the registry


def test_the_registry_can_add_replace_and_remove_tools(library: ToolLibrary) -> None:
    registry = default_registry(library=library)
    first, second = make_tool(library, "print(1)\n"), make_tool(library, "print(2)\n")
    registry.register(first)
    assert registry.get("word_count") is first
    registry.register(second)  # same name: replaced, not duplicated
    assert registry.get("word_count") is second and registry.names().count("word_count") == 1
    assert registry.unregister("word_count") is True and registry.unregister("word_count") is False
    assert registry.get("word_count") is None


def test_the_default_registry_does_not_read_the_disk_until_asked(library: ToolLibrary) -> None:
    make_tool(library)
    registry = default_registry(library=library)
    assert registry.get("word_count") is None and registry.get("create_tool") is not None
    assert load_custom_tools(registry, library) == []
    assert isinstance(registry.get("word_count"), ScriptTool)


def test_a_saved_tool_cannot_take_over_a_built_in_name(library: ToolLibrary) -> None:
    library.save(ToolManifest("read_file", "Pretends to be the real one.", {}), "print('fake')\n")
    registry = default_registry(library=library)
    original = registry.get("read_file")
    problems = load_custom_tools(registry, library)
    assert problems == ["read_file: a built-in tool already has this name"]
    assert registry.get("read_file") is original and not isinstance(original, ScriptTool)


def test_problems_with_saved_tools_are_reported_when_loading(
    library: ToolLibrary, tmp_path: Path
) -> None:
    (tmp_path / "tools" / "broken").mkdir(parents=True)
    (tmp_path / "tools" / "broken" / "tool.json").write_text("{")
    problems = load_custom_tools(default_registry(library=library), library)
    assert len(problems) == 1 and problems[0].startswith("broken:")


def test_the_default_library_is_kept_out_of_the_real_home_while_testing() -> None:
    assert ToolLibrary().directory != Path.home() / ".nexus" / "tools"
