"""``SparseEncoder``: hashed vocabulary and BM25 term weights (IDF is applied by Qdrant)."""

from collections import Counter, defaultdict

import xxhash

from rag_demo.models import SparseVector


def token_index(token: str, dim: int) -> int:
    """Return the stable vocabulary index ``xxhash64(token) mod dim`` (same in every process)."""
    return xxhash.xxh64_intdigest(token.encode("utf-8")) % dim


class SparseEncoder:
    """Encode tokens as a sparse vector in a hashed vocabulary of ``dim`` slots.

    Documents get the BM25 term-frequency part ``tf (k1+1) / (tf + k1 (1 - b + b dl/avgdl))``;
    the collection's ``modifier: idf`` multiplies the IDF at query time. Queries get weight 1.

    Args:
        dim: Vocabulary size (hash buckets); 2**31 by default (T3.3).
        k1: BM25 saturation.
        b: BM25 length normalisation.
        avg_len: Assumed average document length in tokens.
    """

    def __init__(
        self, dim: int = 1 << 31, k1: float = 1.2, b: float = 0.75, avg_len: float = 60.0
    ) -> None:
        self.dim = dim
        self.k1 = k1
        self.b = b
        self.avg_len = avg_len

    def encode(self, tokens: list[str]) -> SparseVector:
        """Document-side vector.

        Examples:
            >>> v = SparseEncoder().encode(["frist", "frist", "woche"])
            >>> len(v.indices), round(max(v.values), 3)
            (2, 1.876)
        """
        length = len(tokens)
        weights: defaultdict[int, float] = defaultdict(float)
        for token, tf in Counter(tokens).items():
            norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_len)
            weights[token_index(token, self.dim)] += tf * (self.k1 + 1) / norm
        indices = sorted(weights)
        return SparseVector(indices=indices, values=[weights[i] for i in indices])

    def encode_query(self, tokens: list[str]) -> SparseVector:
        """Query-side vector: weight 1.0 for every distinct token."""
        indices = sorted({token_index(t, self.dim) for t in tokens})
        return SparseVector(indices=indices, values=[1.0] * len(indices))
