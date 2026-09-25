"""The agent loop summarizing a long conversation so that it never has to stop."""

from pathlib import Path

from nexus.brain.base import BrainReply, Depth
from nexus.brain.mock import MockBrain
from nexus.brain.tokens import estimate_conversation_tokens
from nexus.context.compaction import is_summary
from nexus.guardrails.modes import Mode
from nexus.instructions.assemble import load_prompt
from nexus.loop import Event, HaltReason, RunResult, run_agent
from nexus.loop.budget import DEFAULT_SCALE, compact_now, prompt_budget, spec_tokens
from nexus.loop.events import Compacted, Halted, Notice
from nexus.messages import Message, Role, ToolCall, Usage
from tests.helpers import make_deps

WINDOW = 8000
SUMMARY_TEXT = "- earlier work, summarized"


def is_summary_request(messages: list[Message]) -> bool:
    return messages[0].content == load_prompt("compaction")


def summary_reply(text: str = SUMMARY_TEXT) -> BrainReply:
    return BrainReply(Message.assistant(text), (), Usage(7, 3, 10))


def history(pairs: int) -> list[Message]:
    """A system prompt and `pairs` question-and-answer turns, each about 400 tokens."""
    messages = [Message.system("system")]
    for number in range(pairs):
        messages += [Message.user(f"question {number} " + "word " * 300)]
        messages += [Message.assistant(f"answer {number} " + "word " * 300)]
    return messages


def run(
    tmp_path: Path, brain: MockBrain, messages: list[Message], memory_notes: tuple[str, ...] = ()
) -> tuple[list[Event], RunResult]:
    deps = make_deps(tmp_path, brain)
    for note in memory_notes:
        deps.memory.add_note(note)
    events: list[Event] = []
    result = run_agent(messages, deps, Mode.ASK, Depth.BALANCED, events.append)
    return events, result


def assert_history_is_valid(messages: list[Message]) -> None:
    """The rules a model server enforces: results follow their calls and nothing dangles."""
    assert messages[0].role is Role.SYSTEM
    waiting_for: set[str] = set()
    for message in messages[1:]:
        if message.role is Role.TOOL:
            assert message.tool_call_id in waiting_for, "a tool result without its call"
            waiting_for.discard(message.tool_call_id or "")
        else:
            assert not waiting_for, "a tool call whose result is missing"
            if message.role is Role.ASSISTANT:
                waiting_for = {call.id for call in message.tool_calls}
    assert not waiting_for


def answering_brain(final: str = "All done.") -> MockBrain:
    def respond(messages: list[Message]) -> BrainReply:
        if is_summary_request(messages):
            return summary_reply()
        return BrainReply(Message.assistant(final), (), Usage(20, 5, 25))

    return MockBrain(context_window=WINDOW, responder=respond)


def test_a_long_conversation_is_summarized_and_the_turn_carries_on(tmp_path: Path) -> None:
    brain = answering_brain()
    request = Message.user("what did we decide?")
    messages = [*history(12), request]
    old_length = len(messages)

    events, result = run(tmp_path, brain, messages)

    assert result.halt is None and result.final_text == "All done."
    compacted = [e for e in events if isinstance(e, Compacted)]
    assert len(compacted) == 1 and compacted[0].tokens_after < compacted[0].tokens_before
    assert any(isinstance(e, Notice) and "summarizing" in e.text for e in events)
    assert len(messages) < old_length
    assert is_summary(messages[1]) and SUMMARY_TEXT in messages[1].content
    assert any(m is request for m in messages)  # the user's request is never folded away
    assert_history_is_valid(messages)


def test_the_model_answers_from_a_prompt_that_fits_the_window(tmp_path: Path) -> None:
    brain = answering_brain()
    messages = [*history(12), Message.user("go on")]
    deps = make_deps(tmp_path, brain)
    run_agent(messages, deps, Mode.ASK, Depth.BALANCED, lambda event: None)

    sent, _ = brain.calls[-1]
    budget = prompt_budget(deps, Depth.BALANCED, spec_tokens(deps), DEFAULT_SCALE)
    assert estimate_conversation_tokens(sent) <= budget
    assert any(is_summary(message) for message in sent)


