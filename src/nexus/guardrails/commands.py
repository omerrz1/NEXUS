"""Rules for shell commands: which are always refused, and which are safe to run unasked.

These are string checks, not a sandbox. A determined command can get around them, so in
`ask` mode the person reading each command remains the real safety net.
"""

import os
import re
import shlex
from pathlib import Path

_PRIVILEGE = frozenset({"sudo", "su", "doas"})
_NETWORK = frozenset({"curl", "wget", "ssh", "scp", "sftp", "ftp", "telnet", "nc", "ncat", "rsync"})
_DESTRUCTIVE = frozenset({"mkfs", "shutdown", "reboot", "halt", "diskutil"})
_GIT_REMOTE = frozenset({"push", "pull", "fetch", "clone", "remote"})
_INSTALLERS = frozenset({"pip", "pip3", "npm", "yarn", "pnpm", "brew", "apt", "apt-get", "gem"})
_INSTALL_WORDS = frozenset({"install", "add", "update", "upgrade", "i"})
_WRAPPERS = frozenset({"env", "command", "nohup", "time", "exec", "nice", "builtin"})
_SHELLS = frozenset({"bash", "sh", "zsh"})

# Read-only programs that are safe to run without asking, when used on their own.
_SAFE_PROGRAMS = frozenset(
    {"ls", "pwd", "cat", "head", "tail", "wc", "grep", "rg", "find", "tree", "du", "df"}
    | {"file", "stat", "which", "whoami", "date", "uname", "echo", "sort", "uniq", "diff"}
    | {"cut", "basename", "dirname", "realpath", "id", "hostname"}
)
_SAFE_GIT = frozenset({"status", "diff", "log", "show"})
_FIND_UNSAFE = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fls"})
_OPERATOR_CHARS = frozenset(";&|()<>")
_MAX_NESTING = 3  # How deep "bash -c 'bash -c ...'" is followed.


def denied_reason(command: str, workspace: Path, _depth: int = 0) -> str | None:
    """Return why `command` must never run, or None if it may go on to the other checks."""
    try:
        segments = _split_segments(command)
    except ValueError:
        return "The command could not be understood (unbalanced quotes?). Rewrite it."

    for words in segments:
        words = _without_prefixes(words)
        if not words:
            continue
        reason = _denied_segment(words, workspace, _depth)
        if reason:
            return reason
    return None


def is_safe_command(command: str) -> bool:
    """Return True for a read-only command (or a pipe of them) that needs no approval."""
    if "`" in command or "$(" in command or "\n" in command:
        return False
    try:
        tokens = _tokens(command)
    except ValueError:
        return False
    if not tokens:
        return False

    segment: list[str] = []
    for token in [*tokens, "|"]:
        if not _is_operator(token):
            segment.append(token)
        elif token == "|" and _is_safe_segment(segment):
            segment = []
        else:
            return False  # Any other operator: ;  &&  >  <  &  (  )
    return True


def _tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return list(lexer)


def _is_operator(token: str) -> bool:
    return all(char in _OPERATOR_CHARS for char in token)


def _split_segments(command: str) -> list[list[str]]:
    """Split a command line into simple commands at ; && || | and similar operators."""
    segments: list[list[str]] = [[]]
    for token in _tokens(command):
        if _is_operator(token):
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _without_prefixes(words: list[str]) -> list[str]:
    """Skip VAR=value assignments and wrappers like `env` so the real program is first."""
    index = 0
    while index < len(words) and (
        re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[index]) or words[index] in _WRAPPERS
    ):
        index += 1
    return words[index:]


def _denied_segment(words: list[str], workspace: Path, depth: int) -> str | None:
    program = Path(words[0]).name
    rest = words[1:]
    if program in _PRIVILEGE:
        return f"'{program}' (privilege escalation) is not allowed."
    if program in _NETWORK:
        return f"'{program}' needs the network, which Nexus does not use."
    if program in _DESTRUCTIVE or program.startswith("mkfs"):
        return f"'{program}' is a destructive system command and is not allowed."
    if program in _INSTALLERS and _INSTALL_WORDS & set(rest):
        return f"'{program} install' needs the network, which Nexus does not use."
    if program == "git" and _git_subcommand(rest) in _GIT_REMOTE:
        return f"'git {_git_subcommand(rest)}' talks to a remote, which Nexus does not use."
    if program == "dd" and any(word.startswith("of=/dev/") for word in rest):
        return "Writing to a device with dd is not allowed."
    if program == "rm":
        return _denied_rm(rest, workspace)
    return _denied_nested(program, rest, workspace, depth)


def _git_subcommand(rest: list[str]) -> str:
    """The first word after git that is not an option, skipping the value of -C and -c."""
    skip_next = False
    for word in rest:
        if skip_next:
            skip_next = False
        elif word in ("-C", "-c"):
            skip_next = True
        elif not word.startswith("-"):
            return word
    return ""


def _is_recursive_flag(word: str) -> bool:
    """True for -r, -R, -rf, --recursive and similar."""
    if word == "--recursive":
        return True
    return word.startswith("-") and not word.startswith("--") and bool({"r", "R"} & set(word))


def _denied_rm(rest: list[str], workspace: Path) -> str | None:
    """Refuse recursive deletes of the filesystem root, the home folder, or the workspace."""
    if not any(_is_recursive_flag(word) for word in rest):
        return None

    home, workspace = Path.home().resolve(), workspace.resolve()
    for target in (word for word in rest if not word.startswith("-")):
        # "rm -rf ~/*" empties the folder just as "rm -rf ~" does, so judge the folder.
        folder = os.path.expandvars(target).removesuffix("/*")
        path = Path("." if folder == "*" else folder).expanduser()
        path = (path if path.is_absolute() else workspace / path).resolve()
        if path in (workspace, home) or path.parent == path:
            return f"Recursively deleting '{target}' is not allowed."
        if workspace.is_relative_to(path):
            return f"'{target}' contains the working directory, so deleting it is not allowed."
    return None


def _denied_nested(program: str, rest: list[str], workspace: Path, depth: int) -> str | None:
    """Look inside `bash -c '...'` and `eval '...'`, which hide a second command line."""
    if depth >= _MAX_NESTING:
        return None
    if program in _SHELLS and "-c" in rest[:-1]:
        return denied_reason(rest[rest.index("-c") + 1], workspace, depth + 1)
    if program == "eval":
        return denied_reason(" ".join(rest), workspace, depth + 1)
    return None


def _is_safe_segment(words: list[str]) -> bool:
    """One simple command is safe if it is a known read-only program used read-only."""
    if not words or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        return False
    program, rest = Path(words[0]).name, words[1:]
    if program == "git":
        return _git_subcommand(rest) in _SAFE_GIT
    if program == "find":
        return not _FIND_UNSAFE & set(rest)
    return program in _SAFE_PROGRAMS
