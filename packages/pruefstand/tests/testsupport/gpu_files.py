"""Temp ``endpoints.yaml`` / ``models.yaml`` for the A40 tests, and the shipped catalogue path."""

from collections.abc import Mapping
from pathlib import Path

import yaml

SHIPPED_CATALOGUE = Path(__file__).resolve().parents[4] / "infra" / "gpu" / "models.yaml"
SHIPPED_ENDPOINTS = Path(__file__).resolve().parents[4] / "infra" / "gpu" / "endpoints.yaml"
OPTIONS = {"num_ctx": 4096, "num_predict": 77, "temperature": 0.0, "seed": 7, "top_p": 1.0}


def write_catalogue(path: Path, entries: Mapping[str, Mapping[str, object]]) -> Path:
    """Write a catalogue with one ollama entry per ``{id: options}``."""
    models = [
        {"id": mid, "engine": "ollama", "tag": mid.removeprefix("ollama/"), "options": opts}
        for mid, opts in entries.items()
    ]
    path.write_text(yaml.safe_dump({"models": models}), encoding="utf-8")
    return path


def write_endpoints(path: Path, mapping: dict[str, tuple[str, str]]) -> Path:
    """Write ``{service: (base_url_env, model_id)}`` as an endpoints file."""
    endpoints = {
        name: {"base_url_env": env, "model_id": mid, "family": "x", "kind": "chat"}
        for name, (env, mid) in mapping.items()
    }
    path.write_text(yaml.safe_dump({"endpoints": endpoints}), encoding="utf-8")
    return path
