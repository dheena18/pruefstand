"""Pinned datagen models and prompt versions of QA generation (T4.2 S0, D780).

The ids are the GitHub Models catalogue ids behind provider ``github``. They are PROVISIONAL until
the first successful call by the owner's token confirms them (``models.github.ai`` is not
reachable from the VM, D604); changing a pin is a row in ``docs/decisions.md``, not a code change
elsewhere. Families come from ``core/data/model_families.yaml`` (datagen: ``gpt``; cross-check:
``llama``; neither is the generator family ``qwen`` nor the judge family ``gemma``).
"""

DATAGEN_MODEL = "github/openai/gpt-4.1-mini"
CROSS_CHECK_MODEL = "github/meta/Llama-3.3-70B-Instruct"
PROMPT_VERSIONS = {
    "factual": "qa_factual_de_v1",
    "comparison": "qa_comparison_de_v1",
    "multi_hop": "qa_multi_hop_de_v1",
    "cross_lingual": "qa_cross_lingual_de_v1",
}
PASS2_PROMPT_VERSION = "qa_validate_de_v1"
