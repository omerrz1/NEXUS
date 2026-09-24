"""Keeping tool output small enough for a small model's context window."""

from nexus.tools.base import ToolContext


def cap_text(text: str, ctx: ToolContext, hint: str = "") -> tuple[str, bool]:
    """Cut `text` to the context's line and byte limits. Returns (text, was_cut).

    A footer tells the model the output was cut, and `hint` says how to get the rest.
    """
    lines = text.splitlines()
    was_cut = len(lines) > ctx.max_output_lines
    kept = "\n".join(lines[: ctx.max_output_lines])
    if len(kept.encode()) > ctx.max_output_bytes:
        kept = kept.encode()[: ctx.max_output_bytes].decode(errors="ignore")
        was_cut = True
    if not was_cut:
        return text, False

    reason = f"output cut at {ctx.max_output_lines} lines or {ctx.max_output_bytes} bytes"
    return f"{kept}\n[{reason}{'; ' + hint if hint else ''}]", True


def human_size(size: int) -> str:
    """Format a byte count for people: 512 B, 1.5 KB, 3.2 MB."""
    amount = float(size)
    for unit in ("B", "KB", "MB"):
        if amount < 1024:
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GB"
