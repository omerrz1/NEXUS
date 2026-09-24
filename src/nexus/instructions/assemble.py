"""Builds the system prompt the model receives at the start of every conversation."""

from importlib.resources import files
from pathlib import Path

from nexus.instructions.environment import environment_block

_PROMPTS = files("nexus.instructions") / "prompts"

# The layers, in order. The order is fixed so the prompt's start never changes mid-session.
_LAYERS = ("core", "tool_use", "working_rules")


def load_prompt(name: str) -> str:
    """Return the text of one shipped prompt file, such as "core"."""
    return (_PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()


def build_system_prompt(workspace: Path) -> str:
    """Return the system prompt: identity, tool rules, working rules, then the environment."""
    layers = [load_prompt(name) for name in _LAYERS]
    return "\n\n".join([*layers, environment_block(workspace)])
