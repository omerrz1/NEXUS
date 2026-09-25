"""The agent loop making a tool and using it, all in one turn."""

from pathlib import Path
from typing import Any

import pytest

from nexus.brain.base import BrainReply, Depth
from nexus.brain.mock import MockBrain
from nexus.guardrails.approval import Approval
from nexus.guardrails.modes import Mode
from nexus.loop import Event, HaltReason, RunResult, run_agent
from nexus.loop.events import ToolStarted
from nexus.messages import Message, Role, ToolCall, Usage
from tests.helpers import ScriptedApprover, make_deps

CODE = "import json, sys\nprint(len(json.load(sys.stdin)['text'].split()))\n"


def call(tool_name: str, call_id: str, /, **arguments: Any) -> ToolCall:
    """A tool call. The first two arguments are positional so a tool may have an input `name`."""
    return ToolCall(call_id, tool_name, arguments)


def create_word_count(call_id: str = "c1") -> ToolCall:
    return call(
        "create_tool",
        call_id,
        name="word_count",
        description="Count the words in some text.",
        parameters={"text": "the text to count"},
        code=CODE,
    )


def script(brain: MockBrain, *steps: str | ToolCall) -> None:
    for step in steps:
        if isinstance(step, ToolCall):
            brain.queue_reply(Message.assistant("", (step,)), tool_calls=(step,))
        else:
            brain.queue_reply(Message.assistant(step))


def run(
    tmp_path: Path, brain: MockBrain, approver: ScriptedApprover, mode: Mode = Mode.ASK
) -> tuple[list[Message], list[Event], RunResult]:
    deps = make_deps(tmp_path, brain, approver)
    messages = [Message.system("system"), Message.user("count the words in my note")]
    events: list[Event] = []
    result = run_agent(messages, deps, mode, Depth.BALANCED, events.append)
    return messages, events, result


def tool_results(messages: list[Message]) -> list[str]:
    return [m.content for m in messages if m.role is Role.TOOL]


def test_the_model_makes_a_tool_and_uses_it_in_the_same_turn(tmp_path: Path) -> None:
    brain = MockBrain()
    script(
        brain,
        create_word_count(),
        call("word_count", "c2", text="the quick brown fox"),
        "The note has 4 words.",
    )
    approver = ScriptedApprover(Approval.ONCE)

    messages, _, result = run(tmp_path, brain, approver)

    assert result.halt is None and result.final_text == "The note has 4 words."
    created, counted = tool_results(messages)
    assert "Created the tool word_count" in created and counted == "4"
    # The user was asked twice: about making the tool, and about running it.
    assert [request[0] for request in approver.requests] == ["create_tool", "word_count"]


def test_the_new_tool_is_offered_to_the_model_from_the_very_next_step(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, create_word_count(), "done")
    run(tmp_path, brain, ScriptedApprover())

    offered_before = [spec.name for spec in brain.calls[0][1] or []]
    offered_after = [spec.name for spec in brain.calls[1][1] or []]
    assert "word_count" not in offered_before and "word_count" in offered_after


def test_the_size_of_the_tool_specs_is_recounted_every_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    counted: list[int] = []

    def counting(deps: Any) -> int:
        counted.append(len(deps.tools))
        return 100

    monkeypatch.setattr("nexus.loop.agent.spec_tokens", counting)
    brain = MockBrain()
    script(brain, create_word_count(), "done")
    run(tmp_path, brain, ScriptedApprover())
    assert len(counted) == 2 and counted[1] == counted[0] + 1  # a tool appeared between steps


def test_in_auto_mode_making_a_tool_still_asks_but_using_it_does_not(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, create_word_count(), call("word_count", "c2", text="a b"), "ok")
    approver = ScriptedApprover(Approval.ONCE)

    messages, _, _ = run(tmp_path, brain, approver, mode=Mode.AUTO)

    assert [request[0] for request in approver.requests] == ["create_tool"]
    assert tool_results(messages)[1] == "2"


