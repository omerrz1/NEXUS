"""Slash commands that manage sessions: /new, /sessions, /resume, /rename, and /delete."""

from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from nexus.brain.tokens import estimate_conversation_tokens
from nexus.cli.picker import Choice, pick
from nexus.cli.theme import CYAN, MUTED, SKY
from nexus.context.compaction import is_summary
from nexus.instructions.assemble import build_system_prompt
from nexus.loop import Deps
from nexus.loop.budget import DEFAULT_SCALE, spec_tokens
from nexus.messages import Message, Role
from nexus.session.store import Session, SessionInfo, SessionStore, make_title

_PICKER_LIMIT = 10  # More rows than this would not fit on a small terminal.
_PREVIEW_CHARS = 160


def open_session(
    deps: Deps, store: SessionStore | None, resume: str | None
) -> tuple[Session, str | None]:
    """Begin the session the REPL starts with, and a warning if the one asked for is missing.

    `resume` is None for a fresh session, "" for the latest one started in this folder, or
    a list number or id.
    """
    if resume is None or store is None:
        return _fresh_session(deps), None
    info = store.find(resume) if resume else store.latest_in(deps.ctx.workspace)
    if info is None:
        missing = f"No saved session matches '{resume}'" if resume else "No earlier session here"
        return _fresh_session(deps), f"{missing}; starting a new one."
    session = _load_session(deps, store, info)
    if session is None:
        return _fresh_session(deps), f"Could not read '{info.title}'; starting a new one."
    return session, None


def attach_session(context: dict[str, Any], session: Session) -> None:
    """Make `session` the one the REPL works on, and reset the per-session counters."""
    context.update(current=session, messages=session.messages)
    context.update(tokens=0, turns=session.turns, speed=0.0, last_reply="")
    context["context_used"] = estimate_context_use(session.messages, context.get("deps"))


def estimate_context_use(messages: list[Message], deps: Deps | None) -> int:
    """A guess at how many tokens these messages and the tool specs take in the model's window.

    Only used until the server reports the real number with the next reply.
    """
    tokens = estimate_conversation_tokens(messages)
    if deps is not None:
        tokens += spec_tokens(deps)
    return int(tokens * DEFAULT_SCALE)


def save_current(context: dict[str, Any], console: Console) -> None:
    """Save the current session, if sessions are being saved. A failure is reported, not fatal."""
    store: SessionStore | None = context.get("store")
    if store is None:
        return
    try:
        store.save(context["current"])
    except OSError as err:
        console.print(f"[bold red]Could not save the session:[/bold red] {escape(str(err))}")


def print_resumed(session: Session, workspace: Path, console: Console) -> None:
    """Say which session was opened, and remind the user where the conversation left off."""
    console.print(
        f"  [bold {CYAN}]✔[/bold {CYAN}] Resumed [bold]{escape(session.title)}[/bold] "
        f"[{MUTED}]· {session.turns} turns · last used {_ago(session.updated_at)}[/{MUTED}]"
    )
    if session.workspace != str(workspace):
        console.print(
            f"  [{MUTED}]It was started in {escape(_short_folder(session.workspace))}, "
            f"and you are in {escape(_short_folder(str(workspace)))}.[/{MUTED}]"
        )
    request, reply = _last_exchange(session)
    if request:
        console.print(f"  [{MUTED}]you:   {escape(request)}[/{MUTED}]")
    if reply:
        console.print(f"  [{MUTED}]nexus: {escape(reply)}[/{MUTED}]")
    console.print()


def start_new_session(context: dict[str, Any], console: Console) -> None:
    """Save the current session and begin an empty one."""
    save_current(context, console)
    attach_session(context, _fresh_session(context["deps"]))
    console.print(
        f"  [bold {CYAN}]✔[/bold {CYAN}] Started a new session. "
        f"[{MUTED}]Earlier ones are kept: see /sessions.[/{MUTED}]"
    )


def show_sessions(context: dict[str, Any], console: Console) -> None:
    """List every saved session, newest first, marking the one in use."""
    store = _store(context, console)
    if store is None:
        return
    sessions = store.list_sessions()
    if not sessions:
        console.print(
            f"[{MUTED}]No saved sessions yet. A session is saved after its first turn.[/]"
        )
        return

    table = Table(
        title=f"[bold {SKY}]SAVED SESSIONS[/bold {SKY}]",
        border_style="#0077b6",
        header_style=f"bold {SKY}",
    )
    table.add_column("#", justify="right")
    table.add_column("Title", style="white", overflow="ellipsis", max_width=44)
    table.add_column("Folder", style=MUTED, overflow="ellipsis", max_width=28)
    table.add_column("Turns", justify="right")
    table.add_column("Last used", style=MUTED)
    current_id = context["current"].id
    for number, info in enumerate(sessions, start=1):
        marker = f"[bold {CYAN}]●[/bold {CYAN}] " if info.id == current_id else ""
        table.add_row(
            str(number),
            marker + escape(info.title or "(untitled)"),
            escape(_short_folder(info.workspace)),
            str(info.turns),
            _ago(info.updated_at),
        )
    console.print(table)
    console.print(f"[{MUTED}]Continue one with /resume <number>.[/{MUTED}]\n")