def test_the_cost_of_summarizing_is_counted_in_the_turn_usage(tmp_path: Path) -> None:
    brain = answering_brain()
    _, result = run(tmp_path, brain, [*history(12), Message.user("go on")])

    summary_calls = sum(is_summary_request(sent) for sent, _ in brain.calls)
    assert summary_calls >= 1  # a long history is summarized a block at a time
    assert result.usage.total_tokens == 10 * summary_calls + 25


def test_notes_and_todo_are_pinned_into_the_summary(tmp_path: Path) -> None:
    messages = [*history(12), Message.user("go on")]
    run(tmp_path, answering_brain(), messages, memory_notes=("The user prefers tabs",))
    assert "Session notes:\n1. The user prefers tabs" in messages[1].content


def test_a_short_conversation_is_never_summarized(tmp_path: Path) -> None:
    brain = answering_brain()
    events, _ = run(tmp_path, brain, [*history(2), Message.user("hi")])
    assert not any(isinstance(e, Compacted) for e in events)
    assert len(brain.calls) == 1  # just the answer


def test_when_no_summary_can_be_written_the_turn_stops_cleanly(tmp_path: Path) -> None:
    def respond(messages: list[Message]) -> BrainReply:
        return summary_reply("") if is_summary_request(messages) else summary_reply("answer")

    brain = MockBrain(context_window=WINDOW, responder=respond)
    messages = [*history(12), Message.user("go on")]
    before = list(messages)

    events, result = run(tmp_path, brain, messages)

    assert result.halt is HaltReason.CONTEXT_FULL
    assert isinstance(events[-1], Halted)
    assert messages == before  # nothing was lost
    assert all(is_summary_request(sent) for sent, _ in brain.calls)  # the answer was never asked


def test_summarizing_in_the_middle_of_a_tool_using_turn_keeps_the_history_valid(
    tmp_path: Path,
) -> None:
    (tmp_path / "a.txt").write_text("hello")
    steps = iter(
        [
            BrainReply(Message.assistant("thinking " * 350, (call,)), (call,), Usage.empty())
            for call in (
                ToolCall(f"c{n}", "read_file", {"path": "a.txt", "limit": n + 1}) for n in range(8)
            )
        ]
        + [BrainReply(Message.assistant("Finished."), (), Usage.empty())]
    )

    def respond(messages: list[Message]) -> BrainReply:
        return summary_reply() if is_summary_request(messages) else next(steps)

    request = Message.user("read the file a lot")
    messages = [Message.system("system"), request]
    events, result = run(tmp_path, MockBrain(context_window=WINDOW, responder=respond), messages)

    assert result.halt is None and result.final_text == "Finished."
    assert any(isinstance(e, Compacted) for e in events)
    assert any(m is request for m in messages)
    assert_history_is_valid(messages)


def test_compacting_by_hand_summarizes_the_older_part(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, answering_brain())
    messages = [*history(12), Message.user("latest question")]
    result = compact_now(messages, deps)
    assert result is not None and result.replaced > 0
    assert is_summary(messages[1]) and messages[-1] == Message.user("latest question")
    assert compact_now(messages, deps) is None  # only the summary is left, so nothing to do


def test_the_memory_tools_work_through_the_loop(tmp_path: Path) -> None:
    replies = iter(
        [
            _tool_reply("update_todo", items=[{"text": "step one", "status": "in_progress"}]),
            _tool_reply("remember", note="the user's name is Sam"),
            BrainReply(Message.assistant("Noted."), (), Usage.empty()),
        ]
    )
    deps = make_deps(tmp_path, MockBrain(responder=lambda messages: next(replies)))
    messages = [Message.system("system"), Message.user("plan it and remember me")]
    result = run_agent(messages, deps, Mode.READ_ONLY, Depth.BALANCED, lambda event: None)

    assert result.halt is None
    assert [item.text for item in deps.memory.todo] == ["step one"]
    assert deps.memory.notes == ["the user's name is Sam"]  # even in read-only mode


def _tool_reply(name: str, **arguments: object) -> BrainReply:
    call = ToolCall(f"call-{name}", name, dict(arguments))
    return BrainReply(Message.assistant("", (call,)), (call,), Usage.empty())
