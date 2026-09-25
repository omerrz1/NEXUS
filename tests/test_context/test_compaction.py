"""Tests for replacing the oldest part of a conversation with a model-written summary."""

import re

import pytest

from nexus.brain.base import BrainReply
from nexus.brain.mock import MockBrain
from nexus.context.compaction import (
    SUMMARY_PREFIX,
    compact,
    is_summary,
    plan_compaction,
)
from nexus.messages import Message, Role, ToolCall, Usage


def summarizer(text: str = "- the user fixed a bug") -> MockBrain:
    """A brain whose every reply is `text`, costing 15 tokens."""
    reply = BrainReply(Message.assistant(text), (), Usage(10, 5, 15))
    return MockBrain(responder=lambda messages: reply)


def turn(number: int) -> list[Message]:
    """One finished turn: a question, a tool call with its result, and an answer."""
    call = ToolCall(f"c{number}", "read_file", {"path": f"file{number}.py"})
    return [
        Message.user(f"question {number}"),
        Message.assistant("", (call,)),
        Message.tool(call.id, f"contents of file {number}", "read_file"),
        Message.assistant(f"answer {number}"),
    ]


def conversation(turns: int) -> list[Message]:
    messages = [Message.system("system prompt")]
    for number in range(1, turns + 1):
        messages += turn(number)
    return messages


# ---- plan_compaction


@pytest.mark.parametrize("keep_tokens", [0, 5, 20, 40, 60, 100, 200, 100_000])
def test_the_kept_part_never_starts_with_a_tool_result(keep_tokens: int) -> None:
    messages = [*conversation(4), Message.user("newest request")]
    cut = plan_compaction(messages, keep_tokens)
    if cut is not None:
        assert messages[cut].role is not Role.TOOL
        assert cut <= len(messages) - 1  # the request itself is always kept


def test_the_newest_request_is_kept_even_when_it_alone_exceeds_the_keep_budget() -> None:
    messages = [*conversation(2), Message.user("very long request " * 500)]
    assert plan_compaction(messages, keep_tokens=10) == len(messages) - 1


def test_more_recent_turns_are_kept_when_there_is_room() -> None:
    messages = [*conversation(4), Message.user("newest request")]
    small = plan_compaction(messages, keep_tokens=10)
    large = plan_compaction(messages, keep_tokens=60)
    assert small is not None and large is not None and large < small


def test_nothing_to_compact_when_the_request_is_the_first_message() -> None:
    assert plan_compaction([Message.system("s"), Message.user("hello")], keep_tokens=100) is None


def test_an_earlier_summary_alone_is_not_worth_summarizing_again() -> None:
    summary = Message.user(f"{SUMMARY_PREFIX}\n- something")
    assert plan_compaction([Message.system("s"), summary, Message.user("next")], 10) is None


def test_the_newest_tool_call_always_stays_with_its_results() -> None:
    call = ToolCall("last", "read_file", {"path": "a.py"})
    messages = [*conversation(3), Message.user("ask"), Message.assistant("", (call,))]
    messages += [Message.tool("last", "result one", "read_file")]
    for keep_tokens in (0, 10, 10_000):
        cut = plan_compaction(messages, keep_tokens)
        if cut is not None:
            assert cut <= len(messages) - 2  # the assistant message that made the call is kept


def test_a_running_turn_can_be_summarized_too_so_long_turns_never_hit_the_limit() -> None:
    request = Message.user("read everything")
    messages = [Message.system("s"), request]
    for number in range(1, 6):
        messages += turn(number)[1:]  # the steps of this turn, without another question
    cut = plan_compaction(messages, keep_tokens=0, request=request)
    assert cut is not None and cut > 2  # steps after the request are folded, not just before it


def test_the_request_alone_is_not_worth_summarizing() -> None:
    request = Message.user("start")
    messages = [Message.system("s"), request, *turn(1)[1:]]
    assert plan_compaction(messages, keep_tokens=10_000, request=request) is None


def test_the_request_stays_word_for_word_when_a_long_turn_is_summarized() -> None:
    request = Message.user("read everything")
    messages = [Message.system("s"), *conversation(1)[1:], request]
    for number in range(2, 6):
        messages += turn(number)[1:]
    tail = messages[-1:]  # with no room to spare, only the newest message is kept

    cut = plan_compaction(messages, keep_tokens=0, request=request)
    assert cut is not None
    result = compact(messages, cut, summarizer(), request=request)

    assert result is not None
    assert is_summary(messages[1])
    assert messages[2] is request  # the very same message, straight after the summary
    assert messages[3:] == tail
    assert sum(message is request for message in messages) == 1


def test_a_request_that_ends_up_in_the_kept_part_is_not_duplicated() -> None:
    request = Message.user("newest")
    messages = [*conversation(3), request]
    cut = plan_compaction(messages, keep_tokens=0, request=request)
    assert cut is not None
    compact(messages, cut, summarizer(), request=request)
    assert sum(message is request for message in messages) == 1


