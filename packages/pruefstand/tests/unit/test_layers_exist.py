import importlib

import pytest

LAYERS = [
    "core", "llm", "adapters", "metrics", "judges", "store", "ingest", "perturb",
    "attacks", "runner", "gate", "report", "dataset", "pipeline",
]  # fmt: skip


@pytest.mark.parametrize("name", [*LAYERS, "cli"])
def test_layer_imports(name: str) -> None:
    module = importlib.import_module(f"pruefstand.{name}")
    assert module.__doc__ is not None


def test_cli_is_a_package() -> None:
    module = importlib.import_module("pruefstand.cli")
    assert hasattr(module, "__path__")


def test_llm_backends_package_exists() -> None:
    assert importlib.import_module("pruefstand.llm.backends").__doc__ is not None
