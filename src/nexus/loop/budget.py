"""Keeps the prompt inside the context window: sizing it, trimming old output, summarizing."""

import json

from nexus.brain.base import Depth
from nexus.brain.tokens import estimate_tokens
from nexus.context.compaction import CompactionResult, compact, plan_compaction
from nexus.context.manager import shrink_to_fit
from nexus.loop.deps import Deps
from nexus.loop.events import Compacted, EventHandler, Notice
from nexus.messages import Message, Usage

# Local token estimates run low for code and markdown (about 3 characters per token, not 4),
# so start out cautious and correct from the server's real counts after the first reply.
DEFAULT_SCALE = 1.3

# Above this share of the budget, old tool output is trimmed and then old turns are summarized.
COMPACT_AT = 0.7
# After a summary, the newest messages worth this share of the budget stay word for word.
KEEP_RECENT = 0.3


def spec_tokens(deps: Deps) -> int:
    """Estimated tokens the tool specs add to every request."""
    return estimate_tokens(json.dumps([spec.to_dict() for spec in deps.tools.specs()]))


def answer_room(window: int, depth: Depth) -> int:
    """Tokens kept free for the reply. Thinking happens in the same window as the answer."""
    if depth is Depth.FAST:
        return max(512, window // 8)
    return max(1024, window // 4)


def next_scale(estimated: int, usage: Usage, current: float) -> float:
    """Correct the local estimate using the prompt size the server actually counted."""
    if usage.prompt_tokens <= 0 or estimated <= 0:
        return current
    return min(max(usage.prompt_tokens / estimated, 0.5), 3.0)


def prompt_budget(deps: Deps, depth: Depth, tool_spec_tokens: int, scale: float) -> int:
    """How many estimated tokens the messages may take, leaving room for specs and the reply."""
    window = deps.brain.context_window
    # Estimates are multiplied by `scale` to get real tokens, so divide the budget by it.
    return int((window - answer_room(window, depth)) / scale - tool_spec_tokens)


def make_room(
    messages: list[Message],
    deps: Deps,
    depth: Depth,
    tool_spec_tokens: int,
    scale: float,
    request: Message,
    on_event: EventHandler,
) -> tuple[bool, Usage]:
    """Get the messages under the budget. Returns whether they fit, and what summarizing cost.

    Cheapest first: shorten old tool output, and only if that is not enough, have the model
    summarize the oldest turns. Either way the newest messages, starting from the user's
    `request`, stay word for word.
    """
    budget = prompt_budget(deps, depth, tool_spec_tokens, scale)
    if shrink_to_fit(messages, int(budget * COMPACT_AT)):
        return True, Usage.empty()

    cut = plan_compaction(messages, int(budget * KEEP_RECENT), request)
    spent = Usage.empty()
    if cut is not None:
        on_event(Notice("The conversation is getting long; summarizing the older part."))
        result = compact(messages, cut, deps.brain, deps.memory.render(), request)
        if result is not None:
            on_event(Compacted(result.replaced, result.tokens_before, result.tokens_after))
            spent = result.usage
    return shrink_to_fit(messages, budget), spent


def compact_now(messages: list[Message], deps: Deps) -> CompactionResult | None:
    """Summarize the older part of the conversation on request (the /compact command).

    Returns None when there is nothing old enough to summarize, or the model wrote no summary.
    """
    budget = prompt_budget(deps, Depth.BALANCED, spec_tokens(deps), DEFAULT_SCALE)
    cut = plan_compaction(messages, keep_tokens=int(budget * KEEP_RECENT))
    if cut is None:
        return None
    return compact(messages, cut, deps.brain, deps.memory.render())
