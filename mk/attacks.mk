# T2.6: held-out canary set (private; never committed, never in the public repo).
#   HELDOUT_SEED=<secret, at least 128 bits, e.g. openssl rand -hex 32> make heldout-canaries
# Reads the approved documents in datasets/private_docs/<tenant>/ and writes the git-ignored
# datasets/private/heldout/ (docs/*.md + canaries_heldout.json). Copy that folder by hand to the
# private executor repo (canaries/heldout/); the seed stays a secret there (docs/ops/secrets.md).
.PHONY: heldout-canaries

heldout-canaries:
	uv run python scripts/make_heldout_canaries.py --seed-env HELDOUT_SEED
