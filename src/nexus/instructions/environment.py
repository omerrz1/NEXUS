"""A snapshot of where the agent is running, captured once when the session starts."""

import os
import platform
from datetime import date
from pathlib import Path


def environment_block(workspace: Path) -> str:
    """Describe the working directory, OS, shell, and date for the model.

    It is captured once per session, not per message, so the start of the prompt stays
    identical and the model server can reuse its cache of it.
    """
    shell = Path(os.environ.get("SHELL", "sh")).name
    return "\n".join(
        [
            "Environment:",
            f"- Working directory: {workspace}",
            f"- Home folder: {Path.home()}",
            f"- System: {platform.platform(terse=True)}",
            f"- User shell: {shell} (run_command always uses bash)",
            f"- Today: {date.today().isoformat()}",
        ]
    )
