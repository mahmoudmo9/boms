"""Structured outputs (v0.9.0 section 1.3): every task declares a JSON schema; the model's answer is parsed and checked
against it, retried once with the validation errors, then reported as failed.

A small validator for the subset of JSON Schema the task schemas use (type, properties, required, items, enum,
minimum, maximum, additionalProperties false, nullable types as lists) — no new dependency."""
import json
import re
from typing import Any

TYPES = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
         "null": type(None)}


class InvalidOutput(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:10]))
        self.errors = errors


def parse_json(text: str) -> Any:
    """The JSON object in a model answer (a code fence or text around it is tolerated)."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                pass
    raise InvalidOutput(["the answer is not a JSON object"])


def _type_ok(value: Any, expected) -> bool:
    names = expected if isinstance(expected, list) else [expected]
    for name in names:
        py = TYPES[name]
        if name in ("integer", "number") and isinstance(value, bool):
            continue
        if name == "integer" and isinstance(value, float) and value.is_integer():
            return True
        if isinstance(value, py):
            return True
    return False


def errors(value: Any, schema: dict, path: str = "$") -> list[str]:
    out: list[str] = []
    if "type" in schema and not _type_ok(value, schema["type"]):
        return [f"{path}: expected {schema['type']}"]
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: must be one of {schema['enum']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            out.append(f"{path}: below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            out.append(f"{path}: above {schema['maximum']}")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                out.append(f"{path}.{key}: required")
        for key, sub in value.items():
            if key in props:
                out += errors(sub, props[key], f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                out.append(f"{path}.{key}: not allowed")
    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            out += errors(item, schema["items"], f"{path}[{i}]")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            out.append(f"{path}: more than {schema['maxItems']} items")
    return out


def validate(value: Any, schema: dict) -> Any:
    found = errors(value, schema)
    if found:
        raise InvalidOutput(found)
    return value
