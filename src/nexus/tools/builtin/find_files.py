"""find_files: search for files and folders by name pattern."""

import fnmatch
import os
import time
from pathlib import Path

from pydantic import BaseModel, Field

from nexus.tools.base import Risk, Tool, ToolContext, ToolResult
from nexus.tools.output import cap_text

# Folders that are huge and never what the user is looking for.
_SKIPPED_FOLDERS = frozenset({"node_modules", "__pycache__", "venv", "site-packages"})
_MAX_MATCHES = 500
_MAX_SECONDS = 10.0


class FindFilesArgs(BaseModel):
    pattern: str = Field(description="Name pattern such as '*.py' or 'test_*.py'. Case-sensitive.")
    path: str = Field(".", description="Folder to search in, including its subfolders.")
    include_hidden: bool = Field(False, description="Also search folders starting with a dot.")


class FindFiles(Tool[FindFilesArgs]):
    name = "find_files"
    description = "Find files and folders whose name matches a pattern, searching subfolders."
    args_model = FindFilesArgs
    risk = Risk.READ
    path_fields = ("path",)

    def run(self, args: FindFilesArgs, ctx: ToolContext) -> ToolResult:
        root = ctx.resolve(args.path)
        if not root.is_dir():
            return ToolResult.error(f"{args.path} is not a folder that exists.")

        matches, stopped_early = _search(root, args)
        if not matches:
            note = f" (search stopped after {_MAX_SECONDS:.0f}s)" if stopped_early else ""
            return ToolResult.success(f"No files match '{args.pattern}' in {args.path}{note}.")

        text = "\n".join(matches)
        if stopped_early:
            text += "\n[search stopped early; narrow the pattern or the path to see more]"
        text, truncated = cap_text(text, ctx, hint="narrow the pattern or path")
        return ToolResult.success(text, truncated or stopped_early)


def _search(root: Path, args: FindFilesArgs) -> tuple[list[str], bool]:
    """Walk `root` and return (matching paths, whether the search hit a limit)."""
    deadline = time.monotonic() + _MAX_SECONDS
    matches: list[str] = []
    for folder, subfolders, files in os.walk(root):
        subfolders[:] = sorted(_searchable(subfolders, args.include_hidden))
        for name in sorted(subfolders + files):
            if _name_matches(name, args.pattern):
                matches.append(str(Path(folder, name)))
        if len(matches) >= _MAX_MATCHES or time.monotonic() > deadline:
            return matches[:_MAX_MATCHES], True
    return matches, False


def _searchable(folders: list[str], include_hidden: bool) -> list[str]:
    """Drop folders that are hidden or known to be huge and uninteresting."""
    return [
        name
        for name in folders
        if name not in _SKIPPED_FOLDERS and (include_hidden or not name.startswith("."))
    ]


def _name_matches(name: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern)
