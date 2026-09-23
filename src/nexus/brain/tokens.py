"""Token estimation and accounting utilities for local context budgeting."""

from nexus.messages import Message, Usage


def estimate_tokens(text: str) -> int:
    """Estimate token count for a text string using character and word heuristics."""
    if not text:
        return 0
    # Rule of thumb for code and natural text in small LLM tokenizers: ~3.7 chars/token
    char_estimate = (len(text) + 3) // 4
    word_estimate = int(len(text.split()) * 1.3)
    return max(char_estimate, word_estimate, 1)


def estimate_message_tokens(message: Message) -> int:
    """Estimate token count for a single message including role framing overhead."""
    # Framing overhead per chat completion message is typically ~4 tokens
    tokens = 4 + estimate_tokens(message.content)
    if message.name:
        tokens += estimate_tokens(message.name) + 1
    if message.tool_call_id:
        tokens += estimate_tokens(message.tool_call_id) + 1
    for call in message.tool_calls:
        tokens += estimate_tokens(call.name) + 4
        for key, value in call.arguments.items():
            tokens += estimate_tokens(f"{key}: {value}")
    return tokens


def estimate_conversation_tokens(messages: list[Message]) -> int:
    """Estimate token count for a list of conversation messages."""
    total = sum(estimate_message_tokens(msg) for msg in messages)
    return total + 3  # Conversation framing overhead


class TokenTracker:
    """Tracks token consumption with local estimates corrected by server usage."""

    def __init__(self) -> None:
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Accumulated prompt tokens."""
        return self._prompt_tokens

    @property
    def completion_tokens(self) -> int:
        """Accumulated completion tokens."""
        return self._completion_tokens

    @property
    def total_tokens(self) -> int:
        """Total accumulated tokens."""
        return self._prompt_tokens + self._completion_tokens

    def record_usage(self, usage: Usage, fallback_messages: list[Message] | None = None) -> None:
        """Record usage from server response or fallback to local estimation."""
        if usage.prompt_tokens > 0 or usage.completion_tokens > 0:
            self._prompt_tokens += usage.prompt_tokens
            self._completion_tokens += usage.completion_tokens
            return
        if fallback_messages:
            self._prompt_tokens += estimate_conversation_tokens(fallback_messages)
