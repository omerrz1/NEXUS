"""Non-interactive single-prompt execution mode for Nexus."""

from nexus.brain.base import Brain
from nexus.cli.render import CliRenderer
from nexus.messages import Message


def run_oneshot(
    prompt: str,
    brain: Brain,
    renderer: CliRenderer | None = None,
) -> int:
    """Execute a single prompt non-interactively and stream the output."""
    out = renderer or CliRenderer()
    messages = [
        Message.system("You are Nexus, a local-first coding assistant."),
        Message.user(prompt),
    ]

    out.start_stream()
    try:
        reply = brain.chat(
            messages,
            on_delta=out.print_chunk,
            on_reasoning=out.print_reasoning_chunk,
        )
        out.end_stream()
        if reply.tool_calls:
            for call in reply.tool_calls:
                out.print_tool_call(call.name, call.arguments)
        return 0
    except Exception as err:
        out.end_stream()
        out.print_error(str(err))
        return 1
