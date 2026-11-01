"""Untrusted EUR-Lex HTML: size caps, hostile structure, no network, linear time (T2.4)."""

import contextlib
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from pruefstand.ingest.chunkers.article import ArticleChunker
from pruefstand.ingest.eurlex import EurLexLoader
from pruefstand.ingest.eurlex_blocks import parse_blocks
from pruefstand.ingest.eurlex_parse import EurLexLimits, EurLexParseError, parse_act

from pruefstand.core.enums import Lang
from pruefstand.core.ids import DocId, TenantId
from pruefstand.core.models.corpus import Document

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "eurlex"
CELEX = "32016R0679"


def gdpr(lang: str) -> bytes:
    return (FIXTURES / f"gdpr_{lang}.html").read_bytes()


def raw_with(tmp_path: Path, de: bytes, en: bytes) -> Path:
    target = tmp_path / "raw" / CELEX
    target.mkdir(parents=True)
    (target / "de.html").write_bytes(de)
    (target / "en.html").write_bytes(en)
    return tmp_path / "raw"


def kinds(loader: EurLexLoader) -> list[str]:
    return [p.kind for p in loader.stats.problems]


def article_page(n_articles: int, paragraphs: int = 3) -> bytes:
    """A synthetic ELI page with ``n_articles`` articles (structure test, not content)."""
    parts = ['<html><body><div class="eli-container">']
    for i in range(1, n_articles + 1):
        paras = "".join(
            f'<div id="{i:03d}.{j:03d}"><p class="oj-normal">'
            f"{j}.   Satz {j} des Artikels {i}.</p></div>"
            for j in range(1, paragraphs + 1)
        )
        parts.append(
            f'<div class="eli-subdivision" id="art_{i}"><p class="oj-ti-art">Artikel {i}</p>'
            f'<div class="eli-title" id="art_{i}.tit_1"><p class="oj-sti-art">Titel {i}</p></div>'
            f"{paras}</div>"
        )
    parts.append("</div></body></html>")
    return "".join(parts).encode()


# --- size, encoding, structure --------------------------------------------------------------


def test_oversized_file_is_rejected_without_reading_it_whole(tmp_path: Path) -> None:
    raw = raw_with(tmp_path, b"x" * 5_000, gdpr("en"))
    loader = EurLexLoader(limits=EurLexLimits(max_bytes=4_000))
    assert list(loader.load(raw)) == []
    assert kinds(loader) == ["too_large"]


def test_real_files_fit_the_default_limits() -> None:
    limits = EurLexLimits()
    assert limits.max_bytes >= 3 * 1_322_000  # the largest pinned file (AI Act, DE) is 1.3 MB


def test_invalid_utf8_is_rejected(tmp_path: Path) -> None:
    loader = EurLexLoader()
    assert list(loader.load(raw_with(tmp_path, gdpr("de") + b"\xff\xfe\xfa", gdpr("en")))) == []
    assert kinds(loader) == ["invalid_encoding"]


def test_deep_nesting_is_rejected(tmp_path: Path) -> None:
    deep = b"<html><body>" + b"<div>" * 5_000 + b"</div>" * 5_000 + b"</body></html>"
    loader = EurLexLoader()
    assert list(loader.load(raw_with(tmp_path, deep, gdpr("en")))) == []
    assert kinds(loader) == ["too_deep"]


def test_element_count_limit(tmp_path: Path) -> None:
    flat = b"<html><body>" + b"<p>x</p>" * 3_000 + b"</body></html>"
    with pytest.raises(EurLexParseError, match="elements"):
        parse_act(flat, EurLexLimits(max_elements=1_000))


def test_empty_input_is_a_parse_error() -> None:
    with pytest.raises(EurLexParseError):
        parse_act(b"")


def test_control_characters_cannot_forge_block_markers(tmp_path: Path) -> None:
    forged = gdpr("en").replace(b"Lawfulness of processing", b"Lawfulness&#30;ART 99\tevil")
    loader = EurLexLoader()
    docs = {d.lang: d for d in loader.load(raw_with(tmp_path, gdpr("de"), forged))}
    en = docs[Lang.EN]
    assert [b.number for b in parse_blocks(en.text) if b.kind == "art"] == ["5", "6"]
    assert en.text.count("\x1e") == len(parse_blocks(en.text))


