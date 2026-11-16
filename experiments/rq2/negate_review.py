"""Manual review of the T5.4b sentence ``negate`` pairs (Opus review of PR #173, D1240).

``configs/negate_review.yaml`` lists, by ``pair_id``, the sentence pairs whose negation does not hit
the answer (``invalid``) and those that only weaken it or whose base does not answer the question
(``borderline``). ``report.py`` writes ``results/rq2/discrimination_sensitivity.csv`` without the
``invalid`` pairs. That table is a sensitivity analysis, reported only: the pass rule reads the full
``discrimination.csv`` (D146 unchanged).
"""

from pathlib import Path

import yaml
from rq2.rq2_config import REPO

from pruefstand.core.errors import ConfigError

REVIEW = REPO / "experiments/rq2/configs/negate_review.yaml"


def load_review(path: Path = REVIEW) -> dict[str, dict[str, str]]:
    """Return ``{"invalid": {pair_id: reason}, "borderline": {pair_id: reason}}``.

    Raises:
        ConfigError: The file is missing or not of that shape.
    """
    if not path.is_file():
        msg = f"{path.name} is missing"
        raise ConfigError(msg)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    groups = ("invalid", "borderline")
    if not isinstance(data, dict) or any(not isinstance(data.get(g), dict) for g in groups):
        msg = f"{path.name}: needs the mappings 'invalid' and 'borderline'"
        raise ConfigError(msg)
    return {g: {str(k): str(v) for k, v in data[g].items()} for g in groups}


def invalid_negations(path: Path = REVIEW) -> frozenset[str]:
    """Pair ids whose negation does not hit the answer (left out of the sensitivity table)."""
    return frozenset(load_review(path)["invalid"])
