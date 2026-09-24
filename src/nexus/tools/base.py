"""The Tool base class and the plain data every tool uses: Risk, ToolContext, ToolResult."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Generic, TypeVar

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
    """What a tool may know about the session it runs in."""

    workspace: Path


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
    path_fields: tuple[str, ...] = ()

    @abstractmethod
    def run(self, args: Args, ctx: ToolContext) -> ToolResult:
        """Do the work. Expected failures are returned as ToolResult.error, never raised."""

    def spec(self) -> ToolSpec:
        """Describe this tool to the model as a JSON Schema function."""
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.args_model.model_json_schema(),
        )
