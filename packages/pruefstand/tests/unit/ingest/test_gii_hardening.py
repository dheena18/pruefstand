"""Untrusted-input hardening of the GII loader (T2.2): XML bombs, XXE, network, zip tricks."""

import contextlib
import socket
import stat
import threading
import time
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
from lxml import etree

from pruefstand.ingest.gii.errors import GiiError, GiiParseError, UnsafeArchiveError, UnsafeXmlError
from pruefstand.ingest.gii.safezip import ZipLimits, check_member, read_bounded, read_xml_members
from pruefstand.ingest.gii.xmlparse import XmlLimits, hardened_parser, iter_norms
from pruefstand.ingest.gii_xml import GiiXmlLoader

RawFactory = Callable[[Mapping[str, Mapping[str, bytes]]], Path]
MARKER = "TOPMARKER-4711"


def kinds(loader: GiiXmlLoader) -> list[str]:
    return [p.kind for p in loader.stats.problems]


def wrap(body: str, doctype: str = "") -> bytes:
    head = f'<?xml version="1.0" encoding="UTF-8" ?>{doctype}<dokumente builddate="20260101000000">'
    return f"{head}{body}</dokumente>".encode()


NORM = (
    "<norm><metadaten><jurabk>KSchG</jurabk><enbez>§ 1</enbez><titel>T</titel></metadaten>"
    "<textdaten><text><Content><P>(1) Text.</P></Content></text></textdaten></norm>"
)


# --- XML ---------------------------------------------------------------------------------------


def test_parser_does_not_resolve_external_entities(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text(MARKER, encoding="utf-8")
    xml = (
        f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY xxe SYSTEM "file://{secret}">]><d>a&xxe;b</d>'
    ).encode()
    root = etree.fromstring(xml, hardened_parser())
    assert MARKER not in etree.tostring(root, encoding="unicode")
    assert MARKER not in "".join(root.itertext())


def test_parser_does_not_load_an_external_dtd(tmp_path: Path) -> None:
    dtd = tmp_path / "evil.dtd"
    dtd.write_text(f'<!ENTITY inj "{MARKER}">', encoding="utf-8")
    xml = f'<?xml version="1.0"?><!DOCTYPE d SYSTEM "file://{dtd}"><d>&inj;</d>'.encode()
    try:
        root = etree.fromstring(xml, hardened_parser())
    except etree.XMLSyntaxError:
        return  # an undefined entity is rejected: also fine
    assert MARKER not in "".join(root.itertext())


