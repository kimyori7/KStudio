"""sanitize_json_schema — JSON 비호환 값 (Python type) 정규화."""
from __future__ import annotations

from screen_recorder.agent.backends.tool_adapter import sanitize_json_schema


def test_sanitize_python_int_type_to_integer_string():
    raw = {"type": "object", "properties": {"start_ms": int}}
    out = sanitize_json_schema(raw)
    assert out == {"type": "object", "properties": {"start_ms": "integer"}}


def test_sanitize_nested_dict_and_list():
    raw = {"a": {"b": [int, str, bool]}}
    out = sanitize_json_schema(raw)
    assert out == {"a": {"b": ["integer", "string", "boolean"]}}


def test_sanitize_none_type_to_null():
    assert sanitize_json_schema(type(None)) == "null"


def test_sanitize_unmapped_class_falls_back_to_classname():
    class _Foo:
        pass
    assert sanitize_json_schema(_Foo) == "_Foo"


def test_sanitize_passes_through_primitives():
    assert sanitize_json_schema(42) == 42
    assert sanitize_json_schema("hi") == "hi"
    assert sanitize_json_schema([1, "x", None]) == [1, "x", None]
    assert sanitize_json_schema({"a": 1}) == {"a": 1}
