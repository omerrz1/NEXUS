"""Unit tests for MockBrain."""

from nexus.brain.base import Brain, BrainReply
from nexus.brain.mock import MockBrain
from nexus.messages import Message, ToolCall, Usage


def test_mock_brain_implements_protocol() -> None:
    brain: Brain = MockBrain()
    assert brain.context_window == 16384


def test_mock_brain_queued_replies() -> None:
    brain = MockBrain()
    call = ToolCall(id="call_1", name="list_dir", arguments={"path": "."})
    brain.queue_reply(Message.assistant("Listing files", (call,)), tool_calls=(call,))

    deltas: list[str] = []
    reply = brain.chat([Message.user("List files")], on_delta=deltas.append)

    assert reply.message.content == "Listing files"
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].name == "list_dir"
    assert deltas == ["Listing files"]
    assert len(brain.calls) == 1


def test_mock_brain_responder() -> None:
    def responder(messages: list[Message]) -> BrainReply:
        last = messages[-1].content
        return BrainReply(
            message=Message.assistant(f"Echo: {last}"),
            tool_calls=(),
            usage=Usage.empty(),
        )

    brain = MockBrain(responder=responder)
    reply = brain.chat([Message.user("ping")])
    assert reply.message.content == "Echo: ping"
