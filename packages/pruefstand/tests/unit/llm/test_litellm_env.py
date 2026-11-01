"""``import litellm`` must not pull a repository ``.env`` into the process (CLAUDE.md §5)."""

import os
import subprocess
import sys
from pathlib import Path

CANARY = "PRUEFSTAND_ENV_CANARY"

SNIPPET = """
import os, dotenv.main
dotenv.main.find_dotenv = lambda *a, **k: {path!r}
{imp}
print({name!r} in os.environ)
"""


def _run(tmp_path: Path, imp: str, mode: str | None) -> str:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{CANARY}=leaked\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "LITELLM_MODE" and k != CANARY}
    if mode is not None:
        env["LITELLM_MODE"] = mode
    code = SNIPPET.format(path=str(env_file), imp=imp, name=CANARY)
    out = subprocess.run(  # noqa: S603
        [sys.executable, "-I", "-c", code],
        env=env, cwd=tmp_path, capture_output=True, text=True, check=True, timeout=120,
    )  # fmt: skip
    return out.stdout.strip().splitlines()[-1]


def test_control_litellm_in_dev_mode_does_load_dotenv(tmp_path: Path) -> None:
    assert _run(tmp_path, "import litellm", "DEV") == "True"


def test_our_backend_import_does_not_load_dotenv(tmp_path: Path) -> None:
    assert _run(tmp_path, "import pruefstand.llm.backends.litellm", None) == "False"


def test_telemetry_is_off() -> None:
    import litellm

    assert litellm.telemetry is False
