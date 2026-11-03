"""Number and string formats of the PR comment (ui-spec §10.2) and the Markdown escaping."""

import re
from collections.abc import Callable

import pytest
from testsupport.report_builders import manifest
from testsupport.timing import assert_scales_linearly

from pruefstand.core.models.run import CostSummary
from pruefstand.report.format import (
    fmt_delta,
    fmt_duration,
    fmt_gpu,
    fmt_mde,
    fmt_num,
    fmt_signed,
    fmt_tokens,
    fmt_usd,
    md_code,
    md_escape,
    ref_label,
    safe_url,
)

ZWSP = "\u200b"


def test_ref_label_variants() -> None:
    assert ref_label(manifest(pr_number=42, git_sha="d4e5f6a7b8c9")) == "pr-42@d4e5f6a"
    assert (
        ref_label(manifest(pr_number=None, git_ref="main", git_sha="a1b2c3d4e5")) == "main@a1b2c3d"
    )
    assert ref_label(manifest(pr_number=None, git_ref=None, git_sha=None)) == "–"
    assert ref_label(manifest(pr_number=None, git_ref="main", git_sha=None)) == "main"


def test_ref_label_neutralises_hostile_branch_names_and_shas() -> None:
    label = ref_label(
        manifest(pr_number=None, git_ref="x@octocat|<b>[a](http://e.vx)", git_sha="zz")
    )
    assert "@octocat" not in label
    assert "<b>" not in label
    assert "](" not in label
    assert "|" not in label.replace("\\|", "")
    assert "@zz" not in label


def test_tokens_sum_and_units() -> None:
    cost = CostSummary(
        usd=0, prompt_tokens=4_000_000, completion_tokens=100_000, gpu_seconds=0, llm_calls=1
    )
    assert fmt_tokens(cost) == "4.1 M"
    assert (
        fmt_tokens(cost.model_copy(update={"prompt_tokens": 800_000, "completion_tokens": 12_300}))
        == "812 k"
    )
    assert (
        fmt_tokens(cost.model_copy(update={"prompt_tokens": 100, "completion_tokens": 20}))
        == "< 1 k"
    )
    assert (
        fmt_tokens(cost.model_copy(update={"prompt_tokens": 999_900, "completion_tokens": 0}))
        == "1.0 M"
    )


def test_delta_and_signed() -> None:
    assert fmt_delta(-0.07, -0.10, -0.04) == "−0.07 (−0.10, −0.04)"
    assert fmt_delta(0.01, -0.03, 0.01) == "+0.01 (−0.03, +0.01)"
    assert fmt_signed(-0.0004) == "+0.00"
    assert fmt_signed(None) == "–"
    assert fmt_delta(None, None, None) == "–"


def test_scalar_formats() -> None:
    assert fmt_duration(1092) == "18m 12s"
    assert fmt_duration(41) == "0m 41s"
    assert fmt_usd(0.18) == "0.18 USD"
    assert fmt_usd(0.0) == "0 USD"
    assert fmt_mde(0.0403) == "0.04"
    assert fmt_mde(None) == "–"
    assert fmt_num(0.855) in {"0.85", "0.86"}
    assert fmt_num(None) == "–"
    assert fmt_gpu(2100.4) == "~2,100 GPU-s"


def test_md_escape_neutralises_markdown_html_mentions_links() -> None:
    hostile = (
        "| @octocat <script>alert(1)</script> `x` ![i](http://e.vx/a.png) "
        "[l](https://e.vx) #12 www.e.vx\nnew"
    )
    out = md_escape(hostile)
    assert "@octocat" not in out
    assert "<script>" not in out
    assert "\n" not in out
    assert "](" not in out
    assert "http://" not in out
    assert "https://" not in out
    assert "www." not in out
    assert "#12" not in out
    assert "`" not in out.replace("\\`", "")
    assert "|" not in out.replace("\\|", "")
    assert f"@{ZWSP}octocat" in out


def test_md_escape_caps_length_and_strips_control_characters() -> None:
    assert len(md_escape("a" * 10_000)) <= 201
    assert md_escape("a\x00b\x1b[31m\u202eevil").count("\u202e") == 0
    assert "\x00" not in md_escape("a\x00b")


def test_md_code_cannot_break_out() -> None:
    out = md_code("a`b|c\nd")
    assert out.startswith("`")
    assert out.endswith("`")
    assert "\n" not in out
    assert "`" not in out[1:-1]
    assert "|" not in out.replace("\\|", "")
    assert md_code("") == "–"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://e.vx/a b",
        "https://e.vx/<x>",
        "ftp://e.vx",
        "",
        "https://e.vx/\n",
    ],
)
def test_safe_url_rejects(url: str) -> None:
    assert safe_url(url) is None


def test_safe_url_accepts_https_and_http() -> None:
    assert safe_url("https://example.org/run/1?a=b") == "https://example.org/run/1?a=b"
    assert safe_url(None) is None
    assert safe_url("https://e.vx/" + "a" * 3000) is None


def test_md_escape_is_linear() -> None:
    def escaper(n: int) -> Callable[[], object]:
        text = ("@a|<b>[c](http://d) `e` #1 " * n)[:200_000]
        return lambda: md_escape(text, limit=len(text))

    assert_scales_linearly(escaper(2_000), escaper(8_000), scale=4, floor_s=1e-4)


@pytest.mark.parametrize("text", ["GH-123", "gh-9 x", "see Gh-42"])
def test_gh_autolinks_are_broken(text: str) -> None:
    for out in (md_escape(text), md_code(text)):
        assert not re.search(r"(?i)gh-\d", out)


@pytest.mark.parametrize(
    "url", ["https://e.vx/a\u200bb", "https://e.vx/\u202eevil", "https://e.vx/\x85"]
)
def test_safe_url_rejects_invisible_characters(url: str) -> None:
    assert safe_url(url) is None
