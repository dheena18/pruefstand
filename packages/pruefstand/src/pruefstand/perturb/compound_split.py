"""``compound_split``: a rule finds long compounds, the model paraphrases them (T4.5).

"Kündigungsschutzgesetz" becomes "Gesetz zum Schutz vor Kündigungen". A compound with no natural
paraphrase ("Rahmenvertrag") stays, and a text where the model changes nothing is ``unchanged``.
"""

import re
from functools import cache
from pathlib import Path
from typing import override

import numpy as np
import yaml

from pruefstand.core.protocols import LLMClientLike
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.llm_base import LLMRewritePerturbation

MIN_LENGTH = 10
_WORD = re.compile(rf"\b[A-ZÄÖÜ][a-zäöüß]{{{MIN_LENGTH - 1},}}\b")
_MIN_MODIFIER = 4
_HEADS_FILE = Path(__file__).resolve().parent / "data" / "compound_heads.yaml"


@cache
def _heads() -> tuple[str, ...]:
    data = yaml.safe_load(_HEADS_FILE.read_text(encoding="utf-8"))
    return tuple(str(h) for h in data["heads"])


def find_compounds(text: str) -> tuple[str, ...]:
    """Return the distinct compound candidates of ``text`` in order of appearance.

    A candidate is a capitalised word of at least 10 letters that ends in a legal head word
    (``data/compound_heads.yaml``) with at least four letters in front of it.

    Examples:
        >>> find_compounds("Gilt das Kündigungsschutzgesetz für Kleinbetriebe?")
        ('Kündigungsschutzgesetz',)
        >>> find_compounds("Wie lang ist die Frist?")
        ()
    """
    found: dict[str, None] = {}
    for word in _WORD.findall(text):
        lower = word.lower()
        if any(lower.endswith(h) and len(lower) >= len(h) + _MIN_MODIFIER for h in _heads()):
            found[word] = None
    return tuple(found)


class CompoundSplit(LLMRewritePerturbation):
    """Paraphrase long compounds into analytic phrases."""

    name = "compound_split"

    @override
    async def adraft(self, text: str, llm: LLMClientLike, rng: np.random.Generator) -> Draft | None:
        """Return the paraphrased question, or None without a compound (no model call)."""
        compounds = find_compounds(text)
        if not compounds:
            return None
        out = await self.rewriter.rewrite(
            llm, "compound_split_de", question=text, compounds=", ".join(compounds)
        )
        return Draft(
            text=out.text, model=out.model, local=out.local, used_llm=True, targets=compounds
        )
