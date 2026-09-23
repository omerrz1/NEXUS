"""Unit tests for tool call parsing, fallback extraction, and JSON repair."""

from nexus.brain.toolcalls import (
    extract_all_tool_calls,
    extract_tool_calls_from_text,
    parse_native_tool_call,
    repair_json,
)


def test_repair_json_valid() -> None:
    raw = '{"path": "file.txt", "lines": 10}'
    assert repair_json(raw) == {"path": "file.txt", "lines": 10}


def test_repair_json_trailing_comma() -> None:
    raw = '{"path": "file.txt", "count": 5,}'
    assert repair_json(raw) == {"path": "file.txt", "count": 5}


def test_repair_json_single_quotes() -> None:
    raw = "{'path': 'file.txt', 'count': 5}"
    assert repair_json(raw) == {"path": "file.txt", "count": 5}


def test_repair_json_python_literals() -> None:
    raw = '{"active": True, "done": False, "meta": None}'
    assert repair_json(raw) == {"active": True, "done": False, "meta": None}


def test_repair_json_markdown_fence() -> None:
    raw = """```json
{"name": "read_file", "arguments": {"path": "foo.py"}}
```"""
    res = repair_json(raw)
    assert res == {"name": "read_file", "arguments": {"path": "foo.py"}}


def test_repair_json_unterminated_braces() -> None:
    raw = '{"path": "test.txt", "nested": {"key": "val"'
    res = repair_json(raw)
    assert res is not None
    assert res["path"] == "test.txt"
    assert res["nested"]["key"] == "val"


def test_parse_native_tool_call_valid() -> None:
    native = {
        "id": "call_123",
        "function": {
            "name": "read_file",
            "arguments": '{"path": "foo.py"}',
        },
    }
    call, err = parse_native_tool_call(native, 0)
    assert err is None
    assert call is not None
    assert call.id == "call_123"
    assert call.name == "read_file"
    assert call.arguments == {"path": "foo.py"}


def test_parse_native_tool_call_dict_args() -> None:
    native = {
        "id": "call_456",
        "function": {
            "name": "list_dir",
            "arguments": {"path": "."},
        },
    }
    call, err = parse_native_tool_call(native, 0)
    assert err is None
    assert call is not None
    assert call.name == "list_dir"
    assert call.arguments == {"path": "."}


def test_extract_tool_calls_from_text_tag() -> None:
    text = """Let me inspect the file first.
<tool_call>
{"name": "read_file", "arguments": {"path": "nexus/main.py"}}
</tool_call>
"""
    calls, errors = extract_tool_calls_from_text(text)
    assert not errors
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "nexus/main.py"}


def test_extract_tool_calls_from_text_fence() -> None:
    text = """Here is what I will run:
```json
{
  "name": "run_command",
  "arguments": {"command": "ls -la"}
}
```
"""
    calls, errors = extract_tool_calls_from_text(text)
    assert not errors
    assert len(calls) == 1
    assert calls[0].name == "run_command"
    assert calls[0].arguments == {"command": "ls -la"}


def test_extract_all_tool_calls_native_precedence() -> None:
    native = [
        {"id": "native_1", "function": {"name": "find_files", "arguments": '{"pattern": "*.py"}'}}
    ]
    text = '<tool_call>{"name": "read_file", "arguments": {"path": "x"}}</tool_call>'

    calls, errors = extract_all_tool_calls(native, text)
    assert not errors
    assert len(calls) == 1
    assert calls[0].name == "find_files"
