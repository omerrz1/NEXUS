"""create_tool: make a new tool from a Python script, or replace one made earlier."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from nexus.tools.base import Preview, Risk, Tool, ToolCatalog, ToolContext, ToolResult
from nexus.tools.custom.library import ToolLibrary
from nexus.tools.custom.manifest import MAX_DESCRIPTION_CHARS, ToolManifest
from nexus.tools.custom.script_tool import ScriptTool

MAX_CODE_CHARS = 20_000
# Every tool's description is sent with every request, so an unlimited number would eat the window.
MAX_MADE_TOOLS = 12


class CreateToolArgs(BaseModel):
    name: str = Field(description="Lowercase with underscores, like word_count.")
    description: str = Field(max_length=MAX_DESCRIPTION_CHARS, description="What the tool does.")
    parameters: dict[str, str] = Field(
        default_factory=dict, description="Input names, each with what it means. All are text."
    )
    code: str = Field(max_length=MAX_CODE_CHARS, description="The complete Python script.")

    @model_validator(mode="after")
    def _check_the_tool(self) -> Self:
        # Checked here, before the user is asked, so they never approve a script that
        # could not run. The model gets the message and can fix it.
        ToolManifest(self.name, self.description, dict(self.parameters))
        _check_syntax(self.code)
        return self


class CreateTool(Tool[CreateToolArgs]):
    name = "create_tool"
    description = "Make a tool from a Python script, or replace one you made. Ready to use at once."
    args_model = CreateToolArgs
    risk = Risk.WRITE
    always_ask = True

    def __init__(self, library: ToolLibrary, catalog: ToolCatalog) -> None:
        self._library = library
        self._catalog = catalog

    def run(self, args: CreateToolArgs, ctx: ToolContext) -> ToolResult:
        existing = self._catalog.get(args.name)
        if existing is not None and not isinstance(existing, ScriptTool):
            return ToolResult.error(f"'{args.name}' is a built-in tool. Choose another name.")
        if existing is None and self._made_count() >= MAX_MADE_TOOLS:
            return ToolResult.error(
                f"You already have {MAX_MADE_TOOLS} tools you made. "
                "Delete one with delete_tool first."
            )
        try:
            tool = self._library.save(
                ToolManifest(args.name, args.description, dict(args.parameters)), args.code
            )
        except OSError as err:
            return ToolResult.error(f"Could not save the tool: {err.strerror or err}")
        self._catalog.register(tool)

        verb = "Replaced" if existing is not None else "Created"
        inputs = ", ".join(f'{name}="..."' for name in args.parameters)
        return ToolResult.success(
            f"{verb} the tool {args.name}. It is in your tool list now: "
            f"call it directly as {args.name}({inputs}), not through run_command."
        )

    def _made_count(self) -> int:
        return sum(
            isinstance(self._catalog.get(name), ScriptTool) for name in self._catalog.names()
        )

    def preview(self, args: CreateToolArgs, ctx: ToolContext) -> Preview | None:
        """The script as it will be saved, as a diff when it replaces one."""
        before = self._library.read_script(args.name)
        verb = "Replace" if before is not None else "Create"
        inputs = ", ".join(args.parameters) or "none"
        note = (
            f"{args.description}\nInputs: {inputs}\n"
            "Runs on your computer, with your permissions, every time it is used."
        )
        return Preview(
            f"{verb} the tool {args.name}",
            body=note,
            path=str(self._library.script_path(args.name)),
            before=before,
            after=args.code,
        )


def _check_syntax(code: str) -> None:
    """Refuse a script Python cannot read, saying where, so the model can correct it."""
    if not code.strip():
        raise ValueError("the code is empty")
    try:
        compile(code, "run.py", "exec")
    except SyntaxError as err:
        raise ValueError(f"the code has a syntax error on line {err.lineno}: {err.msg}") from err
    except (ValueError, RecursionError, MemoryError) as err:
        raise ValueError(f"the code cannot be read ({type(err).__name__})") from err
