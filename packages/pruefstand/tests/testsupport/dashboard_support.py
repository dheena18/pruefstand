"""Sanitised exports and pushes against a local bare repository (T6.1 tests)."""

from pathlib import Path
from typing import Any

from testsupport.store_support import registry, run_of

from pruefstand.store.dashboard_repo import push_dashboard_data
from pruefstand.store.sanitise import sanitise_run, seal_export, write_public_export


def export(
    tmp: Path,
    index: int,
    *,
    cases: bool = True,
    name: str = "pub",
    added: dict[str, bytes] | None = None,
) -> Path:
    run = run_of(tmp, index)
    out = write_public_export(sanitise_run(run, registry("VN-7f3a9c")), tmp / f"{name}{index}")
    if cases:
        (out / "cases").mkdir()
        (out / "cases" / "000.json").write_text('{"cases": []}', encoding="utf-8")
        (out / "report.html").write_text("<html>report</html>", encoding="utf-8")
        (out / "gate.json").write_text('{"status": "pass"}', encoding="utf-8")
    for filename, data in (added or {}).items():
        (out / filename).write_bytes(data)
    seal_export(out)
    return out


def push(bare: Path, src: Path, **kwargs: Any) -> str:
    return push_dashboard_data(src, "owner/pruefstand-dashboard-data", remote=str(bare), **kwargs)
