"""JSON Schema registry over spec/schemas, in loose (published) and strict mode.

Strict mode follows SPEC.md section 15: every object schema with `properties` and no
`additionalProperties`/`unevaluatedProperties` gets `unevaluatedProperties: false`, except
schemas sitting directly under `if`, `then`, `else` or `allOf`.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

BASE_URI = "https://app.invalid/spec/v1/"

_SKIP_VALUE_KEYS = {"const", "enum", "default", "examples"}
_NO_STRICT_PARENTS = {"if", "then", "else", "allOf"}


def _strictify(node: Any, parent_key: str | None = None) -> None:
    if isinstance(node, dict):
        if (
            "properties" in node
            and "additionalProperties" not in node
            and "unevaluatedProperties" not in node
            and parent_key not in _NO_STRICT_PARENTS
        ):
            node["unevaluatedProperties"] = False
        for key, value in node.items():
            if key in _SKIP_VALUE_KEYS:
                continue
            if key == "properties" and isinstance(value, dict):
                for sub in value.values():
                    _strictify(sub, "properties")
                continue
            _strictify(value, key)
    elif isinstance(node, list):
        for item in node:
            _strictify(item, parent_key)


def strict_copy(schema: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(schema)
    _strictify(out)
    return out


@lru_cache(maxsize=4)
def _load_files(schemas_dir: str) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for path in sorted(Path(schemas_dir).glob("*.schema.json")):
        files[path.name] = json.loads(path.read_text())
    return files


@lru_cache(maxsize=8)
def _registry(schemas_dir: str, strict: bool) -> Registry:
    resources = []
    for name, schema in _load_files(schemas_dir).items():
        body = strict_copy(schema) if strict else schema
        uri = body.get("$id", BASE_URI + name)
        resources.append((uri, Resource.from_contents(body, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


class SchemaSet:
    """Validators for whole files or single $defs, in loose or strict mode."""

    def __init__(self, schemas_dir: Path) -> None:
        self.schemas_dir = str(schemas_dir)
        self._validators: dict[tuple[str, bool], Draft202012Validator] = {}

    def files(self) -> dict[str, dict[str, Any]]:
        return _load_files(self.schemas_dir)

    def validator(self, ref: str, strict: bool = False) -> Draft202012Validator:
        """ref is 'file.schema.json' or 'file.schema.json#/$defs/Name'."""
        key = (ref, strict)
        found = self._validators.get(key)
        if found is None:
            found = Draft202012Validator(
                {"$ref": BASE_URI + ref}, registry=_registry(self.schemas_dir, strict)
            )
            self._validators[key] = found
        return found

    def errors(self, ref: str, instance: Any, strict: bool = False) -> list[str]:
        out = []
        for err in self.validator(ref, strict).iter_errors(instance):
            path = "/".join(str(p) for p in err.absolute_path)
            out.append(f"{path or '<root>'}: {err.message[:300]}")
        return out

    def is_valid(self, ref: str, instance: Any, strict: bool = False) -> bool:
        return self.validator(ref, strict).is_valid(instance)


def server_def(msg_type: str) -> str:
    return "ws_server.schema.json#/$defs/S_" + msg_type.replace(".", "_")


def client_def(msg_type: str) -> str:
    return "ws_client.schema.json#/$defs/C_" + msg_type.replace(".", "_")
