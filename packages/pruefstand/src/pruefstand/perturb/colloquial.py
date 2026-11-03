"""``colloquial``: the model alone turns a formal legal question into everyday speech (T4.5).

"Unter welchen Voraussetzungen ist eine ordentliche Kündigung durch den Arbeitgeber zulässig?"
becomes "Wann darf mein Chef mich rauswerfen?". The validity check rejects new numbers or
paragraphs and a lost question.
"""

from typing import override

import numpy as np

from pruefstand.core.protocols import LLMClientLike
from pruefstand.perturb.draft import Draft
from pruefstand.perturb.llm_base import LLMRewritePerturbation


class Colloquial(LLMRewritePerturbation):
    """Rewrite a question in colloquial German."""

    name = "colloquial"

    @override
    async def adraft(self, text: str, llm: LLMClientLike, rng: np.random.Generator) -> Draft | None:
        """Return the colloquial rewrite (always one model call)."""
        out = await self.rewriter.rewrite(llm, "colloquial_de", question=text)
        return Draft(text=out.text, model=out.model, local=out.local, used_llm=True)
