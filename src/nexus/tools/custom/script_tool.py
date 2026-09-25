"""A tool made from a script: the inputs go in as JSON, and what the script prints comes back."""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, create_model

from nexus.tools.base import Preview, Risk, Tool, ToolContext, ToolResult
from nexus.tools.custom.manifest import ToolManifest
from nexus.tools.output import cap_text
from nexus.tools.process import run_process

TIMEOUT_SEC = 60


class ScriptTool(Tool[BaseModel]):
    """Runs `script` with the Python that runs Nexus, as a separate process.

    The script reads one JSON object (its inputs) from standard input and prints its result.
    It runs in the working directory with secrets removed from its environment, and is
    stopped after a minute. It always counts as a command for the guardrails, whatever it
    does, because nothing checks what a script does.
    """

    risk = Risk.EXEC

    def __init__(self, manifest: ToolManifest, script: Path) -> None:
        self.name = manifest.name
        self.description = manifest.description
        self.args_model = _arguments_model(manifest)
        self.script = script

    def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        inputs = json.dumps(args.model_dump())
        result = run_process(
            [sys.executable, str(self.script)], ctx.workspace, TIMEOUT_SEC, input_text=inputs
        )
        if result.start_error:
            return ToolResult.error(f"Could not start the tool: {result.start_error}")
        text, truncated = cap_text(result.output.strip() or "(no output)", ctx)
        if result.timed_out:
            return ToolResult.error(f"Stopped: the tool ran longer than {TIMEOUT_SEC}s.\n{text}")
        if result.exit_code != 0:
            # The script's own error message (a traceback, usually) is what lets the model fix it.
            return ToolResult.error(f"The tool failed (exit code {result.exit_code}).\n{text}")
        return ToolResult.success(text, truncated)

    def preview(self, args: BaseModel, ctx: ToolContext) -> Preview | None:
        inputs = "\n".join(f"{name} = {value!r}" for name, value in args.model_dump().items())
        return Preview(f"Run the tool {self.name}", body=inputs or "(no inputs)")

    def grant_scope(self, args: BaseModel, ctx: ToolContext) -> str:
        return f"the tool {self.name}"


def _arguments_model(manifest: ToolManifest) -> type[BaseModel]:
    """A pydantic model with one required text field per input, for validation and the schema."""
    fields: dict[str, Any] = {
        name: (str, Field(description=meaning)) for name, meaning in manifest.parameters.items()
    }
    return create_model(f"{manifest.name}_inputs", **fields)
