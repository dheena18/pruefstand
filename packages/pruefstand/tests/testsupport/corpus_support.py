"""Helpers of the ingest tests (T2.5): a raw data tree in the T2.1 layout built from the real fixtures.

``build_raw_root`` zips the trimmed GII norms, copies the EUR-Lex pairs and writes the three OLDP
records as one JSON-lines dump, exactly where ``make data`` would put them. ``fixture_config``
copies the committed ``tests/fixtures/corpus.yaml`` (the tenant plan under test) and changes only
``raw_root``.
"""

import json
import zipfile
from pathlib import Path

import yaml

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PLAN_FIXTURE = FIXTURES / "corpus.yaml"
REPO_ROOT = Path(__file__).resolve().parents[4]

GII_FILES = {
    "bgb": "bgb_sample.xml",
    "egbgb": "egbgb_sample.xml",
    "aktg": "aktg_95.xml",
    "kschg": "kschg_1.xml",
    "arbzg": "arbzg_3.xml",
    "kwg": "kwg_53ca.xml",
}
EURLEX_ACTS = {"32016R0679": "gdpr", "32003L0088": "workingtime"}
OLDP_RECORDS = ("labour_lag_hessen", "insurance_ag_duesseldorf", "noheadings_ovg_sachsen")


def build_raw_root(root: Path, *, skip: frozenset[str] = frozenset()) -> Path:
    """Write ``<root>/gii/<slug>/xml.zip``, ``eurlex/<celex>/{de,en}.html`` and the OLDP dump.

    Args:
        root: Target directory (created).
        skip: Source ids (``"gii:kschg"``, ``"eurlex:32016R0679"``, ``"oldp"``) to leave out.

    Returns:
        ``root``.
    """
    for slug, name in GII_FILES.items():
        if f"gii:{slug}" in skip:
            continue
        target = root / "gii" / slug
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(target / "xml.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(name, (FIXTURES / "gii" / name).read_bytes())
    for celex, stem in EURLEX_ACTS.items():
        if f"eurlex:{celex}" in skip:
            continue
        target = root / "eurlex" / celex
        target.mkdir(parents=True, exist_ok=True)
        for lang in ("de", "en"):
            (target / f"{lang}.html").write_bytes(
                (FIXTURES / "eurlex" / f"{stem}_{lang}.html").read_bytes()
            )
    if "oldp" not in skip:
        dump = root / "hf" / "oldp_decisions" / "dump-fixture"
        dump.mkdir(parents=True, exist_ok=True)
        rows = [
            json.loads((FIXTURES / "oldp" / f"{stem}.json").read_text("utf-8"))
            for stem in OLDP_RECORDS
        ]
        (dump / "train.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
        )
    return root


def fixture_config(directory: Path, raw_root: Path) -> Path:
    """Copy the committed fixture plan to ``directory`` with ``raw_root`` and the pins made absolute.

    Args:
        directory: Where to write ``corpus.yaml``.
        raw_root: The tree from :func:`build_raw_root`.

    Returns:
        The path of the written config.
    """
    data = yaml.safe_load(PLAN_FIXTURE.read_text(encoding="utf-8"))
    data["raw_root"] = str(raw_root)
    data["sources_file"] = str(REPO_ROOT / "data" / "sources.yaml")
    path = directory / "corpus.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path
