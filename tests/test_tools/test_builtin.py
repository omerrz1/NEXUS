"""Tests for the built-in tools, run against temporary folders."""

import os
from pathlib import Path

import pytest

from nexus.tools.base import ToolContext, ToolResult
from nexus.tools.registry import default_registry


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext.for_window(tmp_path, 16384)


def run(name: str, ctx: ToolContext, **arguments: object) -> ToolResult:
    tool = default_registry().get(name)
    assert tool is not None
    return tool.run(tool.args_model(**arguments), ctx)


def test_registry_holds_exactly_the_built_in_tools() -> None:
    names = default_registry().names()
    assert names == [
        "read_file",
        "list_dir",
        "find_files",
        "write_file",
        "run_command",
        "web_search",
        "update_todo",
        "remember",
        "forget",
    ]


def test_tool_specs_have_no_titles_to_save_tokens() -> None:
    for spec in default_registry().specs():
        assert "title" not in str(spec.parameters)


def test_tool_specs_are_flat_with_no_references_for_small_models() -> None:
    for spec in default_registry().specs():
        assert "$ref" not in str(spec.parameters) and "$defs" not in str(spec.parameters)


# ---- read_file


def test_read_file_numbers_lines_and_pages(ctx: ToolContext) -> None:
    (ctx.workspace / "a.txt").write_text("\n".join(f"line{n}" for n in range(1, 11)))
    first = run("read_file", ctx, path="a.txt", limit=4)
    assert "    1  line1" in first.output and "    4  line4" in first.output
    assert "showing lines 1-4 of 10; call read_file with offset=4" in first.output
    rest = run("read_file", ctx, path="a.txt", offset=4, limit=100)
    assert "    5  line5" in rest.output and "showing lines" not in rest.output


def test_read_file_problems_are_messages_for_the_model(ctx: ToolContext) -> None:
    (ctx.workspace / "folder").mkdir()
    (ctx.workspace / "bin").write_bytes(b"\x00\x01\x02")
    (ctx.workspace / "empty.txt").write_text("")
    (ctx.workspace / "short.txt").write_text("one\n")
    assert "Not found" in run("read_file", ctx, path="nope.txt").output
    assert "is a directory" in run("read_file", ctx, path="folder").output
    assert "binary" in run("read_file", ctx, path="bin").output
    assert run("read_file", ctx, path="empty.txt").output.endswith("is empty.")
    assert "past the end" in run("read_file", ctx, path="short.txt", offset=5).output


def test_read_file_respects_the_output_budget(tmp_path: Path) -> None:
    small = ToolContext(workspace=tmp_path, max_output_bytes=200)
    (tmp_path / "big.txt").write_text("\n".join("x" * 50 for _ in range(100)))
    result = run("read_file", small, path="big.txt")
    assert len(result.output.encode()) < 400
    assert "call read_file with offset=" in result.output


def test_read_file_can_read_outside_the_workspace(
    ctx: ToolContext, tmp_path_factory: pytest.TempPathFactory
) -> None:
    elsewhere = tmp_path_factory.mktemp("elsewhere") / "note.txt"
    elsewhere.write_text("hello")
    assert "hello" in run("read_file", ctx, path=str(elsewhere)).output


# ---- list_dir


def test_list_dir_lists_folders_first_and_hides_dotfiles(ctx: ToolContext) -> None:
    (ctx.workspace / "src").mkdir()
    (ctx.workspace / "src" / "app.py").write_text("x")
    (ctx.workspace / "a.txt").write_text("abc")
    (ctx.workspace / ".secret").write_text("s")
    shallow = run("list_dir", ctx).output
    assert shallow.splitlines() == ["src/", "a.txt  (3 B)"]
    deep = run("list_dir", ctx, depth=2, show_hidden=True).output
    assert "  app.py  (1 B)" in deep and ".secret" in deep


def test_list_dir_errors(ctx: ToolContext) -> None:
    (ctx.workspace / "f.txt").write_text("x")
    (ctx.workspace / "empty").mkdir()
    assert "Not found" in run("list_dir", ctx, path="missing").output
    assert "is a file" in run("list_dir", ctx, path="f.txt").output
    assert run("list_dir", ctx, path="empty").output.endswith("is empty.")


# ---- find_files


def test_find_files_matches_names_and_skips_noise(ctx: ToolContext) -> None:
    for path in (
        "a/one.py",
        "a/b/two.py",
        "node_modules/x/three.py",
        ".hidden/four.py",
        "five.txt",
    ):
        (ctx.workspace / path).parent.mkdir(parents=True, exist_ok=True)
        (ctx.workspace / path).write_text("")
    found = run("find_files", ctx, pattern="*.py").output.splitlines()
    assert [Path(line).name for line in found] == ["one.py", "two.py"]
    with_hidden = run("find_files", ctx, pattern="*.py", include_hidden=True).output
    assert "four.py" in with_hidden
    assert "No files match" in run("find_files", ctx, pattern="*.rs").output
    assert "not a folder" in run("find_files", ctx, pattern="*", path="five.txt").output


# ---- write_file


