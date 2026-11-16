"""Pinned datagen models and prompt versions of QA generation (T4.2 S0, D780, D1201).

Two backends, chosen by ``PRUEFSTAND_DATAGEN_BACKEND`` (``PruefstandSettings.datagen_backend``):

- ``vm`` (default since D1201): the on-demand CPU model on the VM (``scripts/models/vm_llm.sh``,
  official Mistral GGUF, 14B default and 8B, SHA-256 pinned there, D1200), served by llama.cpp
  under the alias = the model part of the id; family ``mistral``. The VM has no second family, so
  ``--cross-check`` has no VM default (the pass-2 local judge stays the independent check).
- ``github``: the GitHub Models catalogue ids (retired 2026-07-30; kept so old cassettes and
  ledgers stay readable). Families ``gpt`` (datagen) and ``llama`` (cross-check).

Changing a pin is a decision file ``docs/decisions/D<n>.md``, not a code change elsewhere. No pin
is the generator family ``qwen`` or the judge family ``gemma`` (``core/data/model_families.yaml``).
"""

from pruefstand.core.settings import DatagenBackend

DATAGEN_MODEL = "github/openai/gpt-4.1-mini"
CROSS_CHECK_MODEL = "github/meta/Llama-3.3-70B-Instruct"
VM_DATAGEN_MODEL = "openai_compatible_local/ministral-3-14b-instruct-2512"
VM_DATAGEN_MODELS = frozenset(
    {VM_DATAGEN_MODEL, "openai_compatible_local/ministral-3-8b-instruct-2512"}
)
PROMPT_VERSIONS = {
    "factual": "qa_factual_de_v1",
    "comparison": "qa_comparison_de_v1",
    "multi_hop": "qa_multi_hop_de_v1",
    "cross_lingual": "qa_cross_lingual_de_v1",
}
PASS2_PROMPT_VERSION = "qa_validate_de_v1"


def datagen_model(backend: DatagenBackend) -> str:
    """Return the pinned datagen model id of ``backend``.

    Args:
        backend: ``vm`` or ``github``.

    Returns:
        The model id (``<provider>/<model>``).

    Examples:
        >>> datagen_model("vm")
        'openai_compatible_local/ministral-3-14b-instruct-2512'
        >>> datagen_model("github")
        'github/openai/gpt-4.1-mini'
    """
    return VM_DATAGEN_MODEL if backend == "vm" else DATAGEN_MODEL
