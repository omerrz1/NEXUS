"""Interactive tab-completion for slash commands, tool names, and workspace file paths."""

import os
from pathlib import Path
import readline

NEXUS_COMMANDS: tuple[str, ...] = (
    "/help",
    "/clear",
    "/doctor",
    "/model",
    "/tokens",
    "/stats",
    "/thoughts",
    "/tools",
    "/tool",
    "/copy",
    "/save",
    "/export",
    "/mode",
    "/undo",
    "/exit",
    "/quit",
)

BUILTIN_TOOLS: tuple[tuple[str, str, str], ...] = (
    ("read_file", "read", "Read a text file with numbered lines and paging"),
    ("list_dir", "read", "List directory contents (shallow by default)"),
    ("find_files", "read", "Find files matching a glob pattern"),
    ("search_text", "read", "Search file contents for regex or text patterns"),
    ("write_file", "write", "Create a new file or fully overwrite an existing one"),
    ("edit_file", "write", "Exact-match string replacement with unified diff"),
    ("run_command", "exec", "Run a shell command inside workspace with timeout"),
    ("update_todo", "none", "Maintain external scratchpad task list memory"),
)

TOOL_NAMES: tuple[str, ...] = tuple(t[0] for t in BUILTIN_TOOLS)

_HISTORY_PATH = Path.home() / ".nexus" / "history"


class NexusCompleter:
    """Readline completer for slash commands, tools, and workspace paths."""

    def __init__(self, workspace: Path | None = None) -> None:
        self.workspace = workspace or Path.cwd()

    def complete(self, text: str, state: int) -> str | None:
        """Return the next autocompletion match for the current input buffer."""
        line = readline.get_line_buffer()
        matches = self._get_matches(line, text)
        return matches[state] if state < len(matches) else None

    def _get_matches(self, line: str, text: str) -> list[str]:
        """Compute candidate matches based on line context."""
        stripped = line.lstrip()

        # Context 1: Tool arguments after /tool or /call
        if stripped.startswith(("/tool ", "/call ")):
            prefix = line.split(maxsplit=1)[1] if " " in line else ""
            return [t for t in TOOL_NAMES if t.startswith(prefix)]

        # Context 2: Slash command completion
        if stripped.startswith("/") and " " not in stripped:
            return [c for c in NEXUS_COMMANDS if c.startswith(stripped)]

        # Context 3: Explicit tool tag completion (@tool_name or tool:)
        if text.startswith("@"):
            query = text[1:]
            tool_matches = [f"@{t}" for t in TOOL_NAMES if t.startswith(query)]
            file_matches = [f"@{p}" for p in self._complete_paths(query)]
            return tool_matches + file_matches

        # Context 4: Workspace path completion for any path-like argument
        if "/" in text or (text and not text.startswith("-")):
            path_matches = self._complete_paths(text)
            if path_matches:
                return path_matches

        # Context 5: General tool name completion
        return [t for t in TOOL_NAMES if t.startswith(text)]

    def _complete_paths(self, prefix: str) -> list[str]:
        """Complete relative file and directory paths in the workspace."""
        try:
            target = self.workspace / prefix
            parent = target.parent if not prefix.endswith("/") else target
            search_prefix = target.name if not prefix.endswith("/") else ""

            if not parent.exists() or not parent.is_dir():
                return []

            matches: list[str] = []
            for item in parent.iterdir():
                if item.name.startswith(".") and not search_prefix.startswith("."):
                    continue
                if item.name.startswith(search_prefix):
                    rel = item.relative_to(self.workspace)
                    path_str = str(rel) + ("/" if item.is_dir() else "")
                    matches.append(path_str)
            return sorted(matches)
        except Exception:
            return []


def setup_readline(workspace: Path | None = None) -> None:
    """Initialize readline with tab-completion and persistent history."""
    completer = NexusCompleter(workspace)
    readline.set_completer(completer.complete)

    # Configure tab key for completion on macOS libedit and GNU readline
    readline.parse_and_bind("bind ^I rl_complete")
    readline.parse_and_bind("tab: complete")
    readline.set_completer_delims(" \t\n`!#$%^&*()=+[{]}\\|;:'\",<>?")

    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _HISTORY_PATH.exists():
            readline.read_history_file(str(_HISTORY_PATH))
    except Exception:
        pass


def save_readline_history(max_entries: int = 1000) -> None:
    """Save the current readline history to the persistent history file."""
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        readline.set_history_length(max_entries)
        readline.write_history_file(str(_HISTORY_PATH))
    except Exception:
        pass
