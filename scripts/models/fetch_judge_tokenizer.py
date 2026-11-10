"""Fetch the judge's pinned ``tokenizer.json`` (33 MB for gemma3, never committed), sha256-checked.

    uv run python scripts/models/fetch_judge_tokenizer.py [--id ollama/gemma3:12b] [--out FILE]

Run it once on the executor (and in the tier-2 image, T6.2a): without the file the exact judge-input
count is skipped and the run reports ``judge_exact_count_unavailable`` (D1010).
"""

import argparse
import sys
from pathlib import Path

from pruefstand.judges.exact_tokens import fetch_tokenizer, tokenizer_file


def main(argv: list[str] | None = None) -> int:
    """Download and verify the tokenizer; return the exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", dest="model_id", default="ollama/gemma3:12b")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    out = fetch_tokenizer(args.model_id, args.out)
    sys.stdout.write(f"{out} (default location {tokenizer_file(args.model_id)})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
