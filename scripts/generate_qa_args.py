"""Command line and defaults of ``scripts/generate_qa.py`` (T4.2)."""

import argparse
from pathlib import Path

from pruefstand.dataset.datagen_pins import CROSS_CHECK_MODEL, DATAGEN_MODEL, PROMPT_VERSIONS

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = REPO / "corpus" / "slice_v1"
DEFAULT_WORK = REPO / "datasets" / "_work"
DEFAULT_EXCLUDE = REPO / "experiments" / "model_selection" / "indomain_dev_sources.json"
DEFAULT_CATALOGUE = REPO / "infra" / "gpu" / "models.yaml"


def build_parser(description: str) -> argparse.ArgumentParser:
    """Return the argument parser of the script (``description`` is the first docstring line)."""
    parser = argparse.ArgumentParser(description=description)
    add = parser.add_argument
    add("--pass", dest="phase", choices=["generate", "validate", "both"], default="generate")
    add("--tenant", required=True, help="tenant id or 'all'")
    add("--n", type=int, required=True, help="units (chunks or pairs) per tenant")
    add("--category", choices=sorted(PROMPT_VERSIONS), default="factual")
    add("--model", default=DATAGEN_MODEL, help="github/<model> of the datagen model")
    add("--cross-check", type=float, default=0.0, metavar="FRACTION")
    add("--cross-check-model", default=CROSS_CHECK_MODEL)
    add("--seed", type=int, default=7)
    add("--max-requests", type=int, default=None, help="request cap per client")
    add("--concurrency", type=int, default=4)
    add("--corpus-dir", type=Path, default=DEFAULT_CORPUS)
    add("--exclude-file", type=Path, default=DEFAULT_EXCLUDE)
    add("--citation-graph", type=Path, default=None, help="data/raw/hf/oldp_citation_graph")
    add("--work-dir", type=Path, default=DEFAULT_WORK)
    add("--run", default=None, help="run directory name (default: from the arguments)")
    add("--judge-model", default=None, help="pass 2: local judge (default: the catalogue's)")
    add("--no-judge", action="store_true", help="pass 2: deterministic checks only")
    return parser
