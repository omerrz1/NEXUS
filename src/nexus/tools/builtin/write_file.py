"""write_file: create a file, or replace an existing one completely."""

import difflib
from pathlib import Path

from pydantic import BaseModel, Field

from nexus.tools.base import Risk, Tool, ToolContext, ToolResult

_MAX_CONTENT_CHARS = 1_000_000
_PREVIEW_LINES = 30


class WriteFileArgs(BaseModel):
    path: str = Field(description="File to write. Relative to the working directory, or absolute.")
    content: str = Field(description="The complete new contents of the file.")


class WriteFile(Tool[WriteFileArgs]):
    name = "write_file"
    description = (
        "Create a file, or replace an existing file completely. "
        "Missing folders are created. Read the file first if it already exists."
    )
    args_model = WriteFileArgs
    risk = Risk.WRITE
    path_fields = ("path",)

    def run(self, args: WriteFileArgs, ctx: ToolContext) -> ToolResult:
        path = ctx.resolve(args.path)
        if path.is_dir():
            return ToolResult.error(f"{args.path} is a folder. Give a file path instead.")
        if len(args.content) > _MAX_CONTENT_CHARS:
            return ToolResult.error("The content is too large to write in one call.")

        existed = path.exists()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.content, encoding="utf-8")
        except OSError as err:
            return ToolResult.error(f"Cannot write {args.path}: {err.strerror or err}")

        verb = "Replaced" if existed else "Created"
        line_count = len(args.content.splitlines())
        return ToolResult.success(f"{verb} {path} ({line_count} lines).")

    def preview(self, args: WriteFileArgs, ctx: ToolContext) -> str | None:
        """Show a diff against the current file, or the start of the new file."""
        path = ctx.resolve(args.path)
        if not path.exists():
            return _describe_new_file(path, args.content)
        try:
            old_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return f"Replace {path}"
        diff = difflib.unified_diff(
            old_lines, args.content.splitlines(), f"current {path.name}", "new", lineterm="", n=2
        )
        return _limit_lines(f"Replace {path}\n" + "\n".join(diff))

    def grant_scope(self, args: WriteFileArgs, ctx: ToolContext) -> str:
        """Writing inside the workspace can be granted once; elsewhere it is per file."""
        path = ctx.resolve(args.path)
        return "write_file in the working directory" if ctx.contains(path) else f"write_file {path}"


def _describe_new_file(path: Path, content: str) -> str:
    lines = content.splitlines()
    head = f"Create {path} ({len(lines)} lines)\n"
    return _limit_lines(head + "\n".join(f"+ {line}" for line in lines))


def _limit_lines(text: str) -> str:
    """Keep approval prompts short: show the first lines and say how many were left out."""
    lines = text.splitlines()
    if len(lines) <= _PREVIEW_LINES:
        return text
    return "\n".join(lines[:_PREVIEW_LINES]) + f"\n… {len(lines) - _PREVIEW_LINES} more lines"
