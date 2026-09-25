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
from nexus.cli.session_commands import (
    attach_session,
    open_session,
    print_resumed,
    save_current,
)
from nexus.cli.settings import SETTING_CHOICES, Settings, apply_setting, next_choice
from nexus.cli.slash import handle_slash_command
from nexus.cli.status import current_git_branch, probe_server
from nexus.cli.theme import MUTED, SKY
from nexus.loop import Deps, run_agent
from nexus.messages import Message
from nexus.session.store import Session, SessionStore, make_title


def run_repl(
    deps: Deps,
    settings: Settings,
    settings_path: Path | None = None,
    model_name: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    animate_banner: bool = True,
    console: Console | None = None,
    store: SessionStore | None = None,
    resume: str | None = None,
) -> None:
    """Show the banner, then read prompts and slash commands until the user exits.

    With a `store`, the conversation is saved after every turn. `resume` picks a saved
    session to continue: "" for the latest one in this folder, or a list number or id.
    """
    current, warning = open_session(deps, store, resume)
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
        "last_reply": "",
        "deps": deps,
        "store": store,
    }
    attach_session(session, current)

    _print_welcome(out, session, animate_banner)
    if warning:
        out.print_error(warning)
    if current.turns:
        print_resumed(current, deps.ctx.workspace, out.console)
    prompt = build_prompt_session(
        session,
        deps.tools.names,
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
    """Run the agent on the user's message, update the session, and save it."""
    current: Session = session["current"]
    messages = current.messages
    if not current.title:
        current.title = make_title(user_input)
    request = Message.user(user_input)
    messages.append(request)
    printer = EventPrinter(out, deps.memory)

    try:
        result = run_agent(messages, deps, session["mode"], session["depth"], printer)
    except KeyboardInterrupt:
        printer.close()
        _drop_turn(messages, request)  # So the history stays valid.
        out.console.print(f"  [{MUTED}]Stopped.[/{MUTED}]\n")
        return
    except Exception as err:
        printer.close()
        _drop_turn(messages, request)
        out.print_error(f"Inference error: {err}\n")
        return

    session["speed"] = printer.speed
    session["context_used"] = printer.context_tokens or session["context_used"]
    session["last_reply"] = result.final_text
    session["tokens"] += result.usage.total_tokens
    session["turns"] += 1
    current.turns = session["turns"]
    save_current(session, out.console)


def _drop_turn(messages: list[Message], request: Message) -> None:
    """Remove a turn that did not finish: the user's message and everything after it.

    The message is found by identity, not position, because summarizing during the turn
    may have shortened the list, and the user may have typed the same words before.
    """
    for index in range(len(messages) - 1, -1, -1):
        if messages[index] is request:
            del messages[index:]
            return
