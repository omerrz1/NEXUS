"""Interactive REPL session for conversational interaction with the local model."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from rich.console import Console

from nexus.brain.base import DEFAULT_BASE_URL, DEFAULT_MODEL
from nexus.cli.agent_events import EventPrinter
from nexus.cli.prompt import build_prompt_session
from nexus.cli.render import CliRenderer, hud_from_session
from nexus.cli.settings import SETTING_CHOICES, Settings, apply_setting, next_choice
from nexus.cli.slash import handle_slash_command
from nexus.cli.status import current_git_branch, probe_server
from nexus.cli.theme import MUTED, SKY
from nexus.instructions.assemble import build_system_prompt
from nexus.loop import Deps, run_agent
from nexus.messages import Message


def run_repl(
    deps: Deps,
    settings: Settings,
    settings_path: Path | None = None,
    model_name: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
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
        "context_window": deps.brain.context_window,
        "renderer": out,
        "tools": deps.tools,
        "messages": [Message.system(build_system_prompt(deps.ctx.workspace))],
        "last_reply": "",
    }

    _print_welcome(out, session, animate_banner)
    prompt = build_prompt_session(
        session,
        deps.tools.names(),
        on_hotkey=lambda key: apply_setting(
            session, key, next_choice(SETTING_CHOICES[key], session[key])
        ),
    )
    _run_input_loop(prompt, deps, out, session)


def _print_welcome(out: CliRenderer, session: dict[str, Any], animate_banner: bool) -> None:
    """Show the banner, the details card, and the main shortcuts."""
    # The server and git checks run while the banner animates, so they add no waiting time.
    with ThreadPoolExecutor(max_workers=2) as pool:
        server = pool.submit(probe_server, session["base_url"], session["model"])
        branch = pool.submit(current_git_branch, Path.cwd())
        out.print_banner(animate=animate_banner)
        session["server"] = server.result()
        session["branch"] = branch.result()
    out.print_hud(hud_from_session(session))
    out.print_tips()


def _run_input_loop(
    prompt: PromptSession[str], deps: Deps, out: CliRenderer, session: dict[str, Any]
) -> None:
    """Read user input until the user exits, running slash commands or agent turns."""
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
        _run_agent_turn(user_input, deps, out, session)


def _run_agent_turn(user_input: str, deps: Deps, out: CliRenderer, session: dict[str, Any]) -> None:
    """Run the agent on the user's message and update the session with the outcome."""
    messages: list[Message] = session["messages"]
    turn_start = len(messages)  # Where this turn begins, so it can be undone if it fails.
    messages.append(Message.user(user_input))
    printer = EventPrinter(out)

    try:
        result = run_agent(messages, deps, session["mode"], session["depth"], printer)
    except KeyboardInterrupt:
        printer.close()
        del messages[turn_start:]  # Drop the half-finished turn so the history stays valid.
        out.console.print(f"  [{MUTED}]Stopped.[/{MUTED}]\n")
        return
    except Exception as err:
        printer.close()
        del messages[turn_start:]
        out.print_error(f"Inference error: {err}\n")
        return

    session["speed"] = printer.speed
    session["last_reply"] = result.final_text
    session["tokens"] += result.usage.total_tokens
    session["turns"] += 1
