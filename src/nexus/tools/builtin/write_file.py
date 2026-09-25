"""write_file: create a file, or replace an existing one completely."""

from pydantic import BaseModel, Field

from nexus.tools.base import Preview, Risk, Tool, ToolContext, ToolResult

_MAX_CONTENT_CHARS = 1_000_000


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
        return ToolResult.success(f"{verb} {ctx.display_path(path)} ({line_count} lines).")

    def preview(self, args: WriteFileArgs, ctx: ToolContext) -> Preview | None:
        """The file as it will be written, and as it is now if it already exists."""
        path = ctx.resolve(args.path)
        shown = ctx.display_path(path)
        if not path.exists():
            return Preview(f"Create {shown}", path=str(path), after=args.content)
        try:
            before = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            note = "The current contents could not be read."
            return Preview(f"Replace {shown}", body=note, path=str(path), after=args.content)
        return Preview(f"Replace {shown}", path=str(path), before=before, after=args.content)

    def grant_scope(self, args: WriteFileArgs, ctx: ToolContext) -> str:
        """Writing inside the workspace can be granted once; elsewhere it is per file."""
        path = ctx.resolve(args.path)
        return "write_file in the working directory" if ctx.contains(path) else f"write_file {path}"
