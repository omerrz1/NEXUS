"""Replaces the oldest part of a long conversation with a summary the model writes."""

import json
from dataclasses import dataclass

from nexus.brain.base import Brain, Depth
from nexus.brain.tokens import (
    estimate_conversation_tokens,
    estimate_message_tokens,
    estimate_tokens,
)
from nexus.instructions.assemble import load_prompt
from nexus.messages import Message, Role, ToolCall, Usage

SUMMARY_PREFIX = "[Summary of the earlier conversation]"
# Separates the model's summary from the notes and todo list, which are copied in unchanged.
_PINNED_MARKER = "\n\n[Kept exactly as written]\n"

_MESSAGE_CHARS = 1500  # Longest message quoted to the summarizer.
_TOOL_RESULT_CHARS = 300  # Tool output is mostly detail; a taste is enough for a summary.
_TOOL_ARGUMENT_CHARS = 150
_MAX_SUMMARY_CHARS = 3000


@dataclass(frozen=True)
class CompactionResult:
    """What one compaction did."""

    replaced: int  # Messages that were folded into the summary.
    tokens_before: int
    tokens_after: int
    usage: Usage  # What the summarizing itself cost.


def is_summary(message: Message) -> bool:
    """True for the message a compaction leaves behind."""
    return message.role is Role.USER and message.content.startswith(SUMMARY_PREFIX)


def plan_compaction(
    messages: list[Message], keep_tokens: int, request: Message | None = None
) -> int | None:
    """Choose where the part kept word for word starts, or None if nothing is old enough.

    `messages[1:cut]` is what would be summarized (`messages[0]` is the system prompt). The
    newest messages are kept, up to about `keep_tokens`, and the kept part never starts with
    a tool result, because that must stay next to the assistant message that asked for it.
    So the newest assistant message and the tool results after it are always kept.

    `request` is the message the current turn began with, if a turn is running. It does not
    count as something worth summarizing on its own, since `compact` keeps it word for word.
    """
    last = len(messages) - 1
    while last > 0 and messages[last].role is Role.TOOL:
        last -= 1
    cut = last
    kept = sum(estimate_message_tokens(message) for message in messages[last:])
    for index in range(last - 1, 0, -1):
        kept += estimate_message_tokens(messages[index])
        if kept > keep_tokens:
            break
        if messages[index].role is not Role.TOOL:
            cut = index

    worth_summarizing = [
        message for message in messages[1:cut] if not is_summary(message) and message is not request
    ]
    return cut if worth_summarizing else None


def compact(
    messages: list[Message],
    cut: int,
    brain: Brain,
    pinned: str = "",
    request: Message | None = None,
) -> CompactionResult | None:
    """Summarize `messages[1:cut]` and replace them with one summary message, in place.

    `pinned` (the todo list and notes) is copied into the summary unchanged, so it survives
    every compaction. If the current turn's `request` is among the folded messages, it is put
    back right after the summary, word for word, so the model always sees what was asked.
    Returns None, leaving the conversation as it was, if the model wrote no summary.
    """
    old = messages[1:cut]
    tokens_before = estimate_conversation_tokens(messages)
    summary, usage = _write_summary(old, brain)
    if not summary:
        return None

    replacement = [_summary_message(summary, pinned)]
    if request is not None and any(message is request for message in old):
        replacement.append(request)
    messages[1:cut] = replacement
    replaced = len(old) - (len(replacement) - 1)
    return CompactionResult(replaced, tokens_before, estimate_conversation_tokens(messages), usage)


def _write_summary(old: list[Message], brain: Brain) -> tuple[str, Usage]:
    """Fold the old messages into a summary, a window-sized block at a time.

    Each block is summarized together with the summary so far, so the old part can be
    larger than the context window and an earlier summary is carried forward, not stacked.
    """
    summary = ""
    lines = []
    for message in old:
        if is_summary(message):
            summary = _summary_text(message)
        else:
            lines.append(_transcript_line(message))

    usage = Usage.empty()
    for block in _blocks(lines, max_tokens=brain.context_window // 3):
        request = (
            f"Summary so far:\n{summary or '(nothing yet)'}\n\n"
            f"New part of the conversation:\n{block}\n\nWrite the updated summary."
        )
        reply = brain.chat(
            [Message.system(load_prompt("compaction")), Message.user(request)],
            depth=Depth.FAST,
        )
        usage = usage + reply.usage
        summary = reply.message.content.strip()[:_MAX_SUMMARY_CHARS]
        if not summary:
            break
    return summary, usage


def _blocks(lines: list[str], max_tokens: int) -> list[str]:
    """Group transcript lines into blocks that each fit in `max_tokens`."""
    blocks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        tokens = estimate_tokens(line)
        if current and size + tokens > max_tokens:
            blocks.append("\n".join(current))
            current, size = [], 0
        current.append(line)
        size += tokens
    if current:
        blocks.append("\n".join(current))
    return blocks


def _transcript_line(message: Message) -> str:
    """One message as a line of plain text for the summarizer."""
    match message.role:
        case Role.USER:
            return f"User: {_shorten(message.content, _MESSAGE_CHARS)}"
        case Role.ASSISTANT:
            calls = "".join(f" [called {_describe_call(call)}]" for call in message.tool_calls)
            return f"Assistant: {_shorten(message.content, _MESSAGE_CHARS)}{calls}".rstrip()
        case Role.TOOL:
            name = message.name or "a tool"
            return f"Result of {name}: {_shorten(message.content, _TOOL_RESULT_CHARS)}"
        case Role.SYSTEM:
            return message.content


def _describe_call(call: ToolCall) -> str:
    return f"{call.name} {_shorten(json.dumps(call.arguments), _TOOL_ARGUMENT_CHARS)}"


def _shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _summary_message(summary: str, pinned: str) -> Message:
    text = f"{SUMMARY_PREFIX}\n{summary}"
    if pinned:
        text += f"{_PINNED_MARKER}{pinned}"
    return Message.user(text)


def _summary_text(message: Message) -> str:
    """The model-written part of a summary message, without the pinned notes and todo list."""
    body = message.content.removeprefix(SUMMARY_PREFIX)
    return body.split(_PINNED_MARKER)[0].strip()
