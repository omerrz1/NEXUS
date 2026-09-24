"""Unit tests for token estimation."""

from nexus.brain.tokens import (
    estimate_conversation_tokens,
    estimate_message_tokens,
    estimate_tokens,
)
from nexus.messages import Message, ToolCall


def test_estimate_tokens_empty() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_basic_text() -> None:
    text = "Hello world, this is a test prompt for Nexus."
    count = estimate_tokens(text)
    assert count > 0
    assert count < len(text)


def test_estimate_message_tokens_with_tools() -> None:
    call = ToolCall(id="call_1", name="read_file", arguments={"path": "src/main.py"})
    msg = Message.assistant(content="Reading file now.", tool_calls=(call,))
    tokens = estimate_message_tokens(msg)
    assert tokens > estimate_tokens("Reading file now.")


def test_estimate_conversation_tokens() -> None:
    messages = [
        Message.system("System prompt"),
        Message.user("Hello!"),
        Message.assistant("Hi there!"),
    ]
    tokens = estimate_conversation_tokens(messages)
    assert tokens > 10
