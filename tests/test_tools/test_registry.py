"""Tests for the tool registry."""

from pydantic import BaseModel

from nexus.tools.base import Risk, Tool, ToolContext, ToolResult
from nexus.tools.registry import ToolRegistry, default_registry


class EchoArgs(BaseModel):
    text: str


class Echo(Tool[EchoArgs]):
    name = "echo"
    description = "Return the given text."
    args_model = EchoArgs
    risk = Risk.NONE

    def run(self, args: EchoArgs, ctx: ToolContext) -> ToolResult:
        return ToolResult.success(args.text)


def test_default_registry_is_empty_until_tools_are_added() -> None:
    assert default_registry().names() == []


def test_registry_lookup_and_specs() -> None:
    registry = ToolRegistry([Echo()])
    assert registry.names() == ["echo"]
    assert registry.get("echo") is not None
    assert registry.get("missing") is None
    spec = registry.specs()[0]
    assert spec.name == "echo"
    assert "text" in spec.parameters["properties"]