def resume_session(argument: str, context: dict[str, Any], console: Console) -> None:
    """Switch to a saved session, chosen by number or id, or from a menu if none is given."""
    store = _store(context, console)
    if store is None:
        return
    info = store.find(argument) if argument else _choose(store, "Resume which session?", console)
    if info is None:
        if argument:
            console.print(f"No saved session matches '{escape(argument)}'. See /sessions.")
        return
    if info.id == context["current"].id:
        console.print(f"[{MUTED}]You are already in that session.[/{MUTED}]")
        return

    # The current session is saved first: loading the other one replaces the shared memory.
    save_current(context, console)
    deps: Deps = context["deps"]
    session = _load_session(deps, store, info)
    if session is None:
        console.print(f"[bold red]Could not read the session[/bold red] '{escape(info.title)}'.")
        return
    attach_session(context, session)
    print_resumed(session, deps.ctx.workspace, console)


def rename_session(argument: str, context: dict[str, Any], console: Console) -> None:
    """Give the current session a new title."""
    if not argument:
        console.print("Usage: /rename <new title>")
        return
    session: Session = context["current"]
    session.title = make_title(argument)
    save_current(context, console)
    console.print(
        f"  [bold {CYAN}]✔[/bold {CYAN}] Renamed to [bold]{escape(session.title)}[/bold]."
    )


def delete_session(argument: str, context: dict[str, Any], console: Console) -> None:
    """Delete a saved session, chosen by number or id, or from a menu if none is given."""
    store = _store(context, console)
    if store is None:
        return
    info = store.find(argument) if argument else _choose(store, "Delete which session?", console)
    if info is None:
        if argument:
            console.print(f"No saved session matches '{escape(argument)}'. See /sessions.")
        return
    if info.id == context["current"].id:
        console.print("That is the session you are in. Start another with /new, then delete it.")
        return
    if store.delete(info.id):
        console.print(f"  [bold {CYAN}]✔[/bold {CYAN}] Deleted [bold]{escape(info.title)}[/bold].")
    else:
        console.print("[bold red]Could not delete that session.[/bold red]")


def _fresh_session(deps: Deps) -> Session:
    deps.memory.clear()
    return Session.start(deps.ctx.workspace, build_system_prompt(deps.ctx.workspace), deps.memory)


def _load_session(deps: Deps, store: SessionStore, info: SessionInfo) -> Session | None:
    """Open a saved session with a fresh system prompt, so it sees today's date and folder."""
    session = store.load(info.id, deps.memory)
    if session is not None:
        session.refresh_system_prompt(build_system_prompt(deps.ctx.workspace))
    return session


def _store(context: dict[str, Any], console: Console) -> SessionStore | None:
    store: SessionStore | None = context.get("store")
    if store is None:
        console.print(f"[{MUTED}]Sessions are not being saved in this run.[/{MUTED}]")
    return store


def _choose(store: SessionStore, title: str, console: Console) -> SessionInfo | None:
    """Let the user pick one of the most recent sessions from a menu."""
    sessions = store.list_sessions()
    if not sessions:
        console.print(f"[{MUTED}]No saved sessions yet.[/{MUTED}]")
        return None
    choices = [
        Choice(
            info,
            info.title or "(untitled)",
            f"{_short_folder(info.workspace)} · {_ago(info.updated_at)}",
        )
        for info in sessions[:_PICKER_LIMIT]
    ]
    return pick(title, choices)


def _last_exchange(session: Session) -> tuple[str, str]:
    """The user's latest request and the model's latest reply, shortened for a preview."""
    request = reply = ""
    for message in reversed(session.messages):
        if not reply and message.role is Role.ASSISTANT and message.content.strip():
            reply = _preview(message.content)
        elif not request and message.role is Role.USER and not is_summary(message):
            request = _preview(message.content)
        if request and reply:
            break
    return request, reply


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _PREVIEW_CHARS else flat[: _PREVIEW_CHARS - 1] + "…"


def _short_folder(folder: str, limit: int = 28) -> str:
    """A folder with the home directory written as ~, and long ones cut at the front.

    The last folders are what tell two projects apart, so those are the ones kept.
    """
    home = str(Path.home())
    shown = "~" + folder[len(home) :] if folder.startswith(home) else folder
    if len(shown) <= limit:
        return shown
    tail = "/".join(shown.split("/")[-2:])
    return "…/" + tail if len(tail) < limit else "…" + shown[-(limit - 1) :]


def _ago(when: datetime) -> str:
    seconds = (datetime.now() - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    if seconds < 7 * 86400:
        return f"{int(seconds // 86400)} d ago"
    return when.strftime("%Y-%m-%d")
