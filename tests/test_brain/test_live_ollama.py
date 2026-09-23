"""Live integration test against local Ollama running nexus-qwen."""

import httpx
import pytest

from nexus.brain.openai_compat import OpenAIBrain
from nexus.messages import Message, ToolSpec


def is_ollama_online() -> bool:
    """Check if the local Ollama server is currently listening."""
    try:
        resp = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
        return resp.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not is_ollama_online(), reason="Local Ollama instance not reachable")
def test_live_ollama_chat_streaming() -> None:
    brain = OpenAIBrain(
        base_url="http://127.0.0.1:11434/v1",
        model="nexus-qwen",
        temperature=0.1,
        timeout_sec=30.0,
    )

    deltas: list[str] = []
    reply = brain.chat(
        messages=[
            Message.system("You are a helpful assistant. Reply with only the single word PONG."),
            Message.user("PING"),
        ],
        on_delta=deltas.append,
    )

    full_text = "".join(deltas).strip()
    assert len(full_text) > 0
    assert reply.message.content.strip() == full_text
    assert reply.usage.total_tokens > 0


@pytest.mark.skipif(not is_ollama_online(), reason="Local Ollama instance not reachable")
def test_live_ollama_tool_call() -> None:
    brain = OpenAIBrain(
        base_url="http://127.0.0.1:11434/v1",
        model="nexus-qwen",
        temperature=0.1,
        timeout_sec=45.0,
    )

    tools = [
        ToolSpec(
            name="read_file",
            description="Read content of a file given its path.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path of the file to read",
                    }
                },
                "required": ["path"],
            },
        )
    ]

    reply = brain.chat(
        messages=[
            Message.system(
                "You are an assistant with access to tools. "
                "Always call tools to inspect files when requested."
            ),
            Message.user("Please read the file named 'test.py' using the read_file tool."),
        ],
        tools=tools,
    )

    # Either native tool calls or extracted fallback tool calls should be present
    assert len(reply.tool_calls) >= 1
    assert reply.tool_calls[0].name == "read_file"
    assert "path" in reply.tool_calls[0].arguments
