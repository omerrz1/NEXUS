"""The Tool base class and the plain data every tool uses: Risk, ToolContext, ToolResult."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from nexus.messages import ToolSpec


class Risk(StrEnum):
    """How much harm a tool can do; guardrails use it to pick a default verdict."""

    NONE = "none"
    READ = "read"
    WRITE = "write"
    EXEC = "exec"


@dataclass(frozen=True)
class ToolContext:
    """What a tool may know about the session it runs in, including its size limits."""

    workspace: Path
    max_output_bytes: int = 8192
    max_output_lines: int = 200

    @classmethod
    def for_window(cls, workspace: Path, context_window: int) -> "ToolContext":
        """Size the output limits to the model's window so one result cannot fill it."""
        # Half the window in bytes is roughly a sixth of it in tokens for code and markdown.
        max_bytes = min(8192, context_window // 2)
        return cls(workspace=workspace.resolve(), max_output_bytes=max_bytes)

    def resolve(self, raw_path: str) -> Path:
        """Turn a path from the model into an absolute one.

        Relative paths start at the workspace, and a leading ~ is the home folder.
        Symlinks are followed, so the result is where the path really points.
        """
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path.resolve()

    def contains(self, path: Path) -> bool:
        """Return True if `path` is the workspace or something inside it."""
        return path.is_relative_to(self.workspace.resolve())


@dataclass(frozen=True)
class ToolResult:
    """The text a tool hands back to the model, and whether the call worked."""

    ok: bool
    output: str
    truncated: bool = False

    @classmethod
    def success(cls, output: str, truncated: bool = False) -> "ToolResult":
        """Build a result for a call that worked."""
        return cls(ok=True, output=output, truncated=truncated)

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        """Build a result the model can read and correct itself from."""
        return cls(ok=False, output=message)


Args = TypeVar("Args", bound=BaseModel)


class Tool(ABC, Generic[Args]):
    """One capability the model can call. Subclasses fill in the attributes and run()."""

    name: str
    description: str
    args_model: type[Args]
    risk: Risk
    path_fields: tuple[str, ...] = ()  # arguments that hold file paths
    command_fields: tuple[str, ...] = ()  # arguments that hold a shell command

    @abstractmethod
    def run(self, args: Args, ctx: ToolContext) -> ToolResult:
        """Do the work. Expected failures are returned as ToolResult.error, never raised."""

    def preview(self, args: Args, ctx: ToolContext) -> str | None:
        """Text shown to the user when approval is needed, such as a diff or the command."""
        return None

    def grant_scope(self, args: Args, ctx: ToolContext) -> str:
        """What "always allow" covers. By default, every call to this tool."""
        return self.name

    def spec(self) -> ToolSpec:
        """Describe this tool to the model as a JSON Schema function."""
        schema = _without_titles(self.args_model.model_json_schema())
        return ToolSpec(name=self.name, description=self.description, parameters=schema)

    def signature(self) -> str:
        """The arguments in one line, e.g. "path (string, required), offset (integer)"."""
        schema = self.args_model.model_json_schema()
        required = set(schema.get("required", []))
        parts = []
        for name, prop in schema.get("properties", {}).items():
            kind = prop.get("type", "value")
            parts.append(f"{name} ({kind}{', required' if name in required else ''})")
        return ", ".join(parts)


def _without_titles(schema: Any) -> Any:
    """Pydantic adds a "title" to every field; dropping them saves prompt tokens."""
    if isinstance(schema, dict):
        return {key: _without_titles(value) for key, value in schema.items() if key != "title"}
    if isinstance(schema, list):
        return [_without_titles(item) for item in schema]
    return schema
