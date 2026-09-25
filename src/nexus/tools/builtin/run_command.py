"""run_command: run a shell command in the working directory and return its output."""

import shutil

from pydantic import BaseModel, Field

from nexus.tools.base import Preview, Risk, Tool, ToolContext, ToolResult
from nexus.tools.output import cap_text
from nexus.tools.process import run_process


class RunCommandArgs(BaseModel):
    command: str = Field(description="The bash command to run, e.g. 'ls -la' or 'pytest -q'.")
    timeout_sec: int = Field(60, ge=1, le=600, description="Stop the command after this long.")


class RunCommand(Tool[RunCommandArgs]):
    name = "run_command"
    description = (
        "Run a bash command in the working directory and return its output and exit code. "
        "It has no input and no internet access."
    )
    args_model = RunCommandArgs
    risk = Risk.EXEC
    command_fields = ("command",)

    def run(self, args: RunCommandArgs, ctx: ToolContext) -> ToolResult:
        argv = [shutil.which("bash") or "sh", "-c", args.command]
        result = run_process(argv, ctx.workspace, args.timeout_sec)
        if result.start_error:
            return ToolResult.error(f"Could not start the command: {result.start_error}")
        if result.timed_out:
            text, _ = cap_text(result.output, ctx)
            return ToolResult.error(
                f"Stopped: the command ran longer than {args.timeout_sec}s.\n{text}"
            )

        text, truncated = cap_text(
            result.output.strip() or "(no output)", ctx, hint="pipe to head or tail"
        )
        return ToolResult(
            ok=result.exit_code == 0,
            output=f"exit code {result.exit_code}\n{text}",
            truncated=truncated,
        )

    def preview(self, args: RunCommandArgs, ctx: ToolContext) -> Preview | None:
        folder = ctx.display_path(ctx.workspace)
        return Preview("Run a command", body=f"$ {args.command}\n(in {folder})")

    def grant_scope(self, args: RunCommandArgs, ctx: ToolContext) -> str:
        """ "Always allow" covers one program, such as git, and not every command."""
        words = args.command.split()
        return f"run_command {words[0]} ..." if words else "run_command"