def test_loader_rejects_external_entity_document(make_raw: RawFactory, tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text(MARKER, encoding="utf-8")
    doctype = f'<!DOCTYPE dokumente [<!ENTITY xxe SYSTEM "file://{secret}">]>'
    xml = wrap(NORM.replace("(1) Text.", "(1) &xxe;"), doctype)
    loader = GiiXmlLoader()
    docs = list(loader.load(make_raw({"kschg": {"a.xml": xml}})))
    assert docs == []
    assert kinds(loader) == ["unsafe_xml"]
    assert MARKER not in repr(loader.stats)


def test_billion_laughs_is_rejected_fast(make_raw: RawFactory) -> None:
    decls = '<!ENTITY l0 "lol">' + "".join(
        f'<!ENTITY l{i} "' + f"&l{i - 1};" * 10 + '">' for i in range(1, 10)
    )
    xml = wrap(NORM.replace("(1) Text.", "(1) &l9;"), f"<!DOCTYPE dokumente [{decls}]>")
    loader = GiiXmlLoader()
    start = time.perf_counter()
    assert list(loader.load(make_raw({"kschg": {"a.xml": xml}}))) == []
    assert time.perf_counter() - start < 5
    assert kinds(loader) == ["unsafe_xml"]


def test_quadratic_blowup_is_rejected(make_raw: RawFactory) -> None:
    big = "x" * 50_000
    decls = f'<!ENTITY a "{big}">'
    xml = wrap(NORM.replace("(1) Text.", "(1) " + "&a;" * 5_000), f"<!DOCTYPE dokumente [{decls}]>")
    with pytest.raises(UnsafeXmlError, match="entit"):
        list(iter_norms(xml))
    loader = GiiXmlLoader()
    assert list(loader.load(make_raw({"kschg": {"a.xml": xml}}))) == []
    assert kinds(loader) in (
        ["unsafe_xml"],
        ["unsafe_archive"],
    )  # the zip ratio guard may fire first


def test_deep_nesting_is_rejected(make_raw: RawFactory) -> None:
    depth = 5_000
    opens = "".join(f"<e{i}>" for i in range(depth))
    closes = "".join(f"</e{i}>" for i in reversed(range(depth)))
    xml = wrap("<norm>" + opens + closes + "</norm>")
    loader = GiiXmlLoader()
    assert list(loader.load(make_raw({"kschg": {"a.xml": xml}}))) == []
    assert kinds(loader) == ["unsafe_xml"]


def test_nesting_limit_is_a_parameter() -> None:
    xml = wrap("<norm><a><b><c/></b></a></norm>")
    assert len(list(iter_norms(xml, XmlLimits(max_depth=10)))) == 1
    with pytest.raises(UnsafeXmlError, match="depth"):
        list(iter_norms(xml, XmlLimits(max_depth=3)))


@pytest.mark.parametrize(
    "data",
    [
        "\ufeff<dokumente/>".encode("utf-16"),
        "<dokumente/>".encode("utf-16-le"),
        b'<?xml version="1.0" encoding="ISO-8859-1"?><dokumente/>',
        b'<?xml version="1.0" encoding="UTF-7"?><dokumente/>',
    ],
    ids=["utf16-bom", "utf16-no-bom", "latin1", "utf7"],
)
def test_other_encodings_are_rejected(data: bytes) -> None:
    with pytest.raises(UnsafeXmlError, match="encoding"):
        list(iter_norms(data))


def test_malformed_xml_is_a_parse_error() -> None:
    with pytest.raises(GiiParseError, match="invalid xml"):
        list(iter_norms(b"<dokumente><norm></dokumente>"))


def test_oversized_xml_is_rejected() -> None:
    with pytest.raises(UnsafeXmlError, match="size"):
        list(iter_norms(wrap(NORM), XmlLimits(max_bytes=50)))


def test_too_many_norms_is_rejected() -> None:
    with pytest.raises(UnsafeXmlError, match="norms"):
        list(iter_norms(wrap(NORM * 3), XmlLimits(max_norms=2)))


def test_dtd_reference_never_opens_a_connection(make_raw: RawFactory, fixture_dir: Path) -> None:
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
    xml = (fixture_dir / "kschg_1.xml").read_text(encoding="utf-8")
    xml = xml.replace("http://www.gesetze-im-internet.de/dtd/1.01/gii-norm.dtd",
                      f"http://127.0.0.1:{port}/gii-norm.dtd")  # fmt: skip
    loader = GiiXmlLoader()
    docs = list(loader.load(make_raw({"kschg": {"a.xml": xml.encode()}})))
    thread.join()
    server.close()
    assert [d.doc_id for d in docs] == ["gii-kschg-1"]
    assert hits == []


def test_real_doctype_with_system_dtd_is_accepted(raw_dir: Path) -> None:
    loader = GiiXmlLoader()
    assert any(d.doc_id == "gii-kschg-1" for d in loader.load(raw_dir))
    assert loader.stats.error_count == 0


# --- ZIP ---------------------------------------------------------------------------------------


def _zip(path: Path, entries: list[tuple[zipfile.ZipInfo | str, bytes]]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in entries:
            zf.writestr(info, data)
    return path


@pytest.mark.parametrize(
    "name", ["../evil.xml", "a/../../evil.xml", "/etc/evil.xml", "C:\\evil.xml", "x\\..\\y.xml"]
)
def test_zip_slip_names_are_rejected_and_nothing_is_written(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    archive = _zip(tmp_path / "x.zip", [(name, b"<a/>")])
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(UnsafeArchiveError, match="name"):
        list(read_xml_members(archive))
    assert sorted(tmp_path.rglob("*")) == before
    assert list(work.iterdir()) == []


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    link = zipfile.ZipInfo("link.xml")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = _zip(tmp_path / "x.zip", [(link, b"/etc/passwd")])
    with pytest.raises(UnsafeArchiveError, match="symlink"):
        list(read_xml_members(archive))


def test_compression_bomb_is_rejected_before_reading(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "x.zip", [("bomb.xml", b"a" * 5_000_000)])
    with pytest.raises(UnsafeArchiveError, match="ratio"):
        list(read_xml_members(archive))


def test_member_size_total_size_and_count_limits(tmp_path: Path, fixture_dir: Path) -> None:
    data = (fixture_dir / "kschg_1.xml").read_bytes()
    archive = _zip(tmp_path / "x.zip", [("a.xml", data), ("b.xml", data), ("c.jpg", b"\xff" * 500)])
    assert [n for n, _ in read_xml_members(archive)] == ["a.xml", "b.xml"]
    with pytest.raises(UnsafeArchiveError, match="size"):
        list(read_xml_members(archive, ZipLimits(max_member_bytes=1_000)))
    with pytest.raises(UnsafeArchiveError, match="total"):
        list(read_xml_members(archive, ZipLimits(max_total_bytes=len(data) + 1_000)))
    with pytest.raises(UnsafeArchiveError, match="members"):
        list(read_xml_members(archive, ZipLimits(max_members=2)))


def test_read_is_bounded_even_when_the_header_lies(tmp_path: Path) -> None:
    archive = _zip(tmp_path / "x.zip", [("a.xml", b"<a>" + b"x" * 10_000 + b"</a>")])
    with zipfile.ZipFile(archive) as zf:
        info = zf.infolist()[0]
        with pytest.raises(UnsafeArchiveError, match="size"):
            read_bounded(zf, info, limit=1_000)
        info.file_size = 10  # the central directory now claims 10 bytes
        with pytest.raises(UnsafeArchiveError, match=r"corrupt|size"):
            read_bounded(zf, info, limit=1_000_000)


def test_encrypted_member_is_rejected() -> None:
    info = zipfile.ZipInfo("secret.xml")
    info.flag_bits |= 0x1  # ZipFile.writestr clears the bit, so the header is checked directly
    with pytest.raises(UnsafeArchiveError, match="encrypted"):
        check_member(info, ZipLimits())


def test_not_a_zip_is_an_archive_error(tmp_path: Path) -> None:
    bad = tmp_path / "x.zip"
    bad.write_bytes(b"this is not a zip")
    with pytest.raises(UnsafeArchiveError, match="zip"):
        list(read_xml_members(bad))


def test_loader_counts_archive_problems_and_keeps_going(
    make_raw: RawFactory, fixture_dir: Path
) -> None:
    good = (fixture_dir / "kschg_1.xml").read_bytes()
    raw = make_raw({"a-evil": {"../evil.xml": b"<a/>"}, "kschg": {"k.xml": good}})
    (raw / "z-bad").mkdir()
    (raw / "z-bad" / "xml.zip").write_bytes(b"junk")
    loader = GiiXmlLoader()
    docs = list(loader.load(raw))
    assert [d.doc_id for d in docs] == ["gii-kschg-1"]
    assert kinds(loader) == ["unsafe_archive", "unsafe_archive"]
    assert loader.stats.error_count == 2


def test_loader_never_writes_to_disk(raw_dir: Path, tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    before = sorted(tmp_path.rglob("*"))
    assert len(list(GiiXmlLoader().load(raw_dir))) > 5
    assert sorted(tmp_path.rglob("*")) == before


def test_error_types_share_a_base() -> None:
    assert issubclass(UnsafeArchiveError, GiiError)
    assert issubclass(UnsafeXmlError, GiiError)
