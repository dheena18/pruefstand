"""Command line ``python -m pruefstand.ingest.eurlex`` (T2.4)."""

from pathlib import Path

import pytest

from pruefstand.ingest.eurlex_cli import main, pinned_celex

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eurlex"
CELEX = "32016R0679"


def make_tree(tmp_path: Path, sources: str | None) -> Path:
    raw = tmp_path / "data" / "raw" / "eurlex"
    (raw / CELEX).mkdir(parents=True)
    for lang in ("de", "en"):
        (raw / CELEX / f"{lang}.html").write_bytes((FIXTURES / f"gdpr_{lang}.html").read_bytes())
    if sources is not None:
        (tmp_path / "data" / "sources.yaml").write_text(sources, encoding="utf-8")
    return raw


def test_stats_line_and_exit_code_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    raw = make_tree(tmp_path, None)
    assert main([str(raw), "--stats"]) == 0
    out = capsys.readouterr().out
    assert "acts=1 langs=2 aligned_pairs=4 misaligned_acts=0" in out
    assert f"{CELEX}   DSGVO" in out


def test_a_pinned_act_without_files_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sources = (
        "sources:\n"
        f"- {{id: 'eurlex:{CELEX}', kind: eurlex, celex: '{CELEX}'}}\n"
        "- {id: 'eurlex:32024R1689', kind: eurlex, celex: '32024R1689'}\n"
        "- {id: 'gii:bgb', kind: gii, slug: bgb}\n"
    )
    raw = make_tree(tmp_path, sources)
    assert pinned_celex(raw) == [CELEX, "32024R1689"]
    assert main([str(raw)]) == 1
    assert "missing_act" in capsys.readouterr().err


@pytest.mark.parametrize("content", [None, ": : not yaml", "sources: 3", "- a"])
def test_unreadable_sources_file_means_no_expectations(tmp_path: Path, content: str | None) -> None:
    raw = make_tree(tmp_path, content)
    assert pinned_celex(raw) == []


def long_page(*, numbered: bool) -> bytes:
    words = " ".join(["Wort"] * 900)
    paras = ""
    for n in (1, 2):
        marker = f"({n}) " if numbered else ""
        paras += f'<div id="006.00{n}"><p class="oj-normal">{marker}{words}</p></div>'
    return (
        '<html><body><div id="art_6"><p class="oj-ti-art">Article 6</p>'
        f'<div class="eli-title"><p class="oj-sti-art">T</p></div>{paras}</div></body></html>'
    ).encode()


def test_act_whose_chunks_do_not_align_is_not_counted_as_aligned(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = tmp_path / "data" / "raw" / "eurlex" / CELEX
    raw.mkdir(parents=True)
    (raw / "de.html").write_bytes(long_page(numbered=True))
    (raw / "en.html").write_bytes(long_page(numbered=False))
    assert main([str(raw.parent), "--stats"]) == 1
    out = capsys.readouterr().out
    assert out.startswith("acts=0 langs=2 aligned_pairs=0 misaligned_acts=1")