def test_equal_text_is_not_the_same_message() -> None:
    earlier = Message.user("yes")
    request = Message.user("yes")  # same words, a different message
    messages = [Message.system("s"), earlier, Message.assistant("ok"), request]
    cut = plan_compaction(messages, keep_tokens=0, request=request)
    assert cut == 3  # the earlier "yes" is real history and is worth summarizing
    compact(messages, cut, summarizer(), request=request)
    assert messages[-1] is request and len(messages) == 3


# ---- compact


def test_old_messages_become_one_summary_and_the_rest_is_untouched() -> None:
    messages = [*conversation(3), Message.user("newest request")]
    tail = messages[9:]  # the newest turn and the request
    cut = plan_compaction(messages, keep_tokens=0)
    assert cut == 13

    result = compact(messages, cut, summarizer("- read three files"))

    assert result is not None and result.replaced == 12
    assert messages[0] == Message.system("system prompt")
    assert is_summary(messages[1]) and "- read three files" in messages[1].content
    assert messages[2:] == [Message.user("newest request")]
    assert result.usage.total_tokens == 15
    assert result.tokens_after < result.tokens_before
    assert tail[-1] is messages[-1]


def test_the_todo_list_and_notes_are_pinned_word_for_word() -> None:
    messages = [*conversation(2), Message.user("next")]
    pinned = "Todo list:\n1. [done] step one\n\nSession notes:\n1. prefers tabs"
    compact(messages, len(messages) - 1, summarizer(), pinned)
    assert messages[1].content.endswith(pinned)
    assert messages[1].content.startswith(SUMMARY_PREFIX)


def test_the_summarizer_sees_the_old_conversation_as_a_transcript() -> None:
    brain = summarizer()
    messages = [*conversation(2), Message.user("next")]
    compact(messages, len(messages) - 1, brain)

    system, request = brain.calls[0][0]
    assert "running summary" in system.content
    text = request.content
    assert "Summary so far:\n(nothing yet)" in text
    assert "User: question 1" in text
    assert '[called read_file {"path": "file1.py"}]' in text
    assert "Result of read_file: contents of file 1" in text
    assert "Assistant: answer 2" in text


def test_long_messages_are_shortened_for_the_summarizer() -> None:
    brain = summarizer()
    big_result = Message.tool("c1", "x" * 5000, "read_file")
    big_question = Message.user("y" * 5000)
    call = ToolCall("c1", "read_file", {"path": "a"})
    messages = [
        Message.system("s"),
        big_question,
        Message.assistant("", (call,)),
        big_result,
        Message.user("next"),
    ]
    compact(messages, 4, brain)
    text = brain.calls[0][0][1].content
    longest_x = max(len(run) for run in re.findall(r"x+", text))
    longest_y = max(len(run) for run in re.findall(r"y{20,}", text))
    assert (longest_x, longest_y) == (300, 1500)  # a taste, not the whole thing


def test_an_earlier_summary_is_carried_forward_not_stacked() -> None:
    first = summarizer("- first summary")
    messages = [*conversation(2), Message.user("second question")]
    compact(messages, len(messages) - 1, first, pinned="Session notes:\n1. old note")
    messages += [*turn(3), Message.user("third question")]

    second = summarizer("- combined summary")
    cut = plan_compaction(messages, keep_tokens=0)
    assert cut is not None
    compact(messages, cut, second, pinned="Session notes:\n1. new note")

    fed = second.calls[0][0][1].content
    assert "Summary so far:\n- first summary" in fed
    assert "old note" not in fed  # only the model-written part is fed back
    assert sum(is_summary(message) for message in messages) == 1
    assert "- combined summary" in messages[1].content
    assert "new note" in messages[1].content and "old note" not in messages[1].content


def test_a_very_long_history_is_summarized_a_block_at_a_time() -> None:
    replies = iter(f"- summary after block {number}" for number in range(1, 100))
    brain = MockBrain(
        context_window=900,  # blocks of 300 estimated tokens
        responder=lambda messages: BrainReply(Message.assistant(next(replies)), (), Usage(1, 1, 2)),
    )
    messages = [*conversation(20), Message.user("newest")]
    cut = plan_compaction(messages, keep_tokens=0)
    assert cut is not None
    result = compact(messages, cut, brain)

    assert len(brain.calls) > 2
    for number, (sent, _) in enumerate(brain.calls[1:], start=1):
        assert f"Summary so far:\n- summary after block {number}" in sent[1].content
    assert result is not None and result.usage.total_tokens == 2 * len(brain.calls)
    assert f"block {len(brain.calls)}" in messages[1].content  # the last summary wins


def test_when_the_model_writes_no_summary_the_conversation_is_left_alone() -> None:
    messages = [*conversation(3), Message.user("newest")]
    before = list(messages)
    assert compact(messages, len(messages) - 1, summarizer("   ")) is None
    assert messages == before


def test_a_runaway_summary_is_cut_to_a_sane_length() -> None:
    messages = [*conversation(2), Message.user("next")]
    compact(messages, len(messages) - 1, summarizer("word " * 5000))
    assert len(messages[1].content) < 3200


def test_is_summary_recognises_only_the_message_compaction_leaves() -> None:
    assert is_summary(Message.user(f"{SUMMARY_PREFIX}\n- x"))
    assert not is_summary(Message.assistant(f"{SUMMARY_PREFIX}\n- x"))
    assert not is_summary(Message.user("a normal question"))
