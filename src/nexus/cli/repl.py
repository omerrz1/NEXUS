"""Interactive REPL session for conversational interaction with the local model."""

from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console

from nexus.brain.base import Brain
from nexus.cli.prompt import build_prompt_session
from nexus.cli.render import CliRenderer
from nexus.cli.settings import SETTING_CHOICES, Settings, apply_setting, next_choice
from nexus.cli.slash import handle_slash_command
from nexus.cli.theme import MUTED, SKY
from nexus.messages import Message
from nexus.tools.registry import ToolRegistry

_SYSTEM_PROMPT = (
    "You are Nexus, a local-first coding assistant. "
    "You operate with a local model, local tools, and zero network access. "
    "Be concise, direct, and helpful."
)


def run_repl(
    brain: Brain,
    tools: ToolRegistry,
    settings: Settings,
    settings_path: Path | None = None,
    model_name: str = "nexus-qwen",
    base_url: str = "http://127.0.0.1:11434/v1",
    animate_banner: bool = True,
    console: Console | None = None,
) -> None:
    """Show the banner, then read prompts and slash commands until the user exits."""
    out = CliRenderer(console=console)
    out.show_raw_thoughts = settings.show_thinking
    # Session state shared with slash commands, which may read or change it (e.g. /mode).
    session: dict[str, Any] = {
        "model": model_name,
        "base_url": base_url,
        "mode": settings.mode,
        "depth": settings.depth,
        "show_thinking": settings.show_thinking,
        "settings_path": settings_path,
        "tokens": 0,
        "turns": 0,
        "speed": 0.0,
        "context_window": brain.context_window,
        "renderer": out,
        "tools": tools,
        "messages": [Message.system(_SYSTEM_PROMPT)],
        "last_reply": "",
    }

    _print_welcome(out, session, animate_banner)
    prompt = build_prompt_session(
        session,
        tools.names(),
        on_hotkey=lambda key: apply_setting(
            session, key, next_choice(SETTING_CHOICES[key], session[key])
        ),
    )
    _run_input_loop(prompt, brain, out, session)


def _print_welcome(out: CliRenderer, session: dict[str, Any], animate_banner: bool) -> None:
    """Show the banner, the settings card, and the main shortcuts."""
    out.print_banner(animate=animate_banner)
    out.print_hud(
        model=session["model"],
        base_url=session["base_url"],
        mode=session["mode"],
        depth=session["depth"],
        context_window=session["context_window"],
    )
    out.print_tips()


def _run_input_loop(
    prompt: PromptSession[str], brain: Brain, out: CliRenderer, session: dict[str, Any]
) -> None:
    """Read user input until the user exits, running slash commands or model turns."""
    while True:
        try:
            user_input = prompt.prompt().strip()
        except KeyboardInterrupt:
            continue  # Ctrl-C clears the line, like a shell.
        except EOFError:
            out.console.print(f"[bold {SKY}]Goodbye![/bold {SKY}]")
            return

        if not user_input:
            continue
        if user_input.startswith("/"):
            if handle_slash_command(user_input, session, out.console):
                return
            continue
        _run_model_turn(user_input, brain, out, session)


def _run_model_turn(
    user_input: str, brain: Brain, out: CliRenderer, session: dict[str, Any]
) -> None:
    """Send the user's message to the model, stream the reply, and update the session."""
    messages: list[Message] = session["messages"]
    messages.append(Message.user(user_input))
    out.start_stream()

    try:
        reply = brain.chat(
            messages,
            on_delta=out.print_chunk,
            on_reasoning=out.print_reasoning_chunk,
            depth=session["depth"],
        )
    except KeyboardInterrupt:
        out.end_stream()
        messages.pop()  # Drop the unanswered prompt so the history stays consistent.
        out.console.print(f"  [{MUTED}]Stopped.[/{MUTED}]\n")
        return
    except Exception as err:
        out.end_stream()
        messages.pop()
        out.print_error(f"Inference error: {err}\n")
        return

    session["speed"] = out.end_stream()
    messages.append(reply.message)
    session["last_reply"] = reply.message.content
    session["tokens"] += reply.usage.total_tokens
    session["turns"] += 1
    for call in reply.tool_calls:
        out.print_tool_call(call.name, call.arguments)
