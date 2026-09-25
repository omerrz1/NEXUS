"""delete_tool: remove a tool that Nexus made."""

from pydantic import BaseModel, Field

from nexus.tools.base import Preview, Risk, Tool, ToolCatalog, ToolContext, ToolResult
from nexus.tools.custom.library import ToolLibrary
from nexus.tools.custom.script_tool import ScriptTool


class DeleteToolArgs(BaseModel):
    name: str = Field(description="The name of a tool you made.")


class DeleteTool(Tool[DeleteToolArgs]):
    name = "delete_tool"
    description = "Delete a tool you made."
    args_model = DeleteToolArgs
    risk = Risk.WRITE
    always_ask = True

    def __init__(self, library: ToolLibrary, catalog: ToolCatalog) -> None:
        self._library = library
        self._catalog = catalog

    def run(self, args: DeleteToolArgs, ctx: ToolContext) -> ToolResult:
        if not isinstance(self._catalog.get(args.name), ScriptTool):
            return ToolResult.error(self._not_found(args.name))
        if not self._library.remove(args.name):
            return ToolResult.error(f"Could not delete the tool {args.name}.")
        self._catalog.unregister(args.name)
        return ToolResult.success(f"Deleted the tool {args.name}.")

    def preview(self, args: DeleteToolArgs, ctx: ToolContext) -> Preview | None:
        """The script that will be lost, shown as removed lines."""
        before = self._library.read_script(args.name)
        note = "The tool and its script are deleted. This cannot be undone."
        path = str(self._library.script_path(args.name)) if before is not None else ""
        return Preview(
            f"Delete the tool {args.name}", body=note, path=path, before=before, after=""
        )

    def _not_found(self, name: str) -> str:
        made = [n for n in self._catalog.names() if isinstance(self._catalog.get(n), ScriptTool)]
        known = ", ".join(made) if made else "none yet"
        return f"There is no tool you made called '{name}'. Tools you made: {known}."
