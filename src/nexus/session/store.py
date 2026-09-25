"""Saves conversations to disk so a session can be listed, resumed, and deleted."""

import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nexus.messages import Message, Role
from nexus.session.memory import SessionMemory

SESSIONS_DIR = Path.home() / ".nexus" / "sessions"

_TITLE_LIMIT = 60
# Ids are made here (date, time, four random hex digits), so anything else is not one of ours.
_ID_PATTERN = re.compile(r"\d{8}-\d{6}-[0-9a-f]{4}")


@dataclass
class Session:
    """One conversation and the memory that goes with it.

    It is mutable on purpose: the loop extends `messages` in place, and the memory tools
    change `memory` while the session runs. `messages[0]` is the system prompt.
    """

    id: str
    workspace: str
    created_at: datetime
    updated_at: datetime
    messages: list[Message]
    memory: SessionMemory
    turns: int = 0
    title: str = ""

    @classmethod
    def start(cls, workspace: Path, system_prompt: str, memory: SessionMemory) -> "Session":
        """Begin an empty session in `workspace`."""
        now = datetime.now()
        return cls(
            id=f"{now:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}",
            workspace=str(workspace),
            created_at=now,
            updated_at=now,
            messages=[Message.system(system_prompt)],
            memory=memory,
        )

    def refresh_system_prompt(self, system_prompt: str) -> None:
        """Swap in a freshly built system prompt, so a resumed session sees today's date."""
        if self.messages and self.messages[0].role is Role.SYSTEM:
            self.messages[0] = Message.system(system_prompt)
        else:
            self.messages.insert(0, Message.system(system_prompt))


@dataclass(frozen=True)
class SessionInfo:
    """What a list of sessions shows about each one."""

    id: str
    title: str
    workspace: str
    updated_at: datetime
    turns: int


def make_title(text: str) -> str:
    """A short title from the user's first message: its first line, cut to fit."""
    lines = text.strip().splitlines()
    first_line = " ".join(lines[0].split()) if lines else ""
    if len(first_line) <= _TITLE_LIMIT:
        return first_line
    return first_line[: _TITLE_LIMIT - 1].rstrip() + "…"


class SessionStore:
    """Sessions saved as one JSON file each, in a folder only their owner can open."""

    def __init__(self, directory: Path = SESSIONS_DIR) -> None:
        self._directory = directory

    def save(self, session: Session) -> None:
        """Write the session. One that has not finished a turn yet is not worth keeping."""
        if session.turns == 0:
            return
        session.updated_at = datetime.now()
        data = {
            "id": session.id,
            "title": session.title,
            "workspace": session.workspace,
            "created_at": session.created_at.isoformat(),
            "updated_at": session.updated_at.isoformat(),
            "turns": session.turns,
            "memory": session.memory.to_data(),
            "messages": [message.to_dict() for message in session.messages],
        }
        self._directory.mkdir(parents=True, exist_ok=True)
        self._directory.chmod(0o700)
        target = self._directory / f"{session.id}.json"
        temporary = target.with_suffix(".tmp")
        _write_private(temporary, json.dumps(data))
        temporary.replace(target)  # Replacing is atomic, so a crash never leaves half a file.

    def load(self, session_id: str, memory: SessionMemory) -> Session | None:
        """Open a saved session, restoring its notes and todo list into `memory`.

        Returns None if there is no such session or its file cannot be read.
        """
        data = self._read(session_id)
        if data is None:
            return None
        try:
            session = Session(
                id=data["id"],
                workspace=data["workspace"],
                created_at=datetime.fromisoformat(data["created_at"]),
                updated_at=datetime.fromisoformat(data["updated_at"]),
                messages=[Message.from_dict(entry) for entry in data["messages"]],
                memory=memory,
                turns=int(data["turns"]),
                title=data["title"],
            )
        except (KeyError, TypeError, ValueError):
            return None
        memory.load(data.get("memory", {}))
        return session

    def list_sessions(self) -> list[SessionInfo]:
        """Every readable saved session, newest first."""
        sessions = []
        for path in self._directory.glob("*.json"):
            info = self._info(self._read(path.stem))
            if info is not None:
                sessions.append(info)
        return sorted(sessions, key=lambda info: info.updated_at, reverse=True)

    def find(self, reference: str) -> SessionInfo | None:
        """Look up a session by its number in the list (1 is the newest) or by its id.

        The start of an id is enough, as long as it matches only one session.
        """
        sessions = self.list_sessions()
        if reference.isdigit():
            position = int(reference)
            return sessions[position - 1] if 1 <= position <= len(sessions) else None
        matches = [info for info in sessions if info.id.startswith(reference)]
        return matches[0] if len(matches) == 1 and reference else None

    def latest_in(self, workspace: Path) -> SessionInfo | None:
        """The most recently used session that was started in `workspace`."""
        for info in self.list_sessions():
            if info.workspace == str(workspace):
                return info
        return None

    def delete(self, session_id: str) -> bool:
        """Remove a saved session. Returns False if there was nothing to remove."""
        if not _ID_PATTERN.fullmatch(session_id):
            return False
        try:
            (self._directory / f"{session_id}.json").unlink()
        except OSError:
            return False
        return True

    def _read(self, session_id: str) -> dict[str, Any] | None:
        """The parsed contents of one session file, or None if it is missing or damaged."""
        if not _ID_PATTERN.fullmatch(session_id):
            return None
        try:
            data = json.loads((self._directory / f"{session_id}.json").read_text("utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _info(data: dict[str, Any] | None) -> SessionInfo | None:
        if data is None:
            return None
        try:
            return SessionInfo(
                id=data["id"],
                title=data["title"],
                workspace=data["workspace"],
                updated_at=datetime.fromisoformat(data["updated_at"]),
                turns=int(data["turns"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _write_private(path: Path, text: str) -> None:
    """Write a file that only its owner can read: conversations can contain private data."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(text)
