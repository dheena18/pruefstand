"""Hugging Face export: one config per ``license_config`` (interfaces §14, T4.1 S5).

Layout (``hf_export`` or ``--out``)::

    README.md                      dataset card, YAML header ``configs:`` + ``config_licenses:``
    dataset_manifest.json          copy of the manifest (pipeline.datasets rebuilds the directory)
    <license_config>/<split>.jsonl one file per split that has rows of that config

``datasets/private/**`` is never exported, and cases tagged ``heldout`` / ``private`` are filtered.
The upload needs ``HF_TOKEN`` (env only) and never runs in CI; ``dry_run`` makes no network call.

CLI: ``python -m pruefstand.dataset.export_hf <dir> --repo <user>/<name> [--dry-run --out DIR]``.
"""

import argparse
import importlib
import re
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path

import jinja2
import yaml
from huggingface_hub import HfApi

from pruefstand.core.enums import Split
from pruefstand.core.errors import ConfigError, DatasetError
from pruefstand.core.logging import get_logger
from pruefstand.core.models.testcase import TestCase
from pruefstand.core.settings import PruefstandSettings
from pruefstand.dataset.export_manifest import write_hf_manifest
from pruefstand.dataset.io import read_dataset, write_split_file
from pruefstand.dataset.licenses import LICENSE_CONFIGS

_log = get_logger(__name__)
_REPO_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}")
PRIVATE_TAGS = frozenset({"heldout", "held_out", "private"})
EXPORT_DIR = "hf_export"
MARKER = ".pruefstand-hf-export"
_TEMPLATE_DIR = Path(__file__).parent
_LOAD_CHECK_SPLIT = "train"


def _refuse_private(directory: Path) -> None:
    parts = directory.resolve().parts
    if any(a == "datasets" and b == "private" for a, b in pairwise(parts)):
        msg = f"{directory}: datasets/private/** (held-out canaries) is never exported"
        raise DatasetError(msg)


def _rows_by_config(directory: Path) -> dict[str, dict[Split, list[TestCase]]]:
    loaded = read_dataset(directory)
    if loaded.manifest is None or loaded.problems:
        first = loaded.problems[0] if loaded.problems else "invalid manifest"
        msg = f"{directory}: not exportable, run `pruefstand validate dataset` ({first})"
        raise DatasetError(msg)
    grouped: dict[str, dict[Split, list[TestCase]]] = defaultdict(lambda: defaultdict(list))
    for split, cases in loaded.cases.items():
        for c in cases:
            if PRIVATE_TAGS & set(c.tags):
                continue
            grouped[c.license_config][split].append(c)
    return grouped


def _front_matter(layout: dict[str, list[str]]) -> str:
    configs = [
        {
            "config_name": name,
            "data_files": [{"split": s, "path": f"{name}/{s}.jsonl"} for s in splits],
        }
        for name, splits in sorted(layout.items())
    ]
    header = {
        "pretty_name": "Prüfstand-DE",
        "language": ["de", "en"],
        "task_categories": ["question-answering"],
        "license": "other",
        "license_name": "per-config, see config_licenses",
        "config_licenses": {n: LICENSE_CONFIGS[n].spdx for n in sorted(layout)},
        "configs": configs,
    }
    return yaml.safe_dump(header, sort_keys=False, allow_unicode=True)


def _render_card(
    directory: Path, repo_id: str, counts: dict[str, Counter[str]], layout: dict[str, list[str]]
) -> str:
    manifest = read_dataset(directory).manifest
    assert manifest is not None  # noqa: S101  (checked by _rows_by_config)
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
        autoescape=jinja2.select_autoescape(default_for_string=False, default=False),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    configs = [
        {
            "name": n,
            "license_name": LICENSE_CONFIGS[n].name,
            "attribution": LICENSE_CONFIGS[n].attribution,
            "counts": ", ".join(f"{s}: {counts[n][s]}" for s in layout[n]),
        }
        for n in sorted(layout)
    ]
    return env.get_template("card_template.md.j2").render(
        front_matter=_front_matter(layout),
        name=manifest.name,
        version=manifest.version,
        corpus_version=manifest.corpus_version,
        repo_id=repo_id,
        configs=configs,
    )


def build_hf_layout(
    directory: Path, out: Path, repo_id: str = "<HF_USER>/pruefstand-de"
) -> list[str]:
    """Write the HF layout of ``directory`` to ``out`` (no network).

    Args:
        directory: A dataset version directory.
        out: Target; must not exist or be empty, unless it holds the marker file of a previous
            export (then it is replaced); anything else is never deleted.
        repo_id: Used in the card text only.

    Returns:
        The config names written, sorted.

    Raises:
        DatasetError: ``directory`` is under ``datasets/private``, is invalid, holds an unknown
            licence config, or ``out`` is a non-empty directory.
    """
    _refuse_private(directory)
    grouped = _rows_by_config(directory)
    unknown = sorted(set(grouped) - set(LICENSE_CONFIGS))
    if unknown:
        msg = f"{directory}: unknown license_config {unknown[0]!r}; cannot export"
        raise DatasetError(msg)
    if out.exists() and any(out.iterdir()):
        if not (out / MARKER).is_file():  # only a previous export of ours may be replaced
            msg = f"{out}: output directory must be empty"
            raise DatasetError(msg)
        shutil.rmtree(out)
    layout: dict[str, list[str]] = {}
    counts: dict[str, Counter[str]] = {}
    for config, by_split in grouped.items():
        layout[config] = [s.value for s in Split if by_split.get(s)]
        counts[config] = Counter({s.value: len(r) for s, r in by_split.items() if r})
        for split, rows in by_split.items():
            if rows:
                write_split_file(out / config / f"{split.value}.jsonl", rows)
    write_hf_manifest(directory, out, grouped)
    (out / MARKER).write_text("written by pruefstand.dataset.export_hf\n", encoding="utf-8")
    (out / "README.md").write_text(
        _render_card(directory, repo_id, counts, layout), encoding="utf-8"
    )
    return sorted(layout)