def test_write_file_creates_replaces_and_makes_folders(ctx: ToolContext) -> None:
    created = run("write_file", ctx, path="new/dir/f.txt", content="a\nb\n")
    assert created.ok and "Created" in created.output and "(2 lines)" in created.output
    assert (ctx.workspace / "new/dir/f.txt").read_text() == "a\nb\n"
    replaced = run("write_file", ctx, path="new/dir/f.txt", content="c")
    assert "Replaced" in replaced.output
    assert "is a folder" in run("write_file", ctx, path="new", content="x").output


def test_write_file_preview_shows_a_diff_for_existing_files(ctx: ToolContext) -> None:
    tool = default_registry().get("write_file")
    assert tool is not None
    (ctx.workspace / "f.txt").write_text("one\ntwo\n")
    changed = tool.preview(tool.args_model(path="f.txt", content="one\nTWO\n"), ctx)
    assert changed is not None and changed.title == "Replace f.txt"
    assert (changed.before, changed.after) == ("one\ntwo\n", "one\nTWO\n")
    assert changed.path == str(ctx.workspace / "f.txt")
    new = tool.preview(tool.args_model(path="brand-new.txt", content="hello\n"), ctx)
    assert new is not None and new.title == "Create brand-new.txt"
    assert new.before is None and new.after == "hello\n" and new.is_file_change


def test_previews_name_files_by_the_shortest_clear_path(ctx: ToolContext) -> None:
    tool = default_registry().get("write_file")
    assert tool is not None
    nested = tool.preview(tool.args_model(path="src/app/main.py", content="x"), ctx)
    assert nested is not None and nested.title == "Create src/app/main.py"
    elsewhere = tool.preview(tool.args_model(path="~/notes/todo.txt", content="x"), ctx)
    assert elsewhere is not None and elsewhere.title == "Create ~/notes/todo.txt"


def test_a_file_that_cannot_be_read_is_still_previewed(ctx: ToolContext) -> None:
    tool = default_registry().get("write_file")
    assert tool is not None
    path = ctx.workspace / "secret.txt"
    path.write_text("hidden")
    path.chmod(0o000)
    try:
        preview = tool.preview(tool.args_model(path="secret.txt", content="new"), ctx)
    finally:
        path.chmod(0o600)
    assert preview is not None and preview.title == "Replace secret.txt"
    assert preview.before is None and "could not be read" in preview.body


def test_the_command_preview_shows_the_command_and_folder(ctx: ToolContext) -> None:
    tool = default_registry().get("run_command")
    assert tool is not None
    preview = tool.preview(tool.args_model(command="git status"), ctx)
    assert preview is not None and not preview.is_file_change
    assert preview.body.startswith("$ git status") and str(ctx.workspace) in preview.body


def test_write_file_grant_scope_is_wider_inside_the_workspace(ctx: ToolContext) -> None:
    tool = default_registry().get("write_file")
    assert tool is not None
    inside = tool.grant_scope(tool.args_model(path="a.txt", content=""), ctx)
    outside = tool.grant_scope(tool.args_model(path="/tmp/other.txt", content=""), ctx)
    assert inside == "write_file in the working directory"
    assert outside.startswith("write_file /") and "other.txt" in outside


# ---- run_command


def test_run_command_returns_output_and_exit_code(ctx: ToolContext) -> None:
    ok = run("run_command", ctx, command="echo hi; echo oops >&2")
    assert (
        ok.ok and ok.output.startswith("exit code 0") and "hi" in ok.output and "oops" in ok.output
    )
    failed = run("run_command", ctx, command="exit 3")
    assert not failed.ok and "exit code 3" in failed.output


def test_run_command_runs_in_the_workspace_with_no_input(ctx: ToolContext) -> None:
    assert str(ctx.workspace) in run("run_command", ctx, command="pwd").output
    # cat would wait forever for input if stdin were open.
    assert run("run_command", ctx, command="cat").ok


def test_run_command_timeout_stops_the_whole_process_tree(ctx: ToolContext) -> None:
    marker = ctx.workspace / "still-running"
    command = f"(sleep 2; touch {marker}) & sleep 30"
    result = run("run_command", ctx, command=command, timeout_sec=1)
    assert not result.ok and "longer than 1s" in result.output
    import time

    time.sleep(2.5)
    assert not marker.exists()


def test_run_command_hides_secrets_from_commands(
    ctx: ToolContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MY_API_TOKEN", "hunter2")
    monkeypatch.setenv("VISIBLE_SETTING", "fine")
    output = run("run_command", ctx, command="echo [$MY_API_TOKEN] [$VISIBLE_SETTING]").output
    assert "[] [fine]" in output


def test_run_command_caps_long_output(tmp_path: Path) -> None:
    small = ToolContext(workspace=tmp_path, max_output_lines=5)
    result = run("run_command", small, command="seq 1 100")
    assert "output cut at 5 lines" in result.output and result.truncated
    assert os.path.exists(tmp_path)


def test_output_limit_scales_with_the_context_window(tmp_path: Path) -> None:
    assert ToolContext.for_window(tmp_path, 4096).max_output_bytes == 2048
    assert ToolContext.for_window(tmp_path, 100_000).max_output_bytes == 8192
