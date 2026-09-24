"""Facts about the surroundings shown on the details card: server health and git branch."""

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from nexus.brain.openai_compat import is_loopback_url


@dataclass(frozen=True)
class ServerStatus:
    """Whether the model server answered, how fast, and whether it has the chosen model."""

    online: bool
    latency_ms: float = 0.0
    model_found: bool = False


def probe_server(
    base_url: str,
    model: str,
    timeout_sec: float = 1.5,
    client: httpx.Client | None = None,
) -> ServerStatus:
    """Ask the server which models it has. A down server is a status, never an exception."""
    if not is_loopback_url(base_url):
        return ServerStatus(online=False)  # Nexus never contacts a non-local address.

    started = time.perf_counter()
    try:
        response = (client or httpx).get(f"{base_url.rstrip('/')}/models", timeout=timeout_sec)
        response.raise_for_status()
        model_ids = [entry["id"] for entry in response.json()["data"]]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return ServerStatus(online=False)

    latency_ms = (time.perf_counter() - started) * 1000
    return ServerStatus(
        online=True, latency_ms=latency_ms, model_found=_has_model(model_ids, model)
    )


def _has_model(model_ids: list[str], model: str) -> bool:
    """Servers such as Ollama list "name:latest" for a model that is requested as "name"."""
    return any(model_id in (model, f"{model}:latest") for model_id in model_ids)


def current_git_branch(folder: Path) -> str | None:
    """Return the checked-out git branch of `folder`, or None if it is not a repo."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=folder,
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None  # Empty output means a detached HEAD.
