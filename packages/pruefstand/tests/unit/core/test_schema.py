import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from pruefstand.core.schema import export_schemas, register_schema

NAMES = ["canary_registry", "chunk", "corpus_manifest", "run_manifest", "testcase"]


def test_exports_expected_files(tmp_path: Path) -> None:
    paths = export_schemas(tmp_path / "schemas")
    assert {p.name for p in paths} >= {f"{n}.schema.json" for n in NAMES}
    assert all(p.is_file() for p in paths)
    assert paths == sorted(paths)


def test_second_run_is_byte_identical(tmp_path: Path) -> None:
    first = {p.name: p.read_bytes() for p in export_schemas(tmp_path)}
    second = {p.name: p.read_bytes() for p in export_schemas(tmp_path)}
    assert first == second


def test_format(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    text = (tmp_path / "testcase.schema.json").read_text(encoding="utf-8")
    assert text.endswith("}\n")
    schema = json.loads(text)
    assert schema["additionalProperties"] is False
    assert json.dumps(schema, sort_keys=True, indent=2, ensure_ascii=False) + "\n" == text


def test_register_schema_adds_a_file(tmp_path: Path) -> None:
    class Extra(BaseModel):
        x: int

    register_schema("zz_extra_for_test", Extra)
    register_schema("zz_extra_for_test", Extra)
    assert (tmp_path / "zz_extra_for_test.schema.json") in export_schemas(tmp_path)


def test_register_schema_rejects_a_different_model_for_a_name() -> None:
    class Other(BaseModel):
        y: int

    with pytest.raises(ValueError, match="already registered"):
        register_schema("testcase", Other)