def test_declining_means_no_tool_is_made_and_the_model_is_told(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, create_word_count(), call("word_count", "c2", text="a b"), "I could not.")
    approver = ScriptedApprover(Approval.DENY, instead="just use wc -w with run_command")

    messages, events, _ = run(tmp_path, brain, approver)

    declined, unknown = tool_results(messages)
    assert 'said: "just use wc -w with run_command"' in declined
    assert "Unknown tool 'word_count'" in unknown
    assert not any(isinstance(e, ToolStarted) and e.call.name == "create_tool" for e in events)


def test_read_only_mode_refuses_to_make_a_tool_without_asking(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, create_word_count(), "ok")
    approver = ScriptedApprover()
    messages, _, _ = run(tmp_path, brain, approver, mode=Mode.READ_ONLY)
    assert approver.requests == [] and "read-only" in tool_results(messages)[0]


def test_a_script_with_a_typo_is_rejected_before_the_user_is_asked(tmp_path: Path) -> None:
    brain = MockBrain()
    bad = call("create_tool", "c1", name="word_count", description="Counts.", code="print('oops")
    script(brain, bad, "ok")
    approver = ScriptedApprover()
    messages, _, _ = run(tmp_path, brain, approver)
    assert approver.requests == []
    assert "syntax error on line 1" in tool_results(messages)[0]


def test_a_tool_that_fails_when_run_gives_the_model_the_error_to_fix(tmp_path: Path) -> None:
    brain = MockBrain()
    broken = call(
        "create_tool",
        "c1",
        name="broken_tool",
        description="Always fails.",
        code="import json, sys\njson.load(sys.stdin)['missing']\n",
    )
    script(brain, broken, call("broken_tool", "c2"), "I will fix it.")
    messages, _, result = run(tmp_path, brain, ScriptedApprover())
    failure = tool_results(messages)[1]
    assert result.halt is None and failure.startswith("Error: The tool failed (exit code 1)")
    assert "KeyError" in failure


def test_tools_made_in_one_run_are_there_in_the_next(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, create_word_count(), "done")
    run(tmp_path, brain, ScriptedApprover())

    from nexus.tools.custom.library import ToolLibrary
    from nexus.tools.registry import default_registry, load_custom_tools

    registry = default_registry()
    assert registry.get("word_count") is None
    assert load_custom_tools(registry, ToolLibrary()) == []
    assert registry.get("word_count") is not None


def test_a_tool_can_be_replaced_after_reading_its_script(tmp_path: Path) -> None:
    brain = MockBrain()
    replacement = call(
        "create_tool",
        "c3",
        name="word_count",
        description="Count the characters instead.",
        parameters={"text": "the text"},
        code="import json, sys\nprint(len(json.load(sys.stdin)['text']))\n",
    )
    script(
        brain,
        create_word_count(),
        replacement,
        call("word_count", "c4", text="abcd"),
        "4 characters.",
    )
    approver = ScriptedApprover()
    messages, _, _ = run(tmp_path, brain, approver)
    created, replaced, counted = tool_results(messages)
    assert "Created" in created and "Replaced" in replaced and counted == "4"
    replace_request = approver.requests[1]
    assert replace_request[0] == "create_tool" and replace_request[1] is not None
    assert replace_request[1].before == CODE  # the user was shown a diff against the old script


def test_a_reply_with_no_tool_calls_is_unaffected(tmp_path: Path) -> None:
    brain = MockBrain()
    script(brain, "Just an answer.")
    _, _, result = run(tmp_path, brain, ScriptedApprover())
    assert result.final_text == "Just an answer." and result.halt is not HaltReason.MAX_STEPS
    assert isinstance(brain.calls[0][1], list)  # tools were offered, and unused
    _ = BrainReply, Usage  # imported for parity with the other loop tests
