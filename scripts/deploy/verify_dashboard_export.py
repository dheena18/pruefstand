"""Verify a checked-out ``pruefstand-dashboard-data`` tree before the dashboard build (T8.5 S3, N5.1).

``deploy.yml`` (``fetch-data``) runs this on the tree it fetched at the pinned SHA; on any finding
nothing is built or uploaded. The tree is judged as it is (never pruned or filtered here, UI13-20):

* ``manifest.json`` (``{"schema_version": "1", "files": {path: sha256}}``, written by
  ``push_dashboard_data``) lists exactly the files of the tree (``.git`` and itself excepted) and
  every SHA-256 matches;
* no file, ``report.html`` included, contains ``CANARY-`` or a chunk text given with
  ``--chunk-texts`` (the dashboard never shows raw chunk text);
* ``runs/index.json`` lists at most ``MAX_INDEX_RUNS`` runs and at most ``MAX_CASE_RUNS`` runs have
  ``cases/<run_id>/`` shards or a ``report.html`` (both constants come from
  ``pruefstand.core.models.dashboard``, no local copy);
* no ``runs/<run_id>/run.json`` has an ``infra_error`` with a ``:`` detail (UI13-13).

Exit codes: 0 ok, 1 findings (each on stderr, naming the file), 2 usage or unreadable input.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from pruefstand.core.models.dashboard import MAX_CASE_RUNS, MAX_INDEX_RUNS

CANARY = b"CANARY-"
MIN_CHUNK_CHARS = 40
MANIFEST = "manifest.json"


def tree_files(root: Path) -> dict[str, Path]:
    """Every regular file under ``root`` by relative POSIX path (no ``.git``, no manifest)."""
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and not rel.startswith(".git/") and rel != MANIFEST:
            found[rel] = path
    return found


def _manifest_files(root: Path) -> tuple[dict[str, str], list[str]]:
    try:
        doc = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        files = doc["files"]
        if doc["schema_version"] != "1" or not isinstance(files, dict):
            msg = "unsupported manifest"
            raise ValueError(msg)  # noqa: TRY301
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {}, [f"{MANIFEST}: missing or unreadable ({exc})"]
    return {str(k): str(v) for k, v in files.items()}, []


def check_hashes(found: dict[str, Path], listed: dict[str, str]) -> list[str]:
    """The manifest and the tree list the same files and every SHA-256 matches."""
    findings = [f"{name}: not listed in {MANIFEST}" for name in sorted(set(found) - set(listed))]
    findings += [
        f"{name}: listed in {MANIFEST} but missing" for name in sorted(set(listed) - set(found))
    ]
    for name in sorted(set(found) & set(listed)):
        if hashlib.sha256(found[name].read_bytes()).hexdigest() != listed[name]:
            findings.append(f"{name}: SHA-256 differs from {MANIFEST}")
    return findings


def _texts(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "text" and isinstance(item, str) and len(item) >= MIN_CHUNK_CHARS:
                yield item
            else:
                yield from _texts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _texts(item)


def load_chunk_texts(paths: Iterable[Path]) -> list[str]:
    """Every ``text`` string (>= 40 chars) of JSON or JSONL files: raw chunk text, never published."""
    out: list[str] = []
    for path in paths:
        raw = path.read_text(encoding="utf-8")
        try:
            out.extend(_texts(json.loads(raw)))
        except ValueError:
            out.extend(
                t for line in raw.splitlines() if line.strip() for t in _texts(json.loads(line))
            )
    return out


def check_redaction(found: dict[str, Path], chunk_texts: Sequence[str]) -> list[str]:
    """No file contains ``CANARY-`` or one of the raw chunk texts."""
    encoded = [t.encode("utf-8") for t in chunk_texts]
    findings: list[str] = []
    for name, path in found.items():
        data = path.read_bytes()
        if CANARY in data:
            findings.append(f"{name}: contains 'CANARY-'")
        if any(text in data for text in encoded):
            findings.append(f"{name}: contains raw chunk text")
    return findings


def _run_ids(found: dict[str, Path], prefix: str, suffix: str = "") -> set[str]:
    ids: set[str] = set()
    for name in found:
        parts = name.split("/")
        if parts[0] == prefix and len(parts) >= 3 and (not suffix or name.endswith(suffix)):
            ids.add(parts[1])
    return ids


def check_limits(root: Path, found: dict[str, Path]) -> list[str]:
    """At most ``MAX_INDEX_RUNS`` indexed runs and ``MAX_CASE_RUNS`` runs with cases or a report."""
    findings: list[str] = []
    try:
        runs = json.loads((root / "runs" / "index.json").read_text(encoding="utf-8"))["runs"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"runs/index.json: missing or unreadable ({exc})"]
    if len(runs) > MAX_INDEX_RUNS:
        findings.append(f"runs/index.json: {len(runs)} runs, more than {MAX_INDEX_RUNS}")
    with_cases = _run_ids(found, "cases") | _run_ids(found, "runs", "/report.html")
    if len(with_cases) > MAX_CASE_RUNS:
        findings.append(
            f"cases/ or report.html for {len(with_cases)} runs, more than {MAX_CASE_RUNS}"
        )
    return findings


def check_infra_error(found: dict[str, Path]) -> list[str]:
    """``run.json`` keeps only the kind of ``infra_error``, never ``kind: detail`` (UI13-13)."""
    findings: list[str] = []
    for name, path in found.items():
        if not (name.startswith("runs/") and name.endswith("/run.json")):
            continue
        try:
            error = json.loads(path.read_text(encoding="utf-8")).get("infra_error")
        except (ValueError, AttributeError):
            findings.append(f"{name}: unreadable run.json")
            continue
        if isinstance(error, str) and ":" in error:
            findings.append(f"{name}: infra_error still carries a ':' detail")
    return findings


def verify(root: Path, chunk_texts: Sequence[str] = ()) -> list[str]:
    """All findings for the tree at ``root`` (empty = ok)."""
    listed, findings = _manifest_files(root)
    found = tree_files(root)
    if not findings:
        findings += check_hashes(found, listed)
    return (
        findings
        + check_redaction(found, chunk_texts)
        + check_limits(root, found)
        + check_infra_error(found)
    )


def main(argv: Sequence[str] | None = None) -> int:
    """CLI: ``verify_dashboard_export.py <tree> [--chunk-texts FILE ...]``."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("tree", type=Path)
    parser.add_argument("--chunk-texts", type=Path, nargs="*", default=[])
    args = parser.parse_args(argv)
    if not (args.tree / MANIFEST).is_file():
        sys.stderr.write(f"verify_dashboard_export: {args.tree / MANIFEST} not found\n")
        return 2
    try:
        texts = load_chunk_texts(args.chunk_texts)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"verify_dashboard_export: cannot read the chunk texts: {exc}\n")
        return 2
    findings = verify(args.tree, texts)
    for line in findings:
        sys.stderr.write(f"verify_dashboard_export: {line}\n")
    if findings:
        return 1
    sys.stdout.write(f"verify_dashboard_export: ok ({len(tree_files(args.tree))} files)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
