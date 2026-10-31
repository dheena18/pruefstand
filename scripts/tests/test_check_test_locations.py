from pathlib import Path

import pytest
from check_test_locations import main

ROOTS = [
    "packages/pruefstand/src", "apps/rag-demo/src", "packages/pruefstand/tests",
    "apps/rag-demo/tests", "scripts", "data", "experiments", "tools", "action", "infra/gpu",
    "benchmarks", "infra/vm", "infra/cluster", "infra/gate-executor/orchestrator",
    "infra/gate-executor/llm-proxy",
]  # fmt: skip
TESTPATHS = [
    "packages/*/tests", "apps/rag-demo/tests", "tools/*/tests", "infra/gpu/tests",
    "infra/vm/tests", "infra/cluster/tests", "infra/gate-executor/*/tests", "scripts/tests",
    "scripts/*/tests", "tests", "benchmarks/tests", "experiments",
]  # fmt: skip


def _toml_list(items: list[str]) -> str:
    return "[" + ", ".join(f'"{i}"' for i in items) + "]"


def _repo(
    tmp: Path,
    files: list[str],
    *,
    testpaths: list[str] | None = None,
    mypy_path: list[str] | None = None,
) -> Path:
    tp = TESTPATHS if testpaths is None else testpaths
    mp = ROOTS if mypy_path is None else mypy_path
    (tmp / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\n"
        f"pythonpath = {_toml_list(ROOTS)}\n"
        f"testpaths = {_toml_list(tp)}\n"
        "[tool.mypy]\n"
        f"mypy_path = {_toml_list(mp)}\n",
        encoding="utf-8",
    )
    for rel in files:
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    return tmp


def _run(tmp: Path) -> int:
    return main(["--root", str(tmp)])


def test_test_outside_testpaths_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _repo(tmp_path, ["foo/test_x.py"])
    assert _run(tmp_path) == 1
    assert "foo/test_x.py" in capsys.readouterr().out


def test_test_under_scripts_tests_passes(tmp_path: Path) -> None:
    _repo(tmp_path, ["scripts/tests/test_x.py"])
    assert _run(tmp_path) == 0


def test_test_under_glob_testpath_passes(tmp_path: Path) -> None:
    _repo(tmp_path, ["tools/review_app/tests/test_x.py"])
    assert _run(tmp_path) == 0


def test_scripts_area_tests_pass(tmp_path: Path) -> None:
    _repo(tmp_path, ["scripts/dashboard/tests/test_derive.py"])
    assert _run(tmp_path) == 0


def test_init_in_test_dir_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _repo(tmp_path, ["scripts/tests/test_x.py", "scripts/tests/__init__.py"])
    assert _run(tmp_path) == 1
    assert "scripts/tests/__init__.py" in capsys.readouterr().out


def test_name_clash_between_roots_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _repo(tmp_path, ["scripts/foo.py", "tools/foo.py"])
    assert _run(tmp_path) == 1
    assert "foo" in capsys.readouterr().out


def test_name_clash_across_gpu_and_benchmarks_fails(tmp_path: Path) -> None:
    _repo(tmp_path, ["infra/gpu/schema.py", "benchmarks/schema.py"])
    assert _run(tmp_path) == 1


def test_pythonpath_mypy_path_mismatch_fails(tmp_path: Path) -> None:
    _repo(tmp_path, [], mypy_path=ROOTS[:-1])
    assert _run(tmp_path) == 1


def test_repeated_test_basenames_and_conftests_pass(tmp_path: Path) -> None:
    files = [
        "scripts/tests/test_health.py",
        "infra/vm/tests/test_health.py",
        "infra/cluster/tests/conftest.py",
        "scripts/tests/conftest.py",
    ]
    _repo(tmp_path, files)
    assert _run(tmp_path) == 0


def test_unit_dirs_in_two_test_roots_pass(tmp_path: Path) -> None:
    files = [
        "packages/pruefstand/tests/unit/test_a.py",
        "apps/rag-demo/tests/unit/test_a.py",
    ]
    _repo(tmp_path, files)
    assert _run(tmp_path) == 0


def test_testsupport_in_two_test_roots_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = [
        "packages/pruefstand/tests/testsupport/builders.py",
        "apps/rag-demo/tests/testsupport/builders.py",
    ]
    _repo(tmp_path, files)
    assert _run(tmp_path) == 1
    assert "testsupport" in capsys.readouterr().out


def test_tests_dir_missing_from_testpaths_names_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    testpaths = [p for p in TESTPATHS if p != "infra/vm/tests"]
    _repo(tmp_path, ["infra/vm/tests/test_x.py"], testpaths=testpaths)
    assert _run(tmp_path) == 1
    assert "infra/vm" in capsys.readouterr().out


def test_test_file_directly_in_root_fails(tmp_path: Path) -> None:
    _repo(tmp_path, ["infra/vm/test_x.py"])
    assert _run(tmp_path) == 1
