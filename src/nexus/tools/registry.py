"""The explicit list of tools Nexus offers the model, and lookups over it."""

from collections.abc import Iterator, Sequence
from typing import Any

from nexus.messages import ToolSpec
from nexus.session.memory import SessionMemory
from nexus.tools.base import Tool
from nexus.tools.builtin.create_tool import CreateTool
from nexus.tools.builtin.delete_tool import DeleteTool
from nexus.tools.builtin.find_files import FindFiles
from nexus.tools.builtin.forget import Forget
from nexus.tools.builtin.list_dir import ListDir
from nexus.tools.builtin.read_file import ReadFile
from nexus.tools.builtin.remember import Remember
from nexus.tools.builtin.run_command import RunCommand
from nexus.tools.builtin.update_todo import UpdateTodo
from nexus.tools.builtin.web_search import WebSearch
from nexus.tools.builtin.write_file import WriteFile
from nexus.tools.custom.library import ToolLibrary
from nexus.tools.custom.script_tool import ScriptTool

# The tools that keep no session state. Every tool the model can call is listed by hand,
# here or in default_registry(). Anything shown to the user, and every tool spec sent to the
# model, comes from those lists.
BUILTIN_TOOLS: tuple[Tool[Any], ...] = (
    ReadFile(),
    ListDir(),
    FindFiles(),
    WriteFile(),
    RunCommand(),
    WebSearch(),
)


class ToolRegistry:
    """The tools the model can call, looked up by name.

    It starts as a fixed list and changes only when Nexus makes or deletes a custom tool.
    """

    def __init__(self, tools: Sequence[Tool[Any]] = ()) -> None:
        self._tools: dict[str, Tool[Any]] = {tool.name: tool for tool in tools}

    def __iter__(self) -> Iterator[Tool[Any]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def register(self, tool: Tool[Any]) -> None:
        """Add a tool, replacing any tool with the same name."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Remove a tool. Returns False if there was no tool with this name."""
        return self._tools.pop(name, None) is not None

    def get(self, name: str) -> Tool[Any] | None:
        """Return the tool with this name, or None if no such tool exists."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """Return every tool name, in registration order."""
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        """Return the model-facing spec of every tool."""
        return [tool.spec() for tool in self._tools.values()]


def default_registry(
    memory: SessionMemory | None = None, library: ToolLibrary | None = None
) -> ToolRegistry:
    """Build the registry holding the built-in tools.

    The todo and notes tools work on `memory`, so pass the session's own memory object.
    Custom tools already on disk are not loaded here: call `load_custom_tools` for that.
    """
    # An empty memory object is still a real one, so test for None rather than using `or`.
    memory = SessionMemory() if memory is None else memory
    library = ToolLibrary() if library is None else library
    memory_tools: tuple[Tool[Any], ...] = (UpdateTodo(memory), Remember(memory), Forget(memory))
    registry = ToolRegistry((*BUILTIN_TOOLS, *memory_tools))
    registry.register(CreateTool(library, registry))
    registry.register(DeleteTool(library, registry))
    return registry


def load_custom_tools(registry: ToolRegistry, library: ToolLibrary) -> list[str]:
    """Add the custom tools found on disk. Returns a note about each one that was skipped."""
    loaded = library.load_all()
    problems = list(loaded.problems)
    for tool in loaded.tools:
        existing = registry.get(tool.name)
        if existing is not None and not isinstance(existing, ScriptTool):
            problems.append(f"{tool.name}: a built-in tool already has this name")
            continue
        registry.register(tool)
    return problems
