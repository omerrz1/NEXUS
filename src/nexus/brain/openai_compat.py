"""OpenAI-compatible HTTP brain adapter for local servers (Ollama, llama.cpp, etc.)."""

import json
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

import httpx

from nexus.brain.base import BrainReply, Depth
from nexus.brain.tokens import estimate_tokens
from nexus.brain.toolcalls import extract_all_tool_calls
from nexus.messages import Message, ToolSpec, Usage

# The OpenAI `reasoning_effort` value sent for each depth. BALANCED sends nothing so the
# server's default applies, which also keeps models that cannot think working. On
# thinking models served by Ollama, "low" and "medium" think about as long as the
# default; only "none" actually skips thinking, which is why FAST uses it.
_REASONING_EFFORT: dict[Depth, str | None] = {
    Depth.FAST: "none",
    Depth.BALANCED: None,
    Depth.DEEP: "high",
}


def is_loopback_url(url: str) -> bool:
    """Validate that the given URL points strictly to a loopback address."""
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        return False
    if hostname in ("127.0.0.1", "localhost", "::1") or hostname.startswith("127."):
        return True
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in addrinfo:
            ip = str(sockaddr[0])
            if not (ip.startswith("127.") or ip == "::1"):
                return False
        return True
    except socket.gaierror:
        return False


class OpenAIBrain:
    """Communicates with local OpenAI-compatible /v1/chat/completions endpoints."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434/v1",
        model: str = "nexus-qwen",
        context_window: int = 4096,
        temperature: float = 0.2,
        timeout_sec: float = 120.0,
        client: httpx.Client | None = None,
    ) -> None:
        if not is_loopback_url(base_url):
            raise ValueError(
                f"Base URL '{base_url}' is not a loopback address. "
                "Nexus only permits local connections."
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._context_window = context_window
        self._temperature = temperature
        self._timeout_sec = timeout_sec
        self._client = client or httpx.Client(timeout=timeout_sec)

    @property
    def context_window(self) -> int:
        """The total context window in tokens."""
        return self._context_window

    def chat(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
        depth: Depth = Depth.BALANCED,
    ) -> BrainReply:
        """Send conversation messages and stream or await the model response."""
        payload = self._build_payload(messages, tools, depth, stream=on_delta is not None)
        url = f"{self._base_url}/chat/completions"

        try:
            if on_delta is not None:
                return self._chat_stream(url, payload, on_delta, on_reasoning)
            return self._chat_sync(url, payload)
        except httpx.ConnectError as err:
            raise RuntimeError(
                f"Cannot connect to local model server at '{self._base_url}'. "
                "Ensure Ollama or llama.cpp is running on loopback."
            ) from err

    def _build_payload(
        self,
        messages: list[Message],
        tools: list[ToolSpec] | None,
        depth: Depth,
        stream: bool,
    ) -> dict[str, Any]:
        """Construct the chat completions JSON request payload."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [msg.to_dict() for msg in messages],
            "temperature": self._temperature,
            "stream": stream,
            "options": {"num_ctx": self._context_window},
        }
        effort = _REASONING_EFFORT[depth]
        if effort is not None:
            payload["reasoning_effort"] = effort
        if tools:
            payload["tools"] = [tool.to_dict() for tool in tools]
        if stream:
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _chat_sync(self, url: str, payload: dict[str, Any]) -> BrainReply:
        """Execute a non-streaming chat completions request."""
        response = self._client.post(url, json=payload)
        if response.status_code != 200:
            raise RuntimeError(f"Model server error ({response.status_code}): {response.text}")

        data = response.json()
        choice = data.get("choices", [{}])[0]
        msg_data = choice.get("message", {})
        content = msg_data.get("content") or ""
        native_calls = msg_data.get("tool_calls")

        tool_calls, _ = extract_all_tool_calls(native_calls, content)
        usage_data = data.get("usage", {})
        usage = self._parse_usage(usage_data, content)

        assistant_msg = Message.assistant(content, tool_calls)
        return BrainReply(message=assistant_msg, tool_calls=tool_calls, usage=usage)

    def _chat_stream(
        self,
        url: str,
        payload: dict[str, Any],
        on_delta: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
    ) -> BrainReply:
        """Stream chat completions via SSE and reassemble deltas and tool calls."""
        with self._client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = response.read().decode(errors="replace")
                raise RuntimeError(f"Model server error ({response.status_code}): {body}")

            return self._consume_sse_stream(response, on_delta, on_reasoning)

    def _consume_sse_stream(
        self,
        response: httpx.Response,
        on_delta: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
    ) -> BrainReply:
        """Process streaming lines from SSE response."""
        content_parts: list[str] = []
        raw_tool_calls: dict[int, dict[str, Any]] = {}
        usage_dict: dict[str, Any] = {}

        for line in response.iter_lines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            self._process_chunk(chunk, content_parts, raw_tool_calls, on_delta, on_reasoning)
            if chunk.get("usage"):
                usage_dict = chunk["usage"]

        full_content = "".join(content_parts)
        ordered_calls = [raw_tool_calls[i] for i in sorted(raw_tool_calls.keys())]
        tool_calls, _ = extract_all_tool_calls(ordered_calls or None, full_content)
        usage = self._parse_usage(usage_dict, full_content)

        assistant_msg = Message.assistant(full_content, tool_calls)
        return BrainReply(message=assistant_msg, tool_calls=tool_calls, usage=usage)

    def _process_chunk(
        self,
        chunk: dict[str, Any],
        content_parts: list[str],
        raw_tool_calls: dict[int, dict[str, Any]],
        on_delta: Callable[[str], None],
        on_reasoning: Callable[[str], None] | None = None,
    ) -> None:
        """Extract content deltas, reasoning, and tool call fragments from a stream chunk."""
        choices = chunk.get("choices", [])
        if not choices:
            return
        delta = choices[0].get("delta", {})

        reasoning = delta.get("reasoning") or delta.get("reasoning_content")
        if reasoning and on_reasoning is not None:
            on_reasoning(reasoning)

        delta_content = delta.get("content")
        if delta_content:
            content_parts.append(delta_content)
            on_delta(delta_content)

        for tc in delta.get("tool_calls", []):
            idx = tc.get("index", 0)
            entry = raw_tool_calls.setdefault(
                idx, {"id": "", "function": {"name": "", "arguments": ""}}
            )
            if tc.get("id"):
                entry["id"] += tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                entry["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                entry["function"]["arguments"] += fn["arguments"]

    def _parse_usage(self, usage_data: dict[str, Any], content: str) -> Usage:
        """Extract server usage or fallback to token heuristic."""
        if usage_data:
            return Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )
        est = estimate_tokens(content)
        return Usage(prompt_tokens=0, completion_tokens=est, total_tokens=est)
