"""T3.4b: fixed-token sub-chunking on real law text (corpus/slice_v1) and the config contract."""

import hashlib
import json
import re

import pytest
from pydantic import ValidationError
from rd_support import CONFIGS, FIXTURE_CORPUS

from rag_demo.config import config_hash, load_config, prompt_path
from rag_demo.errors import ConfigError
from rag_demo.index import subchunk
from rag_demo.index.corpus_reader import index_text
from rag_demo.index.subchunk import ABBREVIATIONS, sentence_ends, split_rows, split_text
from rag_demo.index.tokens import approx_token_count
from rag_demo.models import ChunkingCfg, RagConfig

CORPUS = FIXTURE_CORPUS / "kanzlei_mueller.chunks.jsonl"
ROWS = [json.loads(line) for line in CORPUS.read_text(encoding="utf-8").splitlines()]
KSCHG = next(
    r for r in ROWS if r["chunk_id"] == "gii-kschg-1#1"
)  # real § 1 KSchG, 1 878 characters
count = approx_token_count


def fixed(size: int) -> ChunkingCfg:
    return ChunkingCfg(strategy="fixed_tokens", size=size)


def naive_split(text: str, budget: int) -> list[str]:
    """The tempting implementation: cut at the last '. ' that fits."""
    pieces, rest = [], text
    while count(rest) > budget:
        window = rest[: len(" ".join(rest.split()[:budget]))]
        cut = window.rfind(". ")
        cut = cut + 1 if cut > len(window) // 2 else len(window)
        pieces.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    return [*pieces, rest]


def test_per_section_returns_the_rows_unchanged() -> None:
    assert split_rows(ROWS, ChunkingCfg(), count) == ROWS


def test_a_long_paragraph_is_cut_into_pieces_within_the_budget() -> None:
    rows = split_rows([KSCHG], fixed(128), count)
    assert len(rows) > 1
    assert [r["chunk_id"] for r in rows] == [f"gii-kschg-1#1#p{n}" for n in range(len(rows))]
    for row in rows:
        assert count(index_text(row)) <= 128  # the citation key is inside the budget
        assert row["doc_id"] == KSCHG["doc_id"]
        assert row["tenant"] == KSCHG["tenant"]
        assert row["citation_key"] == KSCHG["citation_key"]
    joined = " ".join(" ".join(r["text"].split()) for r in rows)
    assert joined == " ".join(KSCHG["text"].split())  # nothing lost, nothing added, no overlap


def test_a_short_chunk_keeps_its_id_and_text() -> None:
    short = next(r for r in ROWS if count(index_text(r)) <= 128)
    assert split_rows([short], fixed(128), count) == [short]


def test_the_citation_key_is_never_part_of_the_piece_text() -> None:
    key = str(KSCHG["citation_key"])
    for row in split_rows([KSCHG], fixed(96), count):
        assert not row["text"].startswith(key)
        assert index_text(row).startswith(f"{key}\n")  # but it is embedded with every piece


def test_the_cut_prefers_a_sentence_end_in_the_second_half() -> None:
    text = "Eins zwei. Drei vier fünf sechs sieben. Acht neun zehn elf zwölf."
    assert split_text(text, 12, count)[0] == "Eins zwei. Drei vier fünf sechs sieben."
    # a sentence end in the FIRST half of the window is not used: the window is cut hard
    early = "Eins zwei drei vier. Fünf sechs sieben acht neun zehn elf zwölf."
    assert (
        split_text(early, 12, count)[0]
        == "Eins zwei drei vier. Fünf sechs sieben acht neun zehn elf"
    )
    hard = split_text("Ein sehr langer Satz ohne irgendein Satzende bis zum Ende hin", 5, count)
    assert all(count(p) <= 5 for p in hard)
    assert " ".join(hard) == "Ein sehr langer Satz ohne irgendein Satzende bis zum Ende hin"


@pytest.mark.parametrize("size", range(64, 200, 7))
def test_real_paragraph_pieces_never_end_after_a_legal_abbreviation(size: int) -> None:
    for row in split_rows([KSCHG], fixed(size), count)[:-1]:
        last = row["text"].split()[-1]
        assert last.rstrip(".").lower() not in ABBREVIATIONS or not last.endswith("."), (size, last)


def test_a_naive_period_split_cuts_after_abbreviations_where_ours_does_not() -> None:
    text = str(KSCHG["text"])
    bad = []
    for size in range(40, 120):
        naive = naive_split(text, size)
        bad += [p for p in naive[:-1] if re.search(r"\b(Abs|Nr|S|Art)\.$", p)]
        ours = split_text(text, size, count)
        assert not any(re.search(r"\b(Abs|Nr|S|Art)\.$", p) for p in ours[:-1]), size
    assert bad, "the naive split should be wrong somewhere on this real § text"


def test_ordinals_and_list_markers_are_no_sentence_ends() -> None:
    text = (
        "wenn die Vergütung am 15. eines Monats fällig ist;\n3. wenn nichts gilt. Danach endet es."
    )
    ends = [text[:e] for e in sentence_ends(text)]
    assert ends == [text[: text.index("Danach") - 1], text]


def test_a_key_that_fills_the_budget_is_refused() -> None:
    row = {**KSCHG, "citation_key": "x " * 100}
    with pytest.raises(ConfigError, match="no room"):
        split_rows([row], fixed(64), count)


def test_chunking_config_contract() -> None:
    assert RagConfig.model_fields["chunking"].default_factory is ChunkingCfg
    with pytest.raises(ValidationError):
        ChunkingCfg(strategy="per_section", size=512)
    with pytest.raises(ValidationError):
        ChunkingCfg(strategy="fixed_tokens")
    for bad in (32, 8192):
        with pytest.raises(ValidationError):
            fixed(bad)


def test_the_default_chunking_leaves_every_config_hash_unchanged() -> None:
    cfg = load_config(CONFIGS / "rag.yaml")
    legacy = RagConfig.model_construct(**{k: getattr(cfg, k) for k in cfg.model_fields_set})
    assert cfg.chunking == ChunkingCfg()
    other = cfg.model_copy(update={"chunking": fixed(512)})
    assert config_hash(other) != config_hash(cfg)
    dump = cfg.model_dump(mode="json")
    del dump["chunking"], dump["public_mode"], dump["public"]  # fields added later (T3.4b, T8.4)
    canonical = json.dumps(dump, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode())
    digest.update(b"\0")
    digest.update(prompt_path(cfg.prompt_file).read_bytes())
    assert config_hash(cfg) == digest.hexdigest()[:16]  # = the hash before the field existed
    assert legacy is not None


def test_a_long_chunk_is_split_in_linear_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    """No quadratic lookback: every abbreviation search sees a bounded window (no wall clock)."""
    seen: list[int] = []
    real = subchunk._WORD_BEFORE

    class Spy:
        def search(self, text: str, pos: int = 0, endpos: int = 10**9) -> re.Match[str] | None:
            seen.append(min(endpos, len(text)) - pos)
            return real.search(text, pos, endpos)

    monkeypatch.setattr(subchunk, "_WORD_BEFORE", Spy())
    long_text = " ".join([str(KSCHG["text"])] * 20)  # about 37 000 characters of real law text
    pieces = split_text(long_text, 128, count)
    assert len(pieces) > 30
    assert seen
    assert max(seen) <= subchunk.LOOKBACK
