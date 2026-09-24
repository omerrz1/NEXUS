"""Tests for shrinking old tool output to fit the context window."""

from nexus.brain.tokens import estimate_conversation_tokens
from nexus.context.manager import STUB_PREFIX, shrink_to_fit
from nexus.messages import Message


def conversation() -> list[Message]:
    return [
        Message.system("You are Nexus."),
        Message.user("Look at the files"),
        Message.tool("1", "old output " * 200, "read_file"),
        Message.tool("2", "newer output " * 200, "read_file"),
        Message.user("Thanks"),
    ]


def test_nothing_changes_when_the_conversation_already_fits() -> None:
    messages = conversation()
    before = list(messages)
    assert shrink_to_fit(messages, budget_tokens=100_000)
    assert messages == before


def test_oldest_tool_output_is_stubbed_first() -> None:
    messages = conversation()
    budget = estimate_conversation_tokens(messages) - 300  # Room for one stub, not two.
    assert shrink_to_fit(messages, budget)
    assert messages[2].content.startswith(STUB_PREFIX)
    assert messages[3].content.startswith("newer output")
    assert messages[2].tool_call_id == "1"  # The stub still answers the model's tool call.


def test_returns_false_when_only_the_conversation_itself_is_too_long() -> None:
    messages = conversation()
    assert not shrink_to_fit(messages, budget_tokens=10)
    assert all(m.content.startswith(STUB_PREFIX) for m in messages if m.role.value == "tool")
