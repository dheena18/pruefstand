"""Approved private documents for tests: real templates, hand-written German body text.

The body is a plain test input (like the fixture laws); only the semantic fact comes from the
production fact templates, so the tests exercise the same regexes as the real corpus.
"""

from pathlib import Path

import numpy as np

from pruefstand.attacks.canary import TENANT_PREFIX
from pruefstand.attacks.facts import SemanticFact, make_semantic_fact
from pruefstand.ingest.private_docs import PrivateDocFront, render_private_doc

BODY = (
    "# {title}\n\n"
    "Diese Notiz hält den Stand der Zusammenarbeit fest. Die Abteilung hat die Unterlagen "
    "geprüft und die offenen Punkte mit der Leitung besprochen. Alle Beteiligten haben "
    "zugestimmt, dass die Angelegenheit intern weiterbearbeitet wird.\n\n"
    "{fact}\n\n"
    "Änderungen bedürfen der Schriftform. Rückfragen richten Sie bitte an das Sekretariat; "
    "die Unterlagen liegen in der Akte und werden vertraulich behandelt.\n"
)


def approved_text(tenant: str, number: int, seed: int = 7, taken: set[str] | None = None) -> str:
    """Return the text of one approved document file (front matter plus body)."""
    rng = np.random.default_rng([seed, number, sum(map(ord, tenant))])
    fact: SemanticFact = make_semantic_fact(tenant, number, rng, taken or set())
    tp = TENANT_PREFIX[tenant].lower()
    front = PrivateDocFront(
        doc_id=f"priv-{tp}-{number + 1:02d}",
        tenant=tenant,
        title=f"Notiz {number + 1} ({fact.doc_type})",
        semantic_fact=fact.sentence,
        semantic_value=fact.value,
        probe_question=fact.probe_question,
        forbidden_answer=fact.forbidden_answer,
    )
    body = BODY.format(title=front.title, fact=fact.sentence)
    return render_private_doc(front, body)


def write_approved(root: Path, per_tenant: int = 3) -> Path:
    """Write ``per_tenant`` approved documents for each customer tenant under ``root``."""
    taken: set[str] = set()
    for tenant in TENANT_PREFIX:
        folder = root / tenant
        folder.mkdir(parents=True, exist_ok=True)
        for number in range(per_tenant):
            text = approved_text(tenant, number, taken=taken)
            front_value = text.split("semantic_value: ", 1)[1].splitlines()[0].strip('"\x27')
            taken.add(front_value)
            name = text.split("doc_id: ", 1)[1].splitlines()[0]
            (folder / f"{name}.md").write_text(text, encoding="utf-8")
    return root
