"""Malformed ``sources.yaml`` shapes end in ``SourcesError`` and exit code 1 (T2.1 follow-up)."""

from pathlib import Path

import pytest
from data_sources import SourcesError, load_sources
from download import main

GOOD_ENTRY = """\
- id: gii:kschg
  kind: gii
  abbrev: KSchG
  slug: kschg
  pinned: '2026-10-31'
  files:
    xml.zip: bfeebd2320aa0ddec074570f2705441e1b26639fb86839f80b1210d8bf2ed8a2
"""
DEFAULTS = """\
defaults:
  gii:
    license: official-work-5-urhg
    license_config: laws_eurlex
    redistribute: true
    attribution: x
"""

CASES = {
    "yaml_syntax_error": "version: 1\nsources: [\n",
    "yaml_tab_error": "version: 1\nsources:\n\t- a\n",
    "kind_is_list": "version: 1\n" + DEFAULTS + "sources:\n- id: gii:kschg\n  kind: [gii]\n",
    "kind_is_mapping": "version: 1\n" + DEFAULTS + "sources:\n- id: gii:kschg\n  kind: {a: b}\n",
    "entry_is_string": "version: 1\n" + DEFAULTS + "sources:\n- just-a-string\n",
    "entry_is_list": "version: 1\n" + DEFAULTS + "sources:\n- [a, b]\n",
    "entry_is_number": "version: 1\n" + DEFAULTS + "sources:\n- 42\n",
    "defaults_is_list": "version: 1\ndefaults: [a, b]\nsources:\n" + GOOD_ENTRY,
    "defaults_is_string": "version: 1\ndefaults: nonsense\nsources:\n" + GOOD_ENTRY,
    "kind_defaults_is_list": "version: 1\ndefaults:\n  gii: [a, b]\nsources:\n" + GOOD_ENTRY,
    "kind_defaults_is_string": "version: 1\ndefaults:\n  gii: nonsense\nsources:\n" + GOOD_ENTRY,
}


@pytest.mark.parametrize("text", CASES.values(), ids=CASES.keys())
def test_malformed_shapes_raise_sources_error_and_exit_1(
    text: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SourcesError):
        load_sources(path)
    assert main(["--sources", str(path), "--raw", str(tmp_path / "raw"), "--verify-only"]) == 1
    assert "error:" in capsys.readouterr().err
