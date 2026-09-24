"""Non-interactive single-prompt execution mode for Nexus."""

from nexus.brain.base import Depth
from nexus.cli.agent_events import EventPrinter
from nexus.cli.render import CliRenderer
from nexus.guardrails.modes import Mode
from nexus.instructions.assemble import build_system_prompt
from nexus.loop import Deps, run_agent
from nexus.messages import Message


def run_oneshot(
    prompt: str,
    deps: Deps,
    renderer: CliRenderer | None = None,
    depth: Depth = Depth.BALANCED,
    mode: Mode = Mode.ASK,
) -> int:
    """Answer one prompt, running any tools it needs. Returns the process exit code."""
    out = renderer or CliRenderer()
    printer = EventPrinter(out)
    messages = [
        Message.system(build_system_prompt(deps.ctx.workspace)),
        Message.user(prompt),
    ]
    try:
        result = run_agent(messages, deps, mode, depth, printer)
    except Exception as err:
        printer.close()
        out.print_error(str(err))
        return 1
    return 0 if result.halt is None else 1
