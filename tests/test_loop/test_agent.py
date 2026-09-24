"""Full agent-loop runs against the mock brain, with scripted tool calls."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nexus.brain.base import BrainReply, Depth
from nexus.brain.mock import MockBrain
from nexus.guardrails.approval import Approval
from nexus.guardrails.modes import Mode
from nexus.loop import Event, HaltReason, RunResult, run_agent
from nexus.loop.agent import _answer_room, _next_scale
from nexus.loop.events import Halted, Notice, TextDelta, ToolStarted
from nexus.messages import Message, Role, ToolCall, Usage
from tests.helpers import ScriptedApprover, make_deps


def call(name: str, call_id: str = "c1", **arguments: object) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=dict(arguments))


def script(brain: MockBrain, *steps: str | ToolCall) -> None:
    """Queue replies: a string is a final answer, a ToolCall is a request to run a tool."""
    for step in steps:
        if isinstance(step, ToolCall):
            brain.queue_reply(Message.assistant("", (step,)), tool_calls=(step,))
        else:
            brain.queue_reply(Message.assistant(step))


def run(
    tmp_path: Path,
    brain: MockBrain,
    approver: ScriptedApprover | None = None,
    mode: Mode = Mode.ASK,
    max_steps: int = 40,
) -> tuple[list[Message], list[Event], RunResult]:
    deps = make_deps(tmp_path, brain, approver, max_steps)
    messages = [Message.system("system"), Message.user("do the thing")]
    events: list[Event] = []
    result = run_agent(messages, deps, mode, Depth.BALANCED, events.append)
    return messages, events, result


def tool_messages(messages: list[Message]) -> list[Message]:
    return [m for m in messages if m.role is Role.TOOL]


def test_a_plain_answer_ends_the_turn(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, "All done.")
    messages, events, result = run(tmp_path, brain)
    assert result.final_text == "All done." and result.halt is None
    assert messages[-1].content == "All done."
    assert any(isinstance(e, TextDelta) and e.text == "All done." for e in events)


def test_the_model_is_given_the_tool_specs(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, "hi")
    run(tmp_path, brain)
    _, specs = brain.calls[0]
    assert specs is not None and next(spec.name for spec in specs) == "read_file"


def test_tool_result_goes_back_to_the_model_then_it_answers(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("remember the milk")
    brain = MockBrain()
    script(brain, call("read_file", path="notes.txt"), "It says: remember the milk.")
    messages, events, result = run(tmp_path, brain)

    assert result.halt is None
    (tool_message,) = tool_messages(messages)
    assert "remember the milk" in tool_message.content and tool_message.tool_call_id == "c1"
    kinds = [type(e).__name__ for e in events if "Tool" in type(e).__name__]
    assert kinds == ["ToolRequested", "ToolStarted", "ToolFinished"]


def test_unknown_tool_and_bad_arguments_are_errors_the_model_can_read(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, call("teleport", "a"), call("read_file", "b", limit=-5), "ok")
    messages, _, result = run(tmp_path, brain)
    unknown, invalid = (m.content for m in tool_messages(messages))
    assert "Unknown tool 'teleport'" in unknown and "read_file" in unknown
    assert (
        "Invalid arguments for read_file" in invalid
        and "Expected: path (string, required)" in invalid
    )
    assert result.halt is None


def test_ask_mode_asks_before_writing_and_writes_when_approved(tmp_path: Path) -> None:
    approver = ScriptedApprover(Approval.ONCE)
    brain = MockBrain()
    script(brain, call("write_file", path="out.txt", content="data"), "written")
    run(tmp_path, brain, approver)
    assert (tmp_path / "out.txt").read_text() == "data"
    (name, preview, scope) = approver.requests[0]
    assert name == "write_file" and "Create" in (preview or "") and "working directory" in scope


def test_declined_action_does_not_run_and_the_model_is_told(tmp_path: Path) -> None:
    approver = ScriptedApprover(Approval.DENY)
    brain = MockBrain()
    script(brain, call("write_file", path="out.txt", content="data"), "ok, I will not")
    messages, events, _ = run(tmp_path, brain, approver)
    assert not (tmp_path / "out.txt").exists()
    assert "declined" in tool_messages(messages)[0].content
    assert not any(isinstance(e, ToolStarted) for e in events)


def test_read_only_mode_refuses_without_asking(tmp_path: Path) -> None:
    approver = ScriptedApprover()
    brain = MockBrain()
    script(brain, call("run_command", command="touch x"), "understood")
    messages, _, _ = run(tmp_path, brain, approver, mode=Mode.READ_ONLY)
    assert approver.requests == [] and not (tmp_path / "x").exists()
    assert "Not allowed" in tool_messages(messages)[0].content


def test_denylisted_command_is_refused_even_in_auto_mode(tmp_path: Path) -> None:
    approver = ScriptedApprover()
    brain = MockBrain()
    script(brain, call("run_command", command="curl http://example.com"), "ok")
    messages, _, _ = run(tmp_path, brain, approver, mode=Mode.AUTO)
    assert approver.requests == [] and "network" in tool_messages(messages)[0].content


def test_auto_mode_runs_commands_and_inside_writes_without_asking(tmp_path: Path) -> None:
    approver = ScriptedApprover()
    brain = MockBrain()
    script(
        brain,
        call("write_file", "a", path="f.txt", content="1"),
        call("run_command", "b", command="cat f.txt && echo done"),
        "fin",
    )
    messages, _, _ = run(tmp_path, brain, approver, mode=Mode.AUTO)
    assert approver.requests == [] and "done" in tool_messages(messages)[1].content


def test_safe_commands_run_without_asking_in_ask_mode(tmp_path: Path) -> None:
    approver = ScriptedApprover()
    brain = MockBrain()
    script(brain, call("run_command", command="ls"), "ok")
    run(tmp_path, brain, approver)
    assert approver.requests == []


def test_repeating_the_same_call_gets_a_warning_then_a_halt(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("same")
    brain = MockBrain()
    script(brain, *[call("read_file", f"c{n}", path="f.txt") for n in range(6)])
    messages, events, result = run(tmp_path, brain)
    assert result.halt is HaltReason.REPEATED_CALL
    assert "Try something different" in tool_messages(messages)[2].content
    assert isinstance(events[-1], Halted)


def test_a_streak_of_different_failures_halts(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, *[call(f"teleport{n}", f"c{n}") for n in range(10)])
    _, _, result = run(tmp_path, brain)
    assert result.halt is HaltReason.ERROR_STREAK


def test_the_step_limit_halts(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    brain = MockBrain()
    script(
        brain, *[call("read_file", f"c{n}", path="f.txt", offset=0, limit=n + 1) for n in range(10)]
    )
    _, _, result = run(tmp_path, brain, max_steps=3)
    assert result.halt is HaltReason.MAX_STEPS


def test_an_unreadable_tool_call_is_reported_back_to_the_model(tmp_path: Path) -> None:
    replies = iter(
        [
            BrainReply(Message.assistant("<tool_call>{oops"), (), Usage.empty(), ("bad JSON",)),
            BrainReply(Message.assistant("fixed"), (), Usage.empty()),
        ]
    )
    brain = MockBrain(responder=lambda messages: next(replies))
    messages, _, result = run(tmp_path, brain)
    feedback = [m for m in messages if m.role is Role.USER][-1]
    assert "could not be read" in feedback.content and "bad JSON" in feedback.content
    assert result.final_text == "fixed"


def test_old_tool_output_is_trimmed_when_the_window_is_small(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("\n".join("word " * 20 for _ in range(60)))
    # Room for two big results after the prompt, tool specs, and reply space, but not three.
    brain = MockBrain(context_window=3600)
    script(
        brain,
        call("read_file", "a", path="big.txt"),
        call("read_file", "b", path="big.txt", offset=1),
        call("read_file", "c", path="big.txt", offset=2),
        "done",
    )
    messages, _, result = run(tmp_path, brain)
    assert result.halt is None
    first, _, third = tool_messages(messages)
    assert "output omitted" in first.content and "word word" in third.content


def test_a_conversation_too_long_for_the_window_halts_cleanly(tmp_path: Path) -> None:
    brain = MockBrain(context_window=2000)
    messages = [Message.system("s"), Message.user("word " * 5000)]
    events: list[Event] = []
    result = run_agent(
        messages, make_deps(tmp_path, brain), Mode.ASK, Depth.BALANCED, events.append
    )
    halted = events[-1]
    assert result.halt is HaltReason.CONTEXT_FULL
    assert isinstance(halted, Halted) and "/new" in halted.message
    assert brain.calls == []  # The model is never called with a prompt that cannot fit.


def test_usage_is_added_up_across_steps(tmp_path: Path) -> None:
    (tmp_path / "f.txt").write_text("x")
    replies = iter(
        [
            BrainReply(
                Message.assistant("", (call("read_file", path="f.txt"),)),
                (call("read_file", path="f.txt"),),
                Usage(10, 5, 15),
            ),
            BrainReply(Message.assistant("done"), (), Usage(20, 5, 25)),
        ]
    )
    brain = MockBrain(responder=lambda messages: next(replies))
    _, _, result = run(tmp_path, brain)
    assert result.usage.total_tokens == 40


def test_events_cannot_be_changed_after_they_are_sent() -> None:
    event = TextDelta("hello")
    with pytest.raises(FrozenInstanceError):
        event.text = "changed"  # type: ignore[misc]


def test_a_cut_off_reply_never_runs_its_tool_calls(tmp_path: Path) -> None:
    write = call("write_file", path="half.txt", content="incomplete")
    reply = BrainReply(
        Message.assistant("Let me writ", (write,)), (write,), Usage(4000, 96, 4096), (), True
    )
    approver = ScriptedApprover()
    brain = MockBrain(responder=lambda messages: reply)
    messages, events, result = run(tmp_path, brain, approver, mode=Mode.AUTO)

    assert result.halt is HaltReason.REPLY_CUT_OFF and result.final_text == "Let me writ"
    assert not (tmp_path / "half.txt").exists() and approver.requests == []
    assert messages[-1].role is Role.ASSISTANT and messages[-1].tool_calls == ()
    halted = events[-1]
    assert isinstance(halted, Halted) and "cut off" in halted.message and "/new" in halted.message


def test_an_empty_reply_is_retried_once_without_thinking(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, "", "Here is the answer.")
    messages, events, result = run(tmp_path, brain)

    assert result.final_text == "Here is the answer." and result.halt is None
    assert brain.depths == [Depth.BALANCED, Depth.FAST]
    assert any(isinstance(e, Notice) for e in events)
    assert [m.role for m in messages[2:]] == [
        Role.USER,
        Role.ASSISTANT,
    ]  # no empty assistant message


def test_repeated_empty_replies_halt(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, "", "", "never reached")
    _, _, result = run(tmp_path, brain)
    assert result.halt is HaltReason.EMPTY_REPLY


def test_token_estimate_is_corrected_by_what_the_server_counted() -> None:
    assert _next_scale(1000, Usage(prompt_tokens=1400), current=1.3) == 1.4
    assert _next_scale(1000, Usage(), current=1.3) == 1.3  # no server count: keep the old value
    assert _next_scale(1000, Usage(prompt_tokens=90000), current=1.3) == 3.0  # clamped


def test_reply_room_is_larger_when_the_model_thinks() -> None:
    assert _answer_room(4096, Depth.FAST) == 512
    assert _answer_room(4096, Depth.BALANCED) == 1024
    assert _answer_room(32768, Depth.DEEP) == 8192


def test_trimming_starts_sooner_when_the_server_reports_more_tokens(tmp_path: Path) -> None:
    (tmp_path / "big.txt").write_text("\n".join("word " * 20 for _ in range(60)))
    read = call("read_file", path="big.txt")

    def replies(prompt_tokens: int) -> MockBrain:
        queue = iter(
            [
                BrainReply(
                    Message.assistant("", (read,)),
                    (read,),
                    Usage(prompt_tokens, 5, prompt_tokens + 5),
                ),
                BrainReply(Message.assistant("done"), (), Usage.empty()),
            ]
        )
        return MockBrain(context_window=3600, responder=lambda messages: next(queue))

    # Same conversation twice. The second server reports far more tokens than we estimate,
    # so the second model call must trim the tool output while the first need not.
    honest = run(tmp_path, replies(100))[0]
    inflated = run(tmp_path, replies(3000))[0]
    assert "output omitted" not in tool_messages(honest)[0].content
    assert "output omitted" in tool_messages(inflated)[0].content
