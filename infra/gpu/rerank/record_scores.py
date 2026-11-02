"""Record the scores of the REAL reranker for ``tests/test_rerank_app.py`` (ADR-0008).

Run once on the VM (needs torch + sentence-transformers and the model download; not part of
``make check``):

  PYTHONPATH=infra/gpu python infra/gpu/rerank/record_scores.py \
      --out infra/gpu/tests/fixtures/rerank_recorded.json

Uses the same ``CrossEncoderScorer`` and the same pinned revision as the service, with the 256-token
limit.
"""

import argparse
import json
from pathlib import Path

from rerank.rerank_app import MAX_TOKENS_TRUNCATED, CrossEncoderScorer

MODEL = "BAAI/bge-reranker-v2-m3"
REVISION = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"
TEXTS = [
    "Das Arbeitsverhältnis eines Arbeiters oder eines Angestellten (Arbeitnehmers) kann mit einer"
    " Frist von vier Wochen zum Fünfzehnten oder zum Ende eines Kalendermonats gekündigt werden."
    " (§ 622 Abs. 1 BGB)",
    "Die Kündigung ist spätestens am dritten Werktag eines Kalendermonats zum Ablauf des"
    " übernächsten Monats zulässig. (§ 573c Abs. 1 BGB, Wohnraummiete)",
    "Die regelmäßige Verjährungsfrist beträgt drei Jahre. (§ 195 BGB)",
    "Der Arbeitnehmer hat bei Beendigung eines Arbeitsverhältnisses Anspruch auf ein schriftliches"
    " Zeugnis. (§ 109 Abs. 1 GewO)",
]
QUERIES = [
    ("Wie lang ist die Kündigungsfrist für Arbeitnehmer?", 0),
    ("Nach wie vielen Jahren verjähren Ansprüche regelmäßig?", 2),
]


def main() -> None:
    """Score every (query, passage) pair with the real model and write the fixture."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    scorer = CrossEncoderScorer(MODEL, REVISION)
    cases = [
        {
            "query": query,
            "texts": TEXTS,
            "relevant": relevant,
            "scores": scorer.score(query, TEXTS, MAX_TOKENS_TRUNCATED),
        }
        for query, relevant in QUERIES
    ]
    payload = {
        "model": MODEL,
        "revision": REVISION,
        "max_tokens": MAX_TOKENS_TRUNCATED,
        "cases": cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