def _load_dataset_function() -> Callable[..., object] | None:
    """``datasets.load_dataset``, or ``None`` when ``datasets`` is absent (or shadowed)."""
    try:
        module = importlib.import_module("datasets")
    except ImportError:
        return None
    found = getattr(module, "load_dataset", None)  # the repo's datasets/ folder has none
    return found if callable(found) else None


@contextmanager
def _offline() -> Iterator[None]:
    """Keep ``datasets`` off the network while the layout is checked (a dry run calls nothing)."""
    config = getattr(importlib.import_module("datasets"), "config", None)
    names = ("HF_HUB_OFFLINE", "HF_DATASETS_OFFLINE")
    before = {n: getattr(config, n, None) for n in names}
    for n in names:
        setattr(config, n, True)
    try:
        yield
    finally:
        for n in names:
            setattr(config, n, before[n])


def _check_loadable(out: Path, configs: Sequence[str]) -> None:
    """Load the files of every config with ``datasets`` (skipped when it is not usable)."""
    load = _load_dataset_function()
    if load is None:
        _log.warning("hf_export_load_check_skipped", reason="datasets is not installed")
        return
    with tempfile.TemporaryDirectory() as cache, _offline():
        for config in configs:
            files = sorted((out / config).glob("*.jsonl"))
            try:
                load(
                    "json",
                    data_files={_LOAD_CHECK_SPLIT: [str(f) for f in files]},
                    split=_LOAD_CHECK_SPLIT,
                    cache_dir=cache,
                )
            except Exception as exc:
                msg = f"hf export of config {config!r} does not load: {type(exc).__name__}"
                raise DatasetError(msg) from exc


def _check_repo_id(repo_id: str) -> None:
    if not _REPO_ID.fullmatch(repo_id):
        msg = f"repo id {repo_id!r} must look like <user>/<name>"
        raise ConfigError(msg)


def export_hf(dir: Path, repo_id: str, private: bool, *, dry_run: bool = False) -> None:  # noqa: A002, FBT001
    """Export a dataset directory as one Hugging Face config per licence config.

    Args:
        dir: ``datasets/<name>/<version>/``.
        repo_id: ``<user>/<name>`` of the dataset repo.
        private: Create the repo as private.
        dry_run: Build the layout under ``dir / "hf_export"``, check that it loads, upload nothing.

    Raises:
        ConfigError: ``repo_id`` is malformed, or a real upload is requested without ``HF_TOKEN``.
        DatasetError: The dataset is under ``datasets/private``, invalid, or does not load.
    """
    _check_repo_id(repo_id)
    if dry_run:
        out = dir / EXPORT_DIR
        _check_loadable(out, build_hf_layout(dir, out, repo_id))
        return
    secret = PruefstandSettings().hf_token  # HF_TOKEN, else the alias PRUEFSTAND_HF_TOKEN
    token = secret.get_secret_value() if secret is not None else ""
    if not token:
        msg = (
            "HF_TOKEN is not set; a real export needs a Hugging Face write token in the environment"
        )
        raise ConfigError(msg)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "layout"
        _check_loadable(out, build_hf_layout(dir, out, repo_id))
        api = HfApi(token=token)
        api.create_repo(repo_id=repo_id, repo_type="dataset", private=private, exist_ok=True)
        api.upload_folder(
            repo_id=repo_id,
            repo_type="dataset",
            folder_path=str(out),
            ignore_patterns=[MARKER],
            commit_message="Update Prüfstand-DE dataset",
        )


def _run(args: argparse.Namespace) -> list[str]:
    """Run the parsed CLI request; return the config names to list."""
    if args.dry_run and args.out is not None:
        _check_repo_id(args.repo)
        configs = build_hf_layout(args.dataset, args.out, args.repo)
        _check_loadable(args.out, configs)
        return configs
    export_hf(args.dataset, args.repo, not args.public, dry_run=args.dry_run)
    if not args.dry_run:
        return []
    return sorted(p.name for p in (args.dataset / EXPORT_DIR).iterdir() if p.is_dir())


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the exit code (0 ok, 2 usage or dataset error)."""
    parser = argparse.ArgumentParser(prog="python -m pruefstand.dataset.export_hf")
    parser.add_argument("dataset", type=Path, help="datasets/<name>/<version>/")
    parser.add_argument("--repo", required=True, help="<user>/<name>")
    parser.add_argument("--dry-run", action="store_true", help="build the layout, upload nothing")
    parser.add_argument("--out", type=Path, help="with --dry-run: where to write the layout")
    parser.add_argument(
        "--public", action="store_true", help="create a public repo (default private)"
    )
    args = parser.parse_args(argv)
    try:
        configs = _run(args)
    except (ConfigError, DatasetError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    for config in configs:
        sys.stdout.write(f"{config}/\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
