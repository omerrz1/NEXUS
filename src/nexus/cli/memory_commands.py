"""Slash commands for the model's working memory: /memory, /todo, and /compact."""

from typing import Any

from rich.console import Console
from rich.markup import escape

from nexus.cli.session_commands import save_current
from nexus.cli.theme import CYAN, MUTED
from nexus.cli.todo_view import todo_progress, todo_text
from nexus.loop import Deps
from nexus.loop.budget import DEFAULT_SCALE, compact_now
from nexus.messages import Message
from nexus.session.memory import MAX_NOTE_CHARS, MAX_NOTES


def handle_memory(argument: str, context: dict[str, Any], console: Console) -> None:
    """Show this session's notes, or add or delete one: /memory [add <text> | forget <number>]."""
    deps: Deps = context["deps"]
    action, _, rest = argument.partition(" ")
    rest = rest.strip()
    match action.lower():
        case "":
            _show_notes(deps, console)
        case "add":
            _add_note(rest, deps, context, console)
        case "forget":
            _forget_note(rest, deps, context, console)
        case _:
            console.print(escape("Usage: /memory [add <text> | forget <number>]"))


def show_todo(context: dict[str, Any], console: Console) -> None:
    """Print the model's task list."""
    deps: Deps = context["deps"]
    if not deps.memory.todo:
        console.print(
            f"[{MUTED}]No task list yet. The model makes one for work with many steps.[/]"
        )
        return
    console.print(todo_text(deps.memory.todo))
    console.print(f"  [{MUTED}]{todo_progress(deps.memory.todo)}[/{MUTED}]\n")


def compact_conversation(context: dict[str, Any], console: Console) -> None:
    """Summarize the older part of the conversation now, to free up room."""
    deps: Deps = context["deps"]
    messages: list[Message] = context["messages"]
    try:
        with console.status("summarizing the older conversation…", spinner="dots"):
            result = compact_now(messages, deps)
    except KeyboardInterrupt:
        console.print(f"  [{MUTED}]Stopped.[/{MUTED}]")
        return
    except Exception as err:  # The model server can fail in many ways; the session goes on.
        console.print(f"[bold red]Could not summarize:[/bold red] {escape(str(err))}")
        return

    if result is None:
        console.print(f"[{MUTED}]Nothing old enough to summarize yet.[/{MUTED}]")
        return
    context["tokens"] = context.get("tokens", 0) + result.usage.total_tokens
    context["context_used"] = int(result.tokens_after * DEFAULT_SCALE)
    save_current(context, console)
    console.print(
        f"  [bold {CYAN}]✔[/bold {CYAN}] Summarized {result.replaced} older messages "
        f"[{MUTED}]({result.tokens_before:,} → {result.tokens_after:,} tokens)[/{MUTED}]"
    )


def _show_notes(deps: Deps, console: Console) -> None:
    if not deps.memory.notes:
        console.print(
            f"[{MUTED}]No notes yet. The model saves them as it works, "
            f"and you can add one with /memory add <text>.[/{MUTED}]"
        )
        return
    for number, note in enumerate(deps.memory.notes, start=1):
        console.print(f"  [{CYAN}]{number}.[/{CYAN}] {escape(note)}")
    console.print(f"[{MUTED}]Delete one with /memory forget <number>.[/{MUTED}]\n")


def _add_note(text: str, deps: Deps, context: dict[str, Any], console: Console) -> None:
    if not text:
        console.print("Usage: /memory add <text>")
    elif len(text) > MAX_NOTE_CHARS:
        console.print(f"That note is too long ({len(text)} of {MAX_NOTE_CHARS} characters).")
    elif deps.memory.notes_are_full():
        console.print(f"Memory is full ({MAX_NOTES} notes). Delete one with /memory forget.")
    else:
        number = deps.memory.add_note(text)
        save_current(context, console)
        console.print(f"  [bold {CYAN}]✔[/bold {CYAN}] Saved as note {number}.")


def _forget_note(text: str, deps: Deps, context: dict[str, Any], console: Console) -> None:
    if not text.isdigit():
        console.print("Usage: /memory forget <number>")
    elif deps.memory.remove_note(int(text)) is None:
        console.print(f"There is no note {text}. See /memory.")
    else:
        save_current(context, console)
        console.print(f"  [bold {CYAN}]✔[/bold {CYAN}] Deleted note {text}.")
