# Licences of the drift-anchor files

The `*.jsonl` files here are data, not code: the MIT licence of `pruefstand` does not cover them.
Every row names its source in `label_set` (T5.4, D946; `DATA_LICENSES.md` §11).

| `label_set` | Source | Licence | Attribution |
| --- | --- | --- | --- |
| `correctness`, `consistency` | GermanQuAD test split | CC BY 4.0 | GermanQuAD by deepset (Möller, Risch, Pietsch, 2021). Modified (answers paired, edited, framed; rendered into a judge prompt). |
| `faithfulness_constructed`, `refusal` | GermanRAG (based on GermanDPR) | CC BY-SA 4.0 | GermanRAG by DiscoResearch, based on GermanDPR. Modified (answers edited, hedged, paired; rendered into a judge prompt). The GermanRAG rows of these files are shared under CC BY-SA 4.0. |

The prompt text around the inputs is part of `pruefstand` (MIT).

Sources and licence texts:

- GermanQuAD: https://huggingface.co/datasets/deepset/germanquad (paper: https://arxiv.org/abs/2104.12741);
  CC BY 4.0: https://creativecommons.org/licenses/by/4.0/
- GermanRAG: https://huggingface.co/datasets/DiscoResearch/germanrag, based on GermanDPR
  (https://huggingface.co/datasets/deepset/germandpr); CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/
