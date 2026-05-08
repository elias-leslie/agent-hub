"""Focused tests for work-context formatting helpers."""

from __future__ import annotations

import pytest

from app.api.complete.work_context import (
    _build_lines,
    _format_value,
    _is_present,
    inject_work_context_dict,
    inject_work_context_message,
    work_context_to_prompt,
)


class _FakeMessage:
    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content


class _FakeModel:
    def model_dump(self, *, exclude_none: bool = True) -> dict[str, object]:
        return {"mode": "test", "project_id": "p1"}


class _FakeEmptyModel:
    def model_dump(self, *, exclude_none: bool = True) -> dict[str, object]:
        return {}


# _is_present
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        (0, True),
        (False, True),
        ("hello", True),
        ([], True),  # str([]) is "[]", non-empty
    ],
)
def test_is_present(value: object, expected: bool) -> None:
    assert _is_present(value) is expected


# _format_value
def test_format_value_scalar() -> None:
    assert _format_value("hello") == "hello"
    assert _format_value(42) == "42"
    assert _format_value(False) == "False"


def test_format_value_dict() -> None:
    assert _format_value({"b": 2, "a": 1}) == '{"a":1,"b":2}'


# _build_lines
def test_build_lines_skips_missing_keys() -> None:
    lines = _build_lines({"mode": "task", "project_id": "p1"})
    assert lines[0] == "<work_context>"
    assert "mode: task" in lines
    assert "project: p1" in lines
    assert "task:" not in "\n".join(lines)
    assert lines[-1] == "</work_context>"


def test_build_lines_includes_json_dict() -> None:
    lines = _build_lines({"adhoc_spec": {"x": 1}})
    assert '{"x":1}' in "\n".join(lines)


def test_build_lines_omits_empty_values() -> None:
    lines = _build_lines({"mode": "", "project_id": None, "task_id": "   "})
    body = "\n".join(lines)
    assert "mode:" not in body
    assert "project:" not in body
    assert "task:" not in body


# work_context_to_prompt
def test_prompt_none_input() -> None:
    assert work_context_to_prompt(None) is None


def test_prompt_empty_dict() -> None:
    assert work_context_to_prompt({}) is None


def test_prompt_empty_model() -> None:
    assert work_context_to_prompt(_FakeEmptyModel()) is None


def test_prompt_from_model() -> None:
    prompt = work_context_to_prompt(_FakeModel())
    assert prompt is not None
    assert "mode: test" in prompt
    assert "project: p1" in prompt


def test_prompt_from_plain_dict() -> None:
    prompt = work_context_to_prompt({"mode": "adhoc", "task_id": "t1"})
    assert prompt is not None
    assert "mode: adhoc" in prompt
    assert "task: t1" in prompt
    assert "project:" not in prompt


# inject_work_context_message
def test_inject_message_returns_original_when_no_context() -> None:
    msgs = [_FakeMessage("user", "hi")]
    assert inject_work_context_message(msgs, None) is msgs


def test_inject_message_prefixes_system() -> None:
    msgs = [_FakeMessage("user", "hi")]
    result = inject_work_context_message(msgs, {"mode": "x"})
    assert len(result) == 2
    assert result[0].role == "system"
    assert "mode: x" in result[0].content
    assert result[1] is msgs[0]


# inject_work_context_dict
def test_inject_dict_returns_original_when_no_context() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    assert inject_work_context_dict(msgs, None) is msgs


def test_inject_dict_prefixes_system() -> None:
    msgs = [{"role": "user", "content": "hi"}]
    result = inject_work_context_dict(msgs, {"mode": "y"})
    assert len(result) == 2
    assert result[0] == {"role": "system", "content": "\n".join(_build_lines({"mode": "y"}))}
    assert result[1] is msgs[0]