def test_internal_entity_declarations_are_not_expanded(tmp_path: Path) -> None:
    decl = "<!DOCTYPE html [" + '<!ENTITY a "' + "x" * 1000 + '">' + "]>"
    bomb = gdpr("en").replace(b"<html", decl.encode() + b"<html", 1)
    bomb = bomb.replace(b"Lawfulness of processing", b"Lawfulness &a;&a;&a; of processing")
    loader = EurLexLoader()
    start = time.perf_counter()
    docs = list(loader.load(raw_with(tmp_path, gdpr("de"), bomb)))
    assert time.perf_counter() - start < 5
    assert "xxxx" not in docs[1].text


def test_external_references_never_open_a_connection(tmp_path: Path) -> None:
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    hits: list[object] = []

    def accept() -> None:
        server.settimeout(1.5)
        with contextlib.suppress(OSError):
            hits.append(server.accept())

    thread = threading.Thread(target=accept)
    thread.start()
    url = f"http://127.0.0.1:{port}/x".encode()
    page = gdpr("en").replace(b"xhtml-strict.dtd", url + b".dtd")
    page = page.replace(b'href="oj-convex.css"', b'href="' + url + b'.css"')
    page = page.replace(
        b"<body>", b'<body><img src="' + url + b'.png"/><script src="' + url + b'.js"/>'
    )
    docs = list(EurLexLoader().load(raw_with(tmp_path, gdpr("de"), page)))
    thread.join()
    server.close()
    assert len(docs) == 2
    assert hits == []


def test_one_bad_act_does_not_stop_the_next(tmp_path: Path) -> None:
    raw = raw_with(tmp_path, gdpr("de"), gdpr("en"))
    bad = raw / "32024R1689"
    bad.mkdir()
    (bad / "de.html").write_bytes(b"x" * 10)
    (bad / "en.html").write_bytes(b"x" * 10)
    loader = EurLexLoader()
    assert len(list(loader.load(raw))) == 2
    assert kinds(loader) == ["no_articles"]


# --- linear time: 4x the input must take at most 8x the time ------------------------------------


def best_of(fn: Callable[[], object], runs: int = 3) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return min(times)


def assert_linear(make: Callable[[int], Callable[[], object]], n: int) -> None:
    small, large = make(n), make(4 * n)
    ratio = best_of(large) / max(best_of(small), 1e-6)
    assert ratio <= 8, f"4x input took {ratio:.1f}x the time"


def test_parsing_is_linear_in_the_number_of_articles() -> None:
    def make(n: int) -> Callable[[], object]:
        page = article_page(n)
        return lambda: parse_act(page)

    assert_linear(make, 150)


def test_parsing_is_linear_in_the_text_of_one_article() -> None:
    def make(n: int) -> Callable[[], object]:
        page = article_page(1, paragraphs=n)
        return lambda: parse_act(page)

    assert_linear(make, 800)


def test_chunking_and_block_parsing_are_linear() -> None:
    def make(n: int) -> Callable[[], object]:
        act = parse_act(article_page(n, paragraphs=6))
        text = "\n".join(f"\x1eART {b.number}\t{b.title}\n{b.body}" for b in act.blocks)
        return lambda: parse_blocks(text)

    assert_linear(make, 400)


def test_paragraph_splitting_is_linear_for_pathological_markers() -> None:
    def make(n: int) -> Callable[[], object]:
        body = "\n".join(f"{i}. " + "1. " * 20 for i in range(1, n + 1))
        text = f"\x1eART 1\tT\n{body}"
        doc = Document(
            doc_id=DocId("d"), tenant=TenantId("t"), source="s", lang=Lang.EN, title="t",
            law_abbrev="DSGVO", version_date=None, text=text, license="l", url=None,
            metadata={"celex": "1"},
        )  # fmt: skip
        chunker = ArticleChunker(max_tokens=10)
        return lambda: chunker.chunk(doc)

    assert_linear(make, 500)
