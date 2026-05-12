"""Tool-argument validation + coercion (port of pi-mono ``utils/validation.ts``).

Pi-mono uses TypeBox; we use ``jsonschema`` for validation and a manual
coercion pass that mirrors pi-mono's primitive-coercion semantics.
"""

from __future__ import annotations

import copy
from typing import Any

from ..types import Tool, ToolCall

try:
    from jsonschema import Draft202012Validator as _Draft202012Validator
    from jsonschema.exceptions import ValidationError as _ValidationError
except ImportError:  # pragma: no cover
    _Draft202012Validator = None  # type: ignore[assignment,misc]
    _ValidationError = None  # type: ignore[assignment,misc]

Draft202012Validator: Any = _Draft202012Validator
ValidationError: Any = _ValidationError


def _is_record(value: Any) -> bool:
    return isinstance(value, dict)


def _get_schema_types(schema: dict[str, Any]) -> list[str]:
    t = schema.get("type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


def _matches_json_type(value: Any, type_name: str) -> bool:
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "null":
        return value is None
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


def _coerce_primitive_by_type(value: Any, type_name: str) -> Any:
    if type_name in ("number", "integer"):
        if value is None:
            return 0
        if isinstance(value, str) and value.strip():
            try:
                parsed = float(value) if type_name == "number" else int(value)
                if type_name == "integer" and float(value).is_integer():
                    return int(value)
                if type_name == "number":
                    return parsed
            except ValueError:
                pass
        if isinstance(value, bool):
            return 1 if value else 0
        return value
    if type_name == "boolean":
        if value is None:
            return False
        if value == "true":
            return True
        if value == "false":
            return False
        if value == 1:
            return True
        if value == 0:
            return False
        return value
    if type_name == "string":
        if value is None:
            return ""
        if isinstance(value, (int, float, bool)):
            return str(value)
        return value
    if type_name == "null":
        if value == "" or value == 0 or value is False:
            return None
        return value
    return value


def _coerce_with_schema(value: Any, schema: dict[str, Any]) -> Any:
    next_value = value

    if isinstance(schema.get("allOf"), list):
        for nested in schema["allOf"]:
            if isinstance(nested, dict):
                next_value = _coerce_with_schema(next_value, nested)

    if isinstance(schema.get("anyOf"), list):
        next_value = _coerce_with_union(next_value, schema["anyOf"])

    if isinstance(schema.get("oneOf"), list):
        next_value = _coerce_with_union(next_value, schema["oneOf"])

    types = _get_schema_types(schema)
    matches_union_member = len(types) > 1 and any(_matches_json_type(next_value, t) for t in types)
    if types and not matches_union_member:
        for t in types:
            candidate = _coerce_primitive_by_type(next_value, t)
            if candidate is not next_value:
                next_value = candidate
                break

    if "object" in types and isinstance(next_value, dict):
        _apply_object_coercion(next_value, schema)

    if "array" in types and isinstance(next_value, list):
        _apply_array_coercion(next_value, schema)

    return next_value


def _coerce_with_union(value: Any, schemas: list[Any]) -> Any:
    if Draft202012Validator is None:
        return value
    for schema in schemas:
        if not isinstance(schema, dict):
            continue
        try:
            candidate = copy.deepcopy(value)
        except Exception:
            candidate = value
        coerced = _coerce_with_schema(candidate, schema)
        try:
            Draft202012Validator(schema).validate(coerced)
            return coerced
        except Exception:
            continue
    return value


def _apply_object_coercion(value: dict[str, Any], schema: dict[str, Any]) -> None:
    properties = schema.get("properties") or {}
    defined_keys = set(properties.keys())
    for key, prop_schema in properties.items():
        if key in value and isinstance(prop_schema, dict):
            value[key] = _coerce_with_schema(value[key], prop_schema)

    additional = schema.get("additionalProperties")
    if isinstance(additional, dict):
        for key in list(value.keys()):
            if key in defined_keys:
                continue
            value[key] = _coerce_with_schema(value[key], additional)


def _apply_array_coercion(value: list[Any], schema: dict[str, Any]) -> None:
    items = schema.get("items")
    if isinstance(items, list):
        for i in range(len(value)):
            if i < len(items) and isinstance(items[i], dict):
                value[i] = _coerce_with_schema(value[i], items[i])
        return
    if isinstance(items, dict):
        for i in range(len(value)):
            value[i] = _coerce_with_schema(value[i], items)


def _format_validation_path(error: ValidationError) -> str:
    path = ".".join(str(p) for p in error.absolute_path)
    if error.validator == "required":
        missing = error.message.split("'")[1] if "'" in error.message else ""
        if missing:
            return f"{path}.{missing}" if path else missing
    return path or "root"


def validate_tool_arguments(tool: Tool, tool_call: ToolCall) -> Any:
    """Validate ``tool_call.arguments`` against ``tool.parameters``.

    Returns the (possibly coerced) arguments. Raises ``ValueError`` with a
    formatted message on validation failure.
    """

    if Draft202012Validator is None:
        return tool_call.arguments

    args = copy.deepcopy(tool_call.arguments)
    coerced = _coerce_with_schema(args, tool.parameters)
    if isinstance(args, dict) and isinstance(coerced, dict):
        args.clear()
        args.update(coerced)
    else:
        args = coerced

    validator = Draft202012Validator(tool.parameters)
    errors = list(validator.iter_errors(args))
    if not errors:
        return args

    formatted = "\n".join(f"  - {_format_validation_path(e)}: {e.message}" for e in errors) or "Unknown validation error"
    import json as _json

    raise ValueError(
        f'Validation failed for tool "{tool_call.name}":\n{formatted}\n\n'
        f"Received arguments:\n{_json.dumps(tool_call.arguments, indent=2, default=str)}"
    )


def validate_tool_call(tools: list[Tool], tool_call: ToolCall) -> Any:
    """Find ``tool_call.name`` in ``tools`` and validate its arguments."""

    tool = next((t for t in tools if t.name == tool_call.name), None)
    if tool is None:
        raise ValueError(f'Tool "{tool_call.name}" not found')
    return validate_tool_arguments(tool, tool_call)


__all__ = ["validate_tool_arguments", "validate_tool_call"]
