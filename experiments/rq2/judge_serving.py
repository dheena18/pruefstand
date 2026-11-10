"""Serving version of a pinned judge for ``calibration_status.yaml`` (X3.3, AI11-09)."""

from pruefstand.pipeline.fingerprints import judge_serving


def serving(judge: str) -> str:
    """``engine tag quantization digest[:12]`` from the catalogue; GitHub Models: the id."""
    return judge_serving(judge) or judge
