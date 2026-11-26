"""Turn a Pydantic model into a self-contained, "strict" JSON schema.

Providers' structured-output modes accept only a subset of JSON Schema:
* no `$ref` / `$defs` (we inline them),
* every object has `additionalProperties: false` and lists all keys in `required`,
* no `title` / `default` noise.
Pydantic still does the real validation afterwards, so constraints providers
ignore (minLength, pattern...) are kept where harmless and enforced by us.
"""

from typing import Any

from pydantic import BaseModel

_DROP = {"title", "default", "examples"}
# Keywords some providers reject inside strict schemas; Pydantic re-checks them anyway.
_UNSUPPORTED = {"minLength", "maxLength", "pattern", "minItems", "maxItems", "format"}


def strict_schema(model: type[BaseModel], *, keep_constraints: bool = False) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(n) for n in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return walk(defs[node["$ref"].split("/")[-1]])
        out: dict[str, Any] = {}
        for k, v in node.items():
            if k in _DROP or (not keep_constraints and k in _UNSUPPORTED):
                continue
            out[k] = walk(v) if k != "properties" else {pk: walk(pv) for pk, pv in v.items()}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out

    result: dict[str, Any] = walk(raw)
    return result
