"""Memory and size limits of the GII loader (T2.2): element bombs, defaults, one parser config."""

import subprocess
import sys
from typing import Any

import pytest
from lxml import etree

from pruefstand.ingest.gii import xmlparse
from pruefstand.ingest.gii.errors import UnsafeXmlError
from pruefstand.ingest.gii.safezip import ZipLimits
from pruefstand.ingest.gii.xmlparse import XmlLimits, iter_norms

NORM = (
    "<norm><metadaten><jurabk>KSchG</jurabk><enbez>§ 1</enbez><titel>T</titel></metadaten>"
    "<textdaten><text><Content><P>(1) Text.</P></Content></text></textdaten></norm>"
)


def wrap(body: str) -> bytes:
    return f'<?xml version="1.0" encoding="UTF-8" ?><dokumente>{body}</dokumente>'.encode()


_BOMB = """
import resource, sys, time
from pruefstand.ingest.gii.errors import UnsafeXmlError
from pruefstand.ingest.gii.xmlparse import iter_norms

n = int(sys.argv[1])
data = b'<?xml version="1.0"?><dokumente>' + b"<a/>" * n + b"</dokumente>"
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
start = time.perf_counter()
try:
    list(iter_norms(data))
    print("accepted")
except UnsafeXmlError as err:
    print("refused", err)
after = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
print((after - before) // 1024, round(time.perf_counter() - start, 1))
"""


def test_flat_element_bomb_is_refused_fast_and_small() -> None:
    result = subprocess.run(  # noqa: S603  (fixed argv, no shell)
        [sys.executable, "-I", "-c", _BOMB, "3500000"],
        capture_output=True, text=True, check=True, timeout=120,
    )  # fmt: skip
    verdict, numbers = result.stdout.strip().splitlines()
    delta_mib, seconds = (float(x) for x in numbers.split())
    assert verdict.startswith("refused"), verdict
    assert "elements" in verdict
    assert delta_mib < 500
    assert seconds < 20


def test_element_limit_is_a_parameter() -> None:
    xml = wrap(NORM)
    assert len(list(iter_norms(xml, XmlLimits(max_elements=100)))) == 1
    with pytest.raises(UnsafeXmlError, match="elements"):
        list(iter_norms(xml, XmlLimits(max_elements=5)))


def test_default_limits_follow_the_real_files() -> None:
    mib = 1024 * 1024
    assert XmlLimits().max_bytes == 16 * mib
    assert XmlLimits().max_elements == 1_000_000
    assert ZipLimits().max_member_bytes == 16 * mib


def test_production_and_hardened_parser_share_one_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    real = etree.iterparse

    def spy(source: Any, *args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return real(source, *args, **kwargs)

    monkeypatch.setattr(etree, "iterparse", spy)
    list(iter_norms(wrap(NORM)))
    for name in ("events",):
        captured.pop(name)
    assert captured == xmlparse.PARSER_OPTIONS
    assert xmlparse.PARSER_OPTIONS["resolve_entities"] is False
    assert xmlparse.PARSER_OPTIONS["no_network"] is True
    assert xmlparse.PARSER_OPTIONS["load_dtd"] is False
    assert xmlparse.PARSER_OPTIONS["huge_tree"] is False
