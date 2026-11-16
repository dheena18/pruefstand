"""runner-env-names.sh and runner-env-keys.sh (D1267): names only, never a value; keys added once.

Only fake files under a temp dir: the real /home/pruefstand/runner.env is never read in tests.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

HOST = Path(__file__).resolve().parents[2] / "host"
NAMES = HOST / "runner-env-names.sh"
KEYS = HOST / "runner-env-keys.sh"
SECRETS = ("s3cr3t-alpha", "b=c d", "quoted value", "single q", "multi", "line two", "tail")
FAKE = """# runner.env (fake)

PRUEFSTAND_DATA_ROOT=s3cr3t-alpha
export GITHUB_TOKEN="b=c d"
  OLLAMA_GPU0_URL='quoted value'
EMPTY_ONE=
WEIRD=single q # not a comment inside the value
not a variable line
MULTI="multi
line=two
tail"
AFTER_MULTI=x
"""


def run(script: Path, *args: str, stdin_script: bool = False) -> subprocess.CompletedProcess[str]:
    argv = ["bash", "-s", "--", *args] if stdin_script else ["bash", str(script), *args]
    return subprocess.run(  # noqa: S603  (fixed argv, our scripts)
        argv,
        input=script.read_text(encoding="utf-8") if stdin_script else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / "runner.env"
    path.write_text(FAKE, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.parametrize("mode", ["file", "stdin"])
def test_names_prints_only_names_and_never_a_value(env_file: Path, mode: str) -> None:
    done = run(NAMES, str(env_file), stdin_script=mode == "stdin")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[:5] == [
        "PRUEFSTAND_DATA_ROOT",
        "GITHUB_TOKEN",
        "OLLAMA_GPU0_URL",
        "EMPTY_ONE (empty)",
        "WEIRD",
    ]
    assert "AFTER_MULTI" in lines
    assert "MULTI" in lines
    assert "line" not in lines  # the continuation line of a quoted value is not a variable
    assert any(re.fullmatch(r"line \d+: skipped \(not NAME=value\)", line) for line in lines)
    for secret in SECRETS:
        assert secret not in done.stdout
        assert secret not in done.stderr


def test_names_refuses_a_missing_file(tmp_path: Path) -> None:
    done = run(NAMES, str(tmp_path / "nope.env"))
    assert done.returncode == 2
    assert "no such file" in done.stderr


def test_keys_appends_both_keys_once_never_printing_them(env_file: Path) -> None:
    before = env_file.read_text(encoding="utf-8")
    done = run(KEYS, str(env_file))
    assert done.returncode == 0, done.stderr
    after = env_file.read_text(encoding="utf-8")
    assert after.startswith(before)  # nothing above changed
    added = dict(line.split("=", 1) for line in after[len(before) :].splitlines())
    assert set(added) == {"PRUEFSTAND_NONCE_KEY", "PRUEFSTAND_CANDIDATE_API_KEY"}
    for value in added.values():
        assert re.fullmatch(r"[0-9a-f]{64}", value)
        assert value not in done.stdout
        assert value not in done.stderr
    assert added["PRUEFSTAND_NONCE_KEY"] != added["PRUEFSTAND_CANDIDATE_API_KEY"]
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    again = run(KEYS, str(env_file))
    assert again.returncode == 0
    assert env_file.read_text(encoding="utf-8") == after  # idempotent
    assert "kept" in again.stdout


def test_keys_refuses_to_fill_an_empty_existing_line(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text("PRUEFSTAND_NONCE_KEY=\n", encoding="utf-8")
    path.chmod(0o600)
    done = run(KEYS, str(path))
    assert done.returncode == 2
    assert "empty" in done.stderr
    assert path.read_text(encoding="utf-8") == "PRUEFSTAND_NONCE_KEY=\n"


def test_keys_creates_a_missing_file_with_mode_600(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    done = run(KEYS, str(path), stdin_script=True)
    assert done.returncode == 0, done.stderr
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_keys_refuses_a_symlink_and_a_group_readable_file(tmp_path: Path) -> None:
    real = tmp_path / "real.env"
    real.write_text("", encoding="utf-8")
    real.chmod(0o600)
    link = tmp_path / "runner.env"
    link.symlink_to(real)
    assert run(KEYS, str(link)).returncode == 2
    loose = tmp_path / "loose.env"
    loose.write_text("", encoding="utf-8")
    loose.chmod(0o644)
    done = run(KEYS, str(loose))
    assert done.returncode == 2
    assert "mode" in done.stderr
    assert loose.read_text(encoding="utf-8") == ""


def test_no_value_reaches_a_trace(env_file: Path) -> None:
    done = subprocess.run(  # noqa: S603
        ["bash", "-x", str(KEYS), str(env_file)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={**os.environ},
    )
    assert done.returncode == 0, done.stderr
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(("PRUEFSTAND_NONCE_KEY=", "PRUEFSTAND_CANDIDATE_API_KEY=")):
            assert line.split("=", 1)[1] not in done.stderr


TRICKY = """A="x\\"
U0VDUkVUPQ==
tail"
M="first
LEAKY_NAME=value
end"
S='a
INNER="x
b'
C=abc\\
HIDDEN=1
D='it''s' # it's a comment
E="q" # comment with ' quote
B=1
"""


def test_names_never_print_a_continuation_line(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text(TRICKY, encoding="utf-8")
    done = run(NAMES, str(path))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["A", "M", "S", "C", "D", "E", "B"]
    for leak in ("U0VDUkVUPQ", "LEAKY_NAME", "INNER", "HIDDEN", "tail", "end", "first"):
        assert leak not in done.stdout


@pytest.mark.parametrize(
    "line",
    [
        'PRUEFSTAND_NONCE_KEY=""',
        "PRUEFSTAND_NONCE_KEY=   ",
        "PRUEFSTAND_NONCE_KEY=''",
        "export PRUEFSTAND_NONCE_KEY= ",
    ],
)
def test_keys_refuses_an_empty_or_blank_quoted_value(tmp_path: Path, line: str) -> None:
    path = tmp_path / "runner.env"
    path.write_text(line + "\n", encoding="utf-8")
    path.chmod(0o600)
    done = run(KEYS, str(path))
    assert done.returncode == 2
    assert "empty" in done.stderr
    assert path.read_text(encoding="utf-8") == line + "\n"


def test_keys_ignore_a_key_like_line_inside_a_quoted_value(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    text = 'NOTE="see\nPRUEFSTAND_NONCE_KEY=not-a-key\nend"\n'
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    done = run(KEYS, str(path))
    assert done.returncode == 0, done.stderr
    added = path.read_text(encoding="utf-8")[len(text) :].splitlines()
    assert [line.split("=", 1)[0] for line in added] == [
        "PRUEFSTAND_NONCE_KEY",
        "PRUEFSTAND_CANDIDATE_API_KEY",
    ]


def test_keys_refuses_a_read_only_file_with_a_clear_message(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text("", encoding="utf-8")
    path.chmod(0o400)
    done = run(KEYS, str(path))
    assert done.returncode == 2
    assert "not writable" in done.stderr
    assert path.read_text(encoding="utf-8") == ""


def _scanner(script: Path) -> str:
    text = script.read_text(encoding="utf-8")
    start = text.index("# --- quote scanner")
    return text[start : text.index("# --- end of quote scanner", start)]


def test_both_scripts_carry_the_same_quote_scanner() -> None:
    assert _scanner(NAMES) == _scanner(KEYS)


@pytest.mark.parametrize(
    "line",
    [
        'PRUEFSTAND_NONCE_KEY="" # note',
        "PRUEFSTAND_NONCE_KEY= # note",
        "PRUEFSTAND_NONCE_KEY=''  #x",
    ],
)
def test_keys_refuses_an_empty_value_before_a_comment(tmp_path: Path, line: str) -> None:
    path = tmp_path / "runner.env"
    path.write_text(line + "\n", encoding="utf-8")
    path.chmod(0o600)
    done = run(KEYS, str(path))
    assert done.returncode == 2
    assert "empty" in done.stderr
    assert path.read_text(encoding="utf-8") == line + "\n"


def test_keys_keep_a_value_with_a_comment_and_an_apostrophe(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    text = "PRUEFSTAND_NONCE_KEY=x # note\nPRUEFSTAND_CANDIDATE_API_KEY=it's\nOTHER=1\n"
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    done = run(KEYS, str(path))
    assert done.returncode == 0, done.stderr
    assert path.read_text(encoding="utf-8") == text  # no duplicate key appended
    assert done.stdout.count("present, kept") == 2


def test_names_unquoted_quotes_are_literal_and_ansi_c_values_are_quoted(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text(
        "A=it's\nB=1\nC=$'line\\'\nSECRET_LINE=x\nend'\nD=2\nE=a\"b\nF=3\n", encoding="utf-8"
    )
    done = run(NAMES, str(path))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["A", "B", "C", "D", "E", "F"]


@pytest.mark.parametrize("script", [NAMES, KEYS])
def test_a_very_long_line_is_refused_fast(tmp_path: Path, script: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text("A=" + "x" * 40_000 + "\n", encoding="utf-8")
    path.chmod(0o600)
    done = run(script, str(path))
    assert done.returncode == 2
    assert "longer than" in done.stderr
    assert path.read_text(encoding="utf-8").count("\n") == 1


def test_a_long_quoted_line_within_the_limit_is_read(tmp_path: Path) -> None:
    path = tmp_path / "runner.env"
    path.write_text('A="' + "y" * 8000 + '"\nB=1\n', encoding="utf-8")
    done = run(NAMES, str(path))
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == ["A", "B"]
