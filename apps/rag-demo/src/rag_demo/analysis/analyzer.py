"""``GermanAnalyzer``: NFC, abbreviations, numbers, stopwords, compound split, folding, stemming."""

import sys
from collections.abc import Sequence
from importlib import resources
from threading import Lock
from typing import Literal

import snowballstemmer  # type: ignore[import-untyped]  # the package ships no stubs

from rag_demo.analysis import compound
from rag_demo.analysis.abbreviations import expand_abbreviations
from rag_demo.analysis.normalise import fold, nfc_lower, normalise_numbers, tokenise

_MEMO_LIMIT = 50_000
_MAX_STEM_LEN = 64  # longer tokens are left as they are (bounded work per token)


def _load_stopwords() -> frozenset[str]:
    text = (resources.files("rag_demo.analysis") / "stopwords_de.txt").read_text(encoding="utf-8")
    words = {line.strip() for line in text.splitlines() if line.strip()}
    return frozenset(words | {fold(w) for w in words})


_STOPWORDS = _load_stopwords()


class GermanAnalyzer:
    """Turn German text into search tokens, identically on the index and the query side.

    Pipeline: NFC + lowercase, function abbreviations (``abs.`` -> ``absatz``), German number
    format and ``€`` -> ``eur``, tokenise (keeps ``§`` and numbers), drop Snowball stopwords,
    compound split (original token first, then its parts), optional ä/ö/ü/ß folding, stemming.

    Args:
        compound_split: Emit the parts of dictionary compounds besides the compound (mutation M4
            turns this off).
        stemmer: ``"snowball_de"`` or ``"none"``.
        fold_umlauts: Fold ä, ö, ü, ß to ae, oe, ue, ss so "Gebühren" matches "Gebuehren". With
            ``stemmer="snowball_de"`` the flag has no effect: Snowball German folds umlauts itself.
    """

    def __init__(
        self,
        compound_split: bool,  # noqa: FBT001  (signature fixed by interfaces.md §16)
        stemmer: Literal["snowball_de", "none"],
        fold_umlauts: bool = True,  # noqa: FBT001, FBT002
    ) -> None:
        self.compound_split = compound_split
        self.stemmer = stemmer
        self.fold_umlauts = fold_umlauts
        self._stem = snowballstemmer.stemmer("german") if stemmer == "snowball_de" else None
        self._memo: dict[str, str] = {}
        self._lock = Lock()  # the Snowball stemmer instance keeps state while it runs

    def tokens(self, text: str) -> list[str]:
        """Return the search tokens of ``text``.

        Args:
            text: Any text; never raises.

        Returns:
            Tokens in text order, a compound followed by its parts.

        Examples:
            >>> GermanAnalyzer(False, "none").tokens("Straße & Gebühren")
            ['strasse', 'gebuehren']
            >>> GermanAnalyzer(True, "none").tokens("Kündigungsschutzgesetz")
            ['kuendigungsschutzgesetz', 'kuendigung', 'schutz', 'gesetz']
            >>> GermanAnalyzer(False, "none").tokens("1.000,50 €")
            ['1000.50', 'eur']
        """
        prepared = normalise_numbers(expand_abbreviations(nfc_lower(text))).replace("€", " eur ")
        words = [t for t in tokenise(prepared) if t not in _STOPWORDS]
        if self.compound_split:
            words = [piece for word in words for piece in self._pieces(word)]
        if self.fold_umlauts:
            words = [fold(word) for word in words]
        return [self._stemmed(word) for word in words]

    @staticmethod
    def _pieces(word: str) -> list[str]:
        parts = compound.split(word)
        return [word] if parts == [word] else [word, *parts]

    def _stemmed(self, word: str) -> str:
        if self._stem is None or not word.isalpha() or len(word) > _MAX_STEM_LEN:
            return word
        with self._lock:
            cached = self._memo.get(word)
            if cached is None:
                if len(self._memo) >= _MEMO_LIMIT:
                    self._memo.clear()
                cached = self._memo[word] = str(self._stem.stemWord(word))
            return cached


def main(argv: Sequence[str] | None = None) -> int:
    """Print the token list of the text given as argument (the defaults of ``rag.yaml``)."""
    args = list(sys.argv[1:] if argv is None else argv)
    analyzer = GermanAnalyzer(compound_split=True, stemmer="snowball_de")
    sys.stdout.write(f"{analyzer.tokens(' '.join(args))}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
