"""run_command: run a shell command in the working directory and return its output."""

import contextlib
import os
import re
import shutil
import signal
import subprocess

from pydantic import BaseModel, Field

from nexus.tools.base import Preview, Risk, Tool, ToolContext, ToolResult
from nexus.tools.output import cap_text

# Environment variables whose names suggest a secret are not passed to commands.
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.IGNORECASE)


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
        try:
            process = subprocess.Popen(
                [shutil.which("bash") or "sh", "-c", args.command],
                cwd=ctx.workspace,
                env=_safe_environment(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                start_new_session=True,  # So the whole command tree can be stopped together.
            )
        except OSError as err:
            return ToolResult.error(f"Could not start the command: {err.strerror or err}")

        try:
            output, _ = process.communicate(timeout=args.timeout_sec)
        except subprocess.TimeoutExpired:
            output = _stop(process)
            text, _ = cap_text(output, ctx)
            return ToolResult.error(
                f"Stopped: the command ran longer than {args.timeout_sec}s.\n{text}"
            )
        except KeyboardInterrupt:
            _stop(process)
            raise

        text, truncated = cap_text(
            output.strip() or "(no output)", ctx, hint="pipe to head or tail"
        )
        return ToolResult(
            ok=process.returncode == 0,
            output=f"exit code {process.returncode}\n{text}",
            truncated=truncated,
        )

    def preview(self, args: RunCommandArgs, ctx: ToolContext) -> Preview | None:
        return Preview("Run a command", body=f"$ {args.command}\n(in {ctx.workspace})")

    def grant_scope(self, args: RunCommandArgs, ctx: ToolContext) -> str:
        """ "Always allow" covers one program, such as git, and not every command."""
        words = args.command.split()
        return f"run_command {words[0]} ..." if words else "run_command"


def _stop(process: "subprocess.Popen[str]") -> str:
    """Kill the command and everything it started, and return what it had printed."""
    with contextlib.suppress(ProcessLookupError):  # Already finished is fine.
        os.killpg(process.pid, signal.SIGKILL)
    output, _ = process.communicate()
    return output.strip()


def _safe_environment() -> dict[str, str]:
    """The current environment without secrets, and set up for non-interactive use."""
    env = {name: value for name, value in os.environ.items() if not _SECRET_NAME.search(name)}
    env.update(PAGER="cat", GIT_PAGER="cat", TERM="dumb")
    return env
