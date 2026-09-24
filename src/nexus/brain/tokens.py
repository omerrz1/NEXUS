"""Rough token estimates, used to keep the conversation inside the context window."""

from nexus.messages import Message


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
