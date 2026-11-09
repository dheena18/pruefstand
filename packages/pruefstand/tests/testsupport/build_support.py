"""Inputs of the ``build_dataset`` tests (T4.7a): real slice chunks, hand-written questions.

The questions and answers below are written by hand for real chunks of ``corpus/slice_v1``; the
citation and the verbatim evidence span are taken from the chunk text. They stand in for the output
of the datagen model ONLY in the offline orchestration test (no generation model is involved);
the live test (``tests/e2e/test_build_dataset_live.py``) generates its candidates with real models.
"""

import re
from collections.abc import Sequence
from pathlib import Path

from testsupport.embed_cassette import recorded_embedder
from testsupport.qa_support import SLICE, slice_chunks

from pruefstand.core.config import SplitPlan
from pruefstand.core.models.corpus import Chunk
from pruefstand.core.models.dataset import QACandidate
from pruefstand.pipeline.build_clients import BuildClients

PROMPT = "qa_factual_de_v1"
# (chunk id, question, answer): questions share no six-word run with the chunk (T4.3 copy rule)
QA = (
    ("gii-arbzg-3#0", "Wie viele Stunden darf ich an einem normalen Werktag höchstens arbeiten?",
     "Acht Stunden; bis zu zehn Stunden, wenn es im Durchschnitt wieder ausgeglichen wird."),
    ("gii-arbzg-4#0", "Wie lang muss meine Pause sein, wenn ich acht Stunden am Tag arbeite?",
     "Mindestens 30 Minuten."),
    ("gii-arbzg-5#0", "Wie viel Zeit muss zwischen zwei Arbeitstagen mindestens frei bleiben?",
     "Mindestens elf Stunden ununterbrochene Ruhezeit."),
    ("gii-kschg-3#0", "Binnen welcher Frist kann ich beim Betriebsrat Einspruch einlegen?",
     "Innerhalb einer Woche nach der Kündigung."),
    ("gii-kschg-4#0", "Wie schnell muss ich nach einer schriftlichen Kündigung klagen?",
     "Innerhalb von drei Wochen nach Zugang der schriftlichen Kündigung, beim Arbeitsgericht."),
    ("gii-bgb-620#0", "Wann endet ein befristeter Dienstvertrag von selbst?",
     "Mit dem Ablauf der Zeit, für die er eingegangen ist."),
    ("gii-bgb-622#0", "Welche Grundkündigungsfrist gilt für Beschäftigte?",
     "Vier Wochen zum Fünfzehnten oder zum Ende eines Kalendermonats."),
    ("gii-bgb-622#2", "Mit welcher Frist kann man in der Probezeit kündigen?",
     "Mit einer Frist von zwei Wochen."),
    ("gii-bgb-623#0", "Reicht eine E-Mail, um ein Arbeitsverhältnis zu beenden?",
     "Nein, die Kündigung braucht die Schriftform; die elektronische Form ist ausgeschlossen."),
    ("gii-bgb-626#0", "Wann ist eine fristlose Kündigung möglich?",
     "Bei einem wichtigen Grund, der die Fortsetzung bis zum Fristende unzumutbar macht."),
    ("gii-bdsg-26#5", "Behält der Betriebsrat bei Beschäftigtendaten seine Mitbestimmung?",
     "Ja, die Beteiligungsrechte der Interessenvertretungen bleiben unberührt."),
    ("eurlex-32016r0679-art-5-de#1",
     "Muss ein Unternehmen die Einhaltung der Datenschutzgrundsätze belegen können?",
     "Ja, der Verantwortliche muss die Einhaltung nachweisen können."),
)  # fmt: skip
_MARKER = re.compile(r"^\((\d+[a-z]?)\)\s+")


def candidate(chunk: Chunk, question: str, answer: str) -> QACandidate:
    """Return the candidate for ``chunk``: its citation and the first sentence as evidence."""
    head = _MARKER.match(chunk.text)
    sentence = chunk.text[head.end() if head else 0 :].split(". ")[0].strip()
    sentence = sentence if sentence.endswith((".", ";", ":")) else sentence + "."
    sentence = " ".join(sentence.split()[:40])
    key = chunk.citation_key or ""
    law = key.split(" ")
    cite = key
    if head:
        cite = f"{law[0]} {law[1]} Abs. {head.group(1)} {' '.join(law[2:])}"
    return QACandidate(
        question=question, answer=answer, citation=cite, chunk_id=chunk.chunk_id,
        prompt_version=PROMPT, evidence_span=sentence, style="laie",
    )  # fmt: skip


def candidates() -> list[QACandidate]:
    """The twelve hand-written candidates over real chunks."""
    chunks = slice_chunks()
    return [candidate(chunks[cid], q, a) for cid, q, a in QA]


def write_candidates(path: Path, cands: Sequence[QACandidate] | None = None) -> Path:
    """Write ``candidates.jsonl`` (the format of ``scripts/generate_qa.py``) and return it."""
    rows = cands if cands is not None else candidates()
    path.write_text("".join(c.model_dump_json() + "\n" for c in rows), encoding="utf-8")
    return path


def offline_clients() -> BuildClients:
    """Clients that refuse every model call; embeddings replay recorded bge-m3 answers."""

    def refuse(*_args: object) -> object:
        msg = "the offline build test makes no model call"
        raise AssertionError(msg)

    return BuildClients(datagen=refuse, local=refuse, embed=lambda _cfg: recorded_embedder())  # type: ignore[arg-type]


def small_plan() -> SplitPlan:
    """A plan that fits the twelve candidates plus the attack and refusal cases of the slice."""
    return SplitPlan.model_validate(
        {
            "smoke_size": 4, "smoke_min_per_category": 1,
            "core_answerable": 4, "core_unanswerable": 2, "core_injection": 0,
            "core_min_cross_lingual": 0, "core_min_answerable_clusters": 0,
            "min_clusters_per_tenant": 0, "judged_subset_size": 3,
            "robust_pr_bases": 2, "robust_pr_min_bases_per_type": 0, "robust_pr_min_perturbed": 0,
            "robust_pr_types": (), "full_refusal": 0, "full_block_unperturbed": 0,
            "full_block_perturbed": 0, "rq1_bases": 0,
        }
    )  # fmt: skip


SLICE_DIR = SLICE
