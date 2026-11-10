"""T3.1d CPU tests: ``git_verify`` residuals (``insteadOf``, a remapped fetch refspec; D954)."""

from gpu_repo import Repo


def test_a_url_insteadof_rewrite_is_refused(repo: Repo) -> None:
    repo.git("config", "url.https://elsewhere.invalid/.insteadOf", str(repo.remote))
    res = repo.run("install-cluster-wrapper.sh", DESTDIR=str(repo.dest))
    assert res.rc == 1
    assert "insteadOf" in res.err
    assert not (repo.dest / "usr").exists()


def test_a_remapped_fetch_refspec_cannot_move_origin_main(repo: Repo) -> None:
    """A remapped ``remote.origin.fetch`` must not change what the tree is compared with."""
    repo.git("checkout", "-q", "-b", "other")
    wrapper = repo.root / "infra/gpu/pruefstand-cluster"
    wrapper.write_text(wrapper.read_text() + "\n# a different tree\n")
    repo.git("commit", "-q", "-am", "other")
    repo.git("push", "-q", "origin", "other")
    repo.git("checkout", "-q", "main")
    repo.git("config", "remote.origin.fetch", "+refs/heads/other:refs/remotes/origin/main")
    res = repo.run("install-cluster-wrapper.sh", DESTDIR=str(repo.dest))
    assert res.rc == 0, res.err
    assert repo.git("rev-parse", "origin/main") == repo.git("rev-parse", "main")
