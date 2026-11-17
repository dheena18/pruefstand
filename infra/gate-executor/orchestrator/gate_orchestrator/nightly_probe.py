"""The nightly contamination-probe phase (T4.6 S7, T6.2b S4; informational, D1099).

After the gate phase the generator of main's ``rag.gpu.yaml`` is asked the retired semantic
canaries closed-book (``scripts/contamination_probe.py`` of the pinned main worktree, under the
held GPU lock). It never gates: its exit code is reported in the summary only, and the report
file (counts and one yes/no per canary, never answer text) lands in the night's report directory.
"""

from collections.abc import Mapping
from pathlib import Path

import yaml

PLANNED_MINUTES = 10.0


def probe_model(rag_gpu: Mapping[str, object], catalogue: Mapping[str, object]) -> tuple[str, str]:
    """``(model id, family)`` of the generator main's ``rag.gpu.yaml`` names.

    Raises:
        ValueError: the generator is not a catalogue ``generator`` entry.
    """
    generator = rag_gpu.get("generator")
    wanted = generator.get("catalogue_id") if isinstance(generator, Mapping) else None
    models = catalogue.get("models")
    for model in models if isinstance(models, list) else []:
        if (
            isinstance(model, Mapping)
            and model.get("id") == wanted
            and model.get("role") == "generator"
        ):
            return str(model["id"]), str(model.get("family", ""))
    msg = f"main's rag.gpu.yaml generator {wanted!r} is not a catalogue generator"
    raise ValueError(msg)


def probe_argv(main_dir: Path, out_dir: Path) -> list[str]:
    """``python scripts/contamination_probe.py --model .. --family .. --out-dir <night report>``."""
    rag = yaml.safe_load(
        (main_dir / "apps" / "rag-demo" / "configs" / "rag.gpu.yaml").read_text("utf-8")
    )
    catalogue = yaml.safe_load((main_dir / "infra" / "gpu" / "models.yaml").read_text("utf-8"))
    model, family = probe_model(rag, catalogue)
    script = main_dir / "scripts" / "contamination_probe.py"
    return ["python", str(script), "--model", model, "--family", family, "--out-dir", str(out_dir)]
