"""Unit tests for OpenAIBrain using mock HTTP transports."""

import json

import httpx
import pytest

from nexus.brain.base import Depth
from nexus.brain.openai_compat import OpenAIBrain, is_loopback_url
from nexus.messages import Message, ToolSpec


def test_is_loopback_url() -> None:
    assert is_loopback_url("http://127.0.0.1:11434/v1") is True
    assert is_loopback_url("http://localhost:8080/v1") is True
    assert is_loopback_url("http://[::1]:11434") is True
    assert is_loopback_url("https://api.openai.com/v1") is False
    assert is_loopback_url("http://google.com") is False
    assert is_loopback_url("http://192.168.1.100:11434/v1") is False


def test_non_loopback_url_rejected() -> None:
    with pytest.raises(ValueError, match="not a loopback address"):
        OpenAIBrain(base_url="https://api.openai.com/v1")


def test_openai_brain_chat_sync() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        data = json.loads(request.read())
        assert data["model"] == "test-model"
        response_body = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello from mock server!",
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return httpx.Response(200, json=response_body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    brain = OpenAIBrain(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        client=client,
    )

    reply = brain.chat([Message.user("Hi")])
    assert reply.message.content == "Hello from mock server!"
    assert reply.usage.total_tokens == 15
    assert not reply.tool_calls


def test_openai_brain_chat_streaming_with_tool_calls() -> None:
    call_chunk_1 = (
        'data: {"choices":[{"delta":{"tool_calls":['
        '{"index":0,"id":"call_1","function":{"name":"read_file","arguments":"{\\"path\\": "}}'
        "]}}]}\n\n"
    )
    call_chunk_2 = (
        'data: {"choices":[{"delta":{"tool_calls":['
        '{"index":0,"function":{"arguments":"\\"test.py\\"}"}}'
        "]}}]}\n\n"
    )
    sse_events = [
        'data: {"choices":[{"delta":{"content":"Let me "}}]}\n\n',
        'data: {"choices":[{"delta":{"content":"read the file."}}]}\n\n',
        call_chunk_1,
        call_chunk_2,
        'data: {"usage":{"prompt_tokens":12,"completion_tokens":8,"total_tokens":20}}\n\n',
        "data: [DONE]\n\n",
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content="".join(sse_events).encode("utf-8"),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    brain = OpenAIBrain(
        base_url="http://127.0.0.1:11434/v1",
        model="test-model",
        client=client,
    )

    deltas: list[str] = []
    reply = brain.chat(
        [Message.user("Check test.py")],
        tools=[ToolSpec(name="read_file", description="Read a file", parameters={})],
        on_delta=deltas.append,
    )

    assert "".join(deltas) == "Let me read the file."
    assert reply.message.content == "Let me read the file."
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0].id == "call_1"
    assert reply.tool_calls[0].name == "read_file"
    assert reply.tool_calls[0].arguments == {"path": "test.py"}
    assert reply.usage.total_tokens == 20


def test_openai_brain_server_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal server error")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    brain = OpenAIBrain(base_url="http://127.0.0.1:11434/v1", client=client)

    with pytest.raises(RuntimeError, match="Model server error"):
        brain.chat([Message.user("Hello")])


@pytest.mark.parametrize(
    ("depth", "expected_effort"),
    [(Depth.FAST, "none"), (Depth.BALANCED, None), (Depth.DEEP, "high")],
)
def test_depth_sets_reasoning_effort(depth: Depth, expected_effort: str | None) -> None:
    sent: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.read()))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    brain = OpenAIBrain(base_url="http://127.0.0.1:11434/v1", client=client)
    brain.chat([Message.user("Hi")], depth=depth)

    assert sent.get("reasoning_effort") == expected_effort


def sse_reply(finish_reason: str, prompt_tokens: int, completion_tokens: int) -> httpx.Response:
    total = prompt_tokens + completion_tokens
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total,
    }
    chunks = [
        {"choices": [{"delta": {"content": "partial answer"}}]},
        {"choices": [{"delta": {}, "finish_reason": finish_reason}]},
        {"usage": usage},
    ]
    events = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks] + ["data: [DONE]\n\n"]
    headers = {"content-type": "text/event-stream"}
    return httpx.Response(200, headers=headers, content="".join(events).encode())


def streaming_brain(response: httpx.Response, window: int = 16384) -> OpenAIBrain:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
    return OpenAIBrain(base_url="http://127.0.0.1:11434/v1", context_window=window, client=client)


def test_a_reply_stopped_for_length_is_marked_cut_off_and_teaches_the_real_window() -> None:
    brain = streaming_brain(sse_reply("length", prompt_tokens=4082, completion_tokens=14))
    reply = brain.chat([Message.user("hi")], on_delta=lambda text: None)
    assert reply.cut_off
    assert (
        brain.context_window == 4096
    )  # 4082 + 14: the server's real window, not the 16384 assumed


def test_a_normal_stop_is_not_cut_off_and_keeps_the_window() -> None:
    brain = streaming_brain(sse_reply("stop", prompt_tokens=300, completion_tokens=20))
    reply = brain.chat([Message.user("hi")], on_delta=lambda text: None)
    assert not reply.cut_off and brain.context_window == 16384


def test_a_cut_off_without_server_counts_does_not_change_the_window() -> None:
    body = {"choices": [{"message": {"content": "partial"}, "finish_reason": "length"}]}
    client = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body))
    )
    brain = OpenAIBrain(base_url="http://127.0.0.1:11434/v1", context_window=8192, client=client)
    reply = brain.chat([Message.user("hi")])  # not streaming, and the server sent no usage
    assert reply.cut_off and brain.context_window == 8192
