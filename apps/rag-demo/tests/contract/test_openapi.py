"""The app's generated OpenAPI equals schemas/target-api-v1.openapi.yaml (descriptions ignored).

`/v1/retrieve` and `RetrieveResponse` belong to T3.5 and are left out of the comparison here;
T3.5 removes the exclusion when it adds the endpoint.
"""

from typing import Any

import yaml
from rd_support import CONFIGS, REPO

from rag_demo.api import create_app
from rag_demo.config import Settings, load_config

T3_5 = {"/v1/retrieve", "RetrieveResponse"}
SETTINGS = Settings(qdrant_url="http://q.test", llm_url="http://l.test", embed_url="http://e.test")


def _types(schema: dict[str, Any]) -> frozenset[str]:
    """Normalise `type: [x, null]`, `anyOf` with null and `$ref` to a set of type names."""
    if "$ref" in schema:
        return frozenset({schema["$ref"].rsplit("/", 1)[-1]})
    if "oneOf" in schema or "anyOf" in schema:
        out: set[str] = set()
        for part in schema.get("oneOf", schema.get("anyOf", [])):
            out |= _types(part)
        return frozenset(out)
    kind = schema.get("type", "any")
    names = set(kind) if isinstance(kind, list) else {kind}
    if "items" in schema and names <= {"array", "null"}:
        names |= {f"[{'|'.join(sorted(_types(schema['items'])))}]"}
        names.discard("array")
    return frozenset(names)


T3_6_PROPERTIES = {"prompt_overflow"}  # T3.6 adds this counter to /v1/health.stats


def _component(schema: dict[str, Any]) -> dict[str, Any]:
    props = {k: v for k, v in schema.get("properties", {}).items() if k not in T3_6_PROPERTIES}
    return {
        "required": sorted(schema.get("required", [])),
        "properties": {name: sorted(_types(p)) for name, p in props.items()},
        "extra": schema.get("additionalProperties", True) is not False,
    }


def _project(spec: dict[str, Any]) -> dict[str, Any]:
    paths = {
        (path, method): {
            "id": op["operationId"],
            "request": _body_ref(op.get("requestBody")),
            "response": _body_ref(op["responses"]["200"]),
        }
        for path, ops in spec["paths"].items()
        if path not in T3_5
        for method, op in ops.items()
    }
    schemas = {
        name: _component(s)
        for name, s in spec["components"]["schemas"].items()
        if name not in T3_5 and not name.startswith(("HTTPValidation", "ValidationError"))
    }
    return {"paths": paths, "schemas": schemas}


def _body_ref(node: dict[str, Any] | None) -> str | None:
    if node is None:
        return None
    return str(node["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1])


def test_generated_openapi_equals_the_checked_in_file() -> None:
    app = create_app(load_config(CONFIGS / "rag.yaml"), settings=SETTINGS)
    expected = yaml.safe_load(
        (REPO / "schemas" / "target-api-v1.openapi.yaml").read_text(encoding="utf-8")
    )
    got = _project(app.openapi())
    want = _project(expected)
    assert got["paths"] == want["paths"]
    assert got["schemas"].keys() == want["schemas"].keys()
    for name in want["schemas"]:
        assert got["schemas"][name] == want["schemas"][name], name
