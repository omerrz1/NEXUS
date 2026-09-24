"""read_file: show a text file with line numbers, a page at a time."""

from pathlib import Path

from pydantic import BaseModel, Field

from nexus.tools.base import Risk, Tool, ToolContext, ToolResult

_MAX_FILE_BYTES = 5_000_000
_MAX_LINE_CHARS = 300  # Minified or generated files can have enormous lines.


class ReadFileArgs(BaseModel):
    path: str = Field(description="File to read. Relative to the working directory, or absolute.")
    offset: int = Field(0, ge=0, description="Number of lines to skip before reading.")
    limit: int = Field(200, ge=1, le=1000, description="Maximum number of lines to return.")


class ReadFile(Tool[ReadFileArgs]):
    name = "read_file"
    description = "Read a text file and return it with line numbers. Long files are paged."
    args_model = ReadFileArgs
    risk = Risk.READ
    path_fields = ("path",)

    def run(self, args: ReadFileArgs, ctx: ToolContext) -> ToolResult:
        path = ctx.resolve(args.path)
        problem = _check_readable(path, args.path)
        if problem:
            return ToolResult.error(problem)

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            return ToolResult.success(f"{args.path} is empty.")
        if args.offset >= len(lines):
            return ToolResult.error(f"{args.path} has {len(lines)} lines; offset is past the end.")

        shown = _number_lines(lines, args, ctx)
        return ToolResult.success("\n".join(shown) + _paging_footer(args, len(shown), len(lines)))


def _check_readable(path: Path, raw_path: str) -> str | None:
    """Return a message for the model if the path cannot be read as text, else None."""
    if not path.exists():
        return f"Not found: {raw_path}. Use find_files or list_dir to look for it."
    if path.is_dir():
        return f"{raw_path} is a directory. Use list_dir to see what is inside."
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return f"{raw_path} is too large to read at once. Use run_command with head or tail."
        with path.open("rb") as handle:
            if b"\0" in handle.read(8192):
                return f"{raw_path} looks like a binary file, not text."
    except OSError as err:
        return f"Cannot read {raw_path}: {err.strerror or err}"
    return None


def _number_lines(lines: list[str], args: ReadFileArgs, ctx: ToolContext) -> list[str]:
    """Number the requested window, stopping early if it would exceed the byte limit."""
    shown: list[str] = []
    size = 0
    window = lines[args.offset : args.offset + min(args.limit, ctx.max_output_lines)]
    for number, line in enumerate(window, start=args.offset + 1):
        text = f"{number:>5}  {line[:_MAX_LINE_CHARS]}"
        size += len(text) + 1
        if size > ctx.max_output_bytes and shown:
            break
        shown.append(text)
    return shown


def _paging_footer(args: ReadFileArgs, shown_count: int, total: int) -> str:
    """Tell the model how to continue when the file has more lines than were shown."""
    end = args.offset + shown_count
    if end >= total:
        return ""
    return f"\n[showing lines {args.offset + 1}-{end} of {total}; call read_file with offset={end}]"
