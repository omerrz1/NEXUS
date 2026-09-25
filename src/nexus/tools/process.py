"""Runs a child process the way every tool does: no keyboard input, a time limit, no secrets."""

import contextlib
import os
import re
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Environment variables whose names suggest a secret are not passed to child processes.
_SECRET_NAME = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH", re.IGNORECASE)


@dataclass(frozen=True)
class ProcessResult:
    """How a child process ended."""

    output: str  # What it printed, error output included.
    exit_code: int | None  # None if it timed out or never started.
    timed_out: bool = False
    start_error: str = ""  # Why it could not be started, if it could not.


def run_process(
    argv: list[str], cwd: Path, timeout_sec: int, input_text: str | None = None
) -> ProcessResult:
    """Run `argv` in `cwd` and wait for it, stopping it and everything it started on timeout.

    `input_text` is what the process reads on standard input. Without it, standard input is
    closed, so a program that waits for input ends instead of hanging.
    """
    try:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=safe_environment(),
            stdin=subprocess.DEVNULL if input_text is None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,  # So the whole process tree can be stopped together.
        )
    except OSError as err:
        return ProcessResult("", None, start_error=err.strerror or str(err))

    try:
        output, _ = process.communicate(input=input_text, timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        return ProcessResult(_stop(process), None, timed_out=True)
    except KeyboardInterrupt:
        _stop(process)
        raise
    return ProcessResult(output, process.returncode)


def safe_environment() -> dict[str, str]:
    """The current environment without secrets, and set up for non-interactive use."""
    env = {name: value for name, value in os.environ.items() if not _SECRET_NAME.search(name)}
    env.update(PAGER="cat", GIT_PAGER="cat", TERM="dumb")
    return env


def _stop(process: "subprocess.Popen[str]") -> str:
    """Kill the process and everything it started, and return what it had printed."""
    with contextlib.suppress(ProcessLookupError):  # Already finished is fine.
        os.killpg(process.pid, signal.SIGKILL)
    output, _ = process.communicate()
    return output.strip()
