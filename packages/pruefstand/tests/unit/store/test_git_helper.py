"""The ``git`` wrapper: list arguments, no shell, the token only through ``GIT_ASKPASS`` (T6.1)."""

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from pruefstand.core.errors import StoreError
from pruefstand.store._git import Git, remote_url

SECRET = "ghp_" + "".join(chr(97 + (i * 11) % 26) for i in range(36))


def test_git_runs_and_returns_stdout() -> None:
    with Git() as git:
        assert git.run("--version").startswith("git version")


def test_a_failing_command_is_a_store_error_without_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOME_PAT", SECRET)
    with Git("SOME_PAT") as git, pytest.raises(StoreError) as excinfo:
        git.run("clone", f"file:///does/not/exist/{SECRET}", str(tmp_path / "x"))
    assert SECRET not in str(excinfo.value)
    assert "git clone" in str(excinfo.value)


def test_the_token_reaches_git_only_through_the_askpass_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOME_PAT", SECRET)
    calls: list[tuple[list[str], dict[str, Any]]] = []
    real = subprocess.run

    def spy(args: list[str], *a: Any, **kw: Any) -> Any:
        calls.append(([str(x) for x in args], kw))
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    with Git("SOME_PAT") as git:
        git.run("--version")
        argv, kw = calls[0]
        assert SECRET not in " ".join(argv)
        assert not kw.get("shell")
        env = kw["env"]
        script = Path(env["GIT_ASKPASS"])
        assert script.is_file()
        assert SECRET not in script.read_text(encoding="utf-8")
        assert env["GIT_TERMINAL_PROMPT"] == "0"
        user = subprocess.run(  # noqa: S603
            [str(script), "Username for 'https://github.com': "],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        pw = subprocess.run(  # noqa: S603
            [str(script), "Password for 'https://x-access-token@github.com': "],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        assert user.stdout.strip() == "x-access-token"
        assert pw.stdout.strip() == SECRET
    assert not script.exists()  # the helper directory is gone after the session


def test_without_a_token_there_is_no_askpass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_PAT", raising=False)
    seen: list[dict[str, Any]] = []
    real = subprocess.run

    def spy(args: list[str], *a: Any, **kw: Any) -> Any:
        seen.append(kw["env"])
        return real(args, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    with Git("SOME_PAT") as git:
        git.run("--version")
    assert "GIT_ASKPASS" not in seen[0]
    assert seen[0]["GIT_TERMINAL_PROMPT"] == "0"


def test_user_and_system_git_config_are_not_read() -> None:
    with Git() as git:
        env = git.environment()
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull


def test_a_timeout_is_a_store_error(tmp_path: Path) -> None:
    with Git(timeout_s=0.05) as git, pytest.raises(StoreError, match="timed out"):
        git.run("-c", "alias.slow=!sleep 5", "slow", cwd=tmp_path)


def test_run_outside_a_session_is_refused() -> None:
    git = Git()
    with pytest.raises(StoreError, match="session"):
        git.run("--version")


def test_the_github_url_is_built_from_owner_and_name() -> None:
    assert (
        remote_url("dheena18/pruefstand-gate") == "https://github.com/dheena18/pruefstand-gate.git"
    )


@pytest.mark.parametrize(
    "repo", ["", "owner", "a/b/c", "../x", "o/r;rm", "o /r", "-o/r", "o/-r", "o/r\n"]
)
def test_a_bad_repo_name_is_refused(repo: str) -> None:
    with pytest.raises(StoreError, match="repo"):
        remote_url(repo)


def test_a_local_remote_is_turned_into_a_file_url(tmp_path: Path) -> None:
    assert remote_url("o/r", str(tmp_path)) == tmp_path.resolve().as_uri()


def test_a_non_local_remote_override_is_passed_through() -> None:
    assert remote_url("o/r", "file:///x/y.git") == "file:///x/y.git"
