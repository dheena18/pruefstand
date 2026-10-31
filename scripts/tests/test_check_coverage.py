import json
from pathlib import Path

import pytest
from check_coverage import FLOORS, OVERALL_FLOOR, main

SRC = "packages/pruefstand/src/pruefstand"
RAG = "apps/rag-demo/src/rag_demo"


def _entry(statements: int, covered: int) -> dict[str, dict[str, int]]:
    return {"summary": {"num_statements": statements, "covered_lines": covered,
                        "num_branches": 0, "covered_branches": 0}}  # fmt: skip


def _report(tmp: Path, *, core: float = 95, other: float = 95, rag: float = 95,
            perturb_statements: int = 1000) -> Path:  # fmt: skip
    files = {
        f"{SRC}/core/a.py": _entry(1000, round(core * 10)),
        f"{SRC}/gate/a.py": _entry(1000, 950),
        f"{SRC}/metrics/a.py": _entry(1000, 950),
        f"{SRC}/perturb/a.py": _entry(perturb_statements, round(perturb_statements * 0.95)),
        f"{SRC}/cli/a.py": _entry(1000, round(other * 10)),
        f"{RAG}/a.py": _entry(1000, round(rag * 10)),
    }
    path = tmp / "coverage.json"
    path.write_text(json.dumps({"files": files}), encoding="utf-8")
    return path


def test_thresholds_equal_claude_md_section_6() -> None:
    assert FLOORS == {"core": 90.0, "gate": 90.0, "metrics": 90.0, "perturb": 90.0}
    assert OVERALL_FLOOR == 80.0


def test_core_below_floor_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--file", str(_report(tmp_path, core=89.9))]) == 1
    assert "pruefstand/core 89.9% < 90%" in capsys.readouterr().out


def test_pruefstand_overall_below_floor_fails(tmp_path: Path) -> None:
    assert main(["--file", str(_report(tmp_path, core=95, other=0))]) == 1


def test_rag_demo_overall_below_floor_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--file", str(_report(tmp_path, rag=79))]) == 1
    assert "rag_demo" in capsys.readouterr().out


def test_all_above_floors_passes(tmp_path: Path) -> None:
    assert main(["--file", str(_report(tmp_path))]) == 0


def test_package_without_statements_is_skipped(tmp_path: Path) -> None:
    assert main(["--file", str(_report(tmp_path, perturb_statements=0))]) == 0
