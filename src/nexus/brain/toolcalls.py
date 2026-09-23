"""Multi-tier tool-call extraction, fallback text parsing, and JSON repair."""

import json
import re
from typing import Any

from nexus.messages import ToolCall

_TOOL_TAG_PATTERN = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL | re.IGNORECASE)
_CODE_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def repair_json(raw: str) -> dict[str, Any] | None:
    """Attempt to parse potentially malformed JSON with heuristics."""
    text = raw.strip()
    if not text:
        return None

    # Step 1: Direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Step 2: Strip outer markdown fences if present
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()

    # Step 3: Replace python constants
    text = re.sub(r"\bTrue\b", "true", text)
    text = re.sub(r"\bFalse\b", "false", text)
    text = re.sub(r"\bNone\b", "null", text)

    # Step 4: Remove trailing commas before } or ]
    text = re.sub(r",\s*([}\]])", r"\1", text)

    # Step 5: Convert single-quoted keys and string values to double quotes
    # Matches 'key': or: 'value' where not preceded by escape
    single_quote_pattern = re.compile(r"(?<!\\)'([^'\\]*(?:\\.[^'\\]*)*)'")
    text_fixed_quotes = single_quote_pattern.sub(r'"\1"', text)

    for candidate in (text, text_fixed_quotes):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    # Step 6: Handle truncated/unterminated JSON by balancing brackets
    open_braces = text_fixed_quotes.count("{") - text_fixed_quotes.count("}")
    open_brackets = text_fixed_quotes.count("[") - text_fixed_quotes.count("]")
    if open_braces > 0 or open_brackets > 0:
        balanced = text_fixed_quotes + ("]" * max(0, open_brackets)) + ("}" * max(0, open_braces))
        try:
            data = json.loads(balanced)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    return None


def parse_native_tool_call(
    call_dict: dict[str, Any], index: int
) -> tuple[ToolCall | None, str | None]:
    """Parse one OpenAI-style tool call dictionary."""
    call_id = str(call_dict.get("id") or f"call_{index}")
    func = call_dict.get("function")
    if not isinstance(func, dict):
        return None, f"Tool call {call_id} missing 'function' payload."

    name = func.get("name")
    if not isinstance(name, str) or not name.strip():
        return None, f"Tool call {call_id} missing function name."

    raw_args = func.get("arguments", {})
    if isinstance(raw_args, dict):
        return ToolCall(id=call_id, name=name, arguments=raw_args), None

    if isinstance(raw_args, str):
        parsed = repair_json(raw_args)
        if parsed is not None:
            return ToolCall(id=call_id, name=name, arguments=parsed), None
        return None, f"Failed to parse arguments JSON for tool '{name}': {raw_args}"

    return None, f"Unexpected arguments format for tool '{name}'."


def extract_tool_calls_from_text(content: str) -> tuple[list[ToolCall], list[str]]:
    """Extract tool calls embedded within text tags or JSON code fences."""
    calls: list[ToolCall] = []
    errors: list[str] = []

    # Check for <tool_call> tags first
    tag_matches = _TOOL_TAG_PATTERN.findall(content)
    for idx, match in enumerate(tag_matches):
        parsed = repair_json(match)
        if parsed and "name" in parsed:
            name = str(parsed["name"])
            arguments = parsed.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {k: v for k, v in parsed.items() if k != "name"}
            calls.append(ToolCall(id=f"text_call_{idx}", name=name, arguments=arguments))
        else:
            errors.append(f"Could not parse <tool_call> payload: {match.strip()}")

    if calls:
        return calls, errors

    # Check for markdown code fences containing JSON with a "name" field
    fence_matches = _CODE_BLOCK_PATTERN.findall(content)
    for idx, match in enumerate(fence_matches):
        parsed = repair_json(match)
        if parsed and "name" in parsed:
            name = str(parsed["name"])
            arguments = parsed.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {k: v for k, v in parsed.items() if k != "name"}
            calls.append(ToolCall(id=f"fence_call_{idx}", name=name, arguments=arguments))

    return calls, errors


def extract_all_tool_calls(
    native_calls: list[dict[str, Any]] | None,
    content: str | None,
) -> tuple[tuple[ToolCall, ...], tuple[str, ...]]:
    """Extract tool calls using native responses with text fallback and repair."""
    calls: list[ToolCall] = []
    errors: list[str] = []

    if native_calls:
        for idx, item in enumerate(native_calls):
            call, err = parse_native_tool_call(item, idx)
            if call is not None:
                calls.append(call)
            if err is not None:
                errors.append(err)
        return tuple(calls), tuple(errors)

    if content:
        text_calls, text_errors = extract_tool_calls_from_text(content)
        calls.extend(text_calls)
        errors.extend(text_errors)

    return tuple(calls), tuple(errors)
