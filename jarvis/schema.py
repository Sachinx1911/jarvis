"""Validation of the portable JSON Schema subset (PLAN.md 5.7).

The core validates every structured output and tool argument itself, whatever the
provider claims.
"""

from __future__ import annotations

from typing import Any


def validate(data: Any, schema: dict[str, Any]) -> bool:
    """Core-side check of the portable schema subset, whatever the provider claims."""
    t = schema.get("type")
    if t == "object":
        if not isinstance(data, dict):
            return False
        props = schema.get("properties", {})
        if any(k not in data for k in schema.get("required", [])):
            return False
        if schema.get("additionalProperties") is False and any(k not in props for k in data):
            return False
        return all(validate(data[k], props[k]) for k in data if k in props)
    if t == "array":
        return isinstance(data, list) and all(validate(x, schema.get("items", {})) for x in data)
    if t == "string":
        return isinstance(data, str) and ("enum" not in schema or data in schema["enum"])
    if t == "integer":
        return isinstance(data, int) and not isinstance(data, bool)
    if t == "number":
        return isinstance(data, (int, float)) and not isinstance(data, bool)
    if t == "boolean":
        return isinstance(data, bool)
    return True
