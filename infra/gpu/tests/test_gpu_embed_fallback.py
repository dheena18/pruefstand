"""T3.1d CPU tests: the expected HTTP 400 of ``/api/generate`` for embed models is quiet (D953)."""

import shlex

from gpu_world import DAY_TAGS, GpuWorld, ps_model

CURL_400 = "curl: (22) The requested URL returned error: 400"


def _curl_400_on_generate(gpu: GpuWorld, model: str) -> None:
    """A ``curl`` whose ``/api/generate`` call for ``model`` fails with a 400; the rest works."""
    script = f"""#!/usr/bin/env bash
echo "curl $*" >> {shlex.quote(str(gpu.stubs.log))}
case "$*" in
  *api/tags*) cat {shlex.quote(str(gpu.tags_file))};;
  *api/ps*) cat {shlex.quote(str(gpu.ps_file))};;
  *{model}*api/generate*) echo "{CURL_400}" >&2; exit 22;;
  *api/generate*|*api/embed*) echo '{{"done":true}}';;
  *) echo "UNEXPECTED curl $*" >&2; exit 99;;
esac
"""
    target = gpu.stubs.bin / "curl"
    target.unlink(missing_ok=True)
    target.write_text(script, encoding="utf-8")
    target.chmod(0o755)


def test_an_embedding_model_falls_back_to_api_embed_without_the_curl_400(gpu: GpuWorld) -> None:
    gpu.set_ps([ps_model(t) for t in DAY_TAGS if t != "bge-m3"])
    _curl_400_on_generate(gpu, "bge-m3")
    res = gpu.script("switch-mode.sh", "day")
    calls = gpu.stubs.calls("curl")
    assert any("api/generate" in c and "bge-m3" in c for c in calls)
    assert any("api/embed" in c for c in calls)
    assert CURL_400 not in res.err
    assert CURL_400 not in res.out


def test_a_chat_model_failure_on_generate_stays_visible(gpu: GpuWorld) -> None:
    gpu.set_ps([ps_model(t) for t in DAY_TAGS if t != "gemma3:12b"])
    _curl_400_on_generate(gpu, "gemma3:12b")
    res = gpu.script("switch-mode.sh", "day")
    assert CURL_400 in res.err
    assert not any("api/embed" in c for c in gpu.stubs.calls("curl"))
    assert res.rc != 0
