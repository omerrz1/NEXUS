"""The explicit list of tools Nexus offers the model, and lookups over it."""

from collections.abc import Iterator, Sequence
from typing import Any

from nexus.messages import ToolSpec
from nexus.tools.base import Tool

# Every tool the model can call is listed here by hand. The list is empty until the
# first built-in tool is implemented; anything shown to the user comes from this list.
BUILTIN_TOOLS: tuple[Tool[Any], ...] = ()


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
