"""Makes a conversation fit the model's context window by shrinking old tool output."""

from dataclasses import replace

from nexus.brain.tokens import estimate_message_tokens
from nexus.messages import Message, Role

STUB_PREFIX = "[output omitted to save space"


def shrink_to_fit(messages: list[Message], budget_tokens: int) -> bool:
    """Replace the oldest tool outputs with one-line stubs until `messages` fit the budget.

    Tool output is usually most of the tokens and the least useful once it has been
    acted on. The list is changed in place. Returns False if it still does not fit, which
    means the conversation itself is too long.
    """
    total = sum(estimate_message_tokens(message) for message in messages)
    for index, message in enumerate(messages):
        if total <= budget_tokens:
            return True
        if message.role is not Role.TOOL or message.content.startswith(STUB_PREFIX):
            continue
        stub = replace(message, content=f"{STUB_PREFIX}: {len(message.content)} characters]")
        total += estimate_message_tokens(stub) - estimate_message_tokens(message)
        messages[index] = stub
    return total <= budget_tokens
