"""list_dir: show what is inside a folder, optionally a few levels deep."""

from pathlib import Path

from pydantic import BaseModel, Field

from nexus.tools.base import Risk, Tool, ToolContext, ToolResult
from nexus.tools.output import cap_text, human_size


class ListDirArgs(BaseModel):
    path: str = Field(".", description="Folder to list. Relative to the working directory.")
    depth: int = Field(1, ge=1, le=3, description="How many levels down to list.")
    show_hidden: bool = Field(False, description="Include files and folders starting with a dot.")


class ListDir(Tool[ListDirArgs]):
    name = "list_dir"
    description = "List the files and folders in a directory. Folders end with a slash."
    args_model = ListDirArgs
    risk = Risk.READ
    path_fields = ("path",)

    def run(self, args: ListDirArgs, ctx: ToolContext) -> ToolResult:
        folder = ctx.resolve(args.path)
        if not folder.exists():
            return ToolResult.error(f"Not found: {args.path}. Check the spelling with find_files.")
        if not folder.is_dir():
            return ToolResult.error(f"{args.path} is a file. Use read_file to see its contents.")

        try:
            lines = _list_folder(folder, args.depth, args.show_hidden)
        except PermissionError:
            return ToolResult.error(f"No permission to list {args.path}.")
        if not lines:
            return ToolResult.success(f"{args.path} is empty.")

        text, truncated = cap_text("\n".join(lines), ctx, hint="list a subfolder instead")
        return ToolResult.success(text, truncated)


def _list_folder(folder: Path, depth: int, show_hidden: bool, indent: str = "") -> list[str]:
    """One line per entry, folders first. Folders that cannot be read are skipped."""
    try:
        entries = sorted(folder.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        if indent:
            return [f"{indent}(no permission)"]
        raise

    lines: list[str] = []
    for entry in entries:
        if entry.name.startswith(".") and not show_hidden:
            continue
        lines.append(indent + _describe(entry))
        if entry.is_dir() and not entry.is_symlink() and depth > 1:
            lines += _list_folder(entry, depth - 1, show_hidden, indent + "  ")
    return lines


def _describe(entry: Path) -> str:
    """Folders get a trailing slash, symlinks an @, and files their size."""
    if entry.is_symlink():
        return f"{entry.name}@"
    if entry.is_dir():
        return f"{entry.name}/"
    try:
        return f"{entry.name}  ({human_size(entry.stat().st_size)})"
    except OSError:
        return entry.name
