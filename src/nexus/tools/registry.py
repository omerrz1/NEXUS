"""The explicit list of tools Nexus offers the model, and lookups over it."""

from collections.abc import Iterator, Sequence
from typing import Any

from nexus.messages import ToolSpec
from nexus.tools.base import Tool
from nexus.tools.builtin.find_files import FindFiles
from nexus.tools.builtin.list_dir import ListDir
from nexus.tools.builtin.read_file import ReadFile
from nexus.tools.builtin.run_command import RunCommand
from nexus.tools.builtin.write_file import WriteFile

# Every tool the model can call is listed here by hand. Anything shown to the user, and
# every tool spec sent to the model, comes from this list.
BUILTIN_TOOLS: tuple[Tool[Any], ...] = (
    ReadFile(),
    ListDir(),
    FindFiles(),
    WriteFile(),
    RunCommand(),
)


class ToolRegistry:
    """A read-only, name-indexed view over a fixed set of tools."""

    def __init__(self, tools: Sequence[Tool[Any]] = ()) -> None:
        self._tools: dict[str, Tool[Any]] = {tool.name: tool for tool in tools}

    def __iter__(self) -> Iterator[Tool[Any]]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> Tool[Any] | None:
        """Return the tool with this name, or None if no such tool exists."""
        return self._tools.get(name)

    def names(self) -> list[str]:
        """Return every tool name, in registration order."""
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        """Return the model-facing spec of every tool."""
        return [tool.spec() for tool in self._tools.values()]


def default_registry() -> ToolRegistry:
    """Build the registry holding the built-in tools."""
    return ToolRegistry(BUILTIN_TOOLS)
