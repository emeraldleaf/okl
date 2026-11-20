"""The storage target is resolved in one place (lesson n_02cc84da158d).

`client.store_url()` reads OKL_DATABASE_URL; `Store` keeps its own default for a caller that names
no URL. A second reader diverged three times: the drift step's info line (#37), an eval script
that fell back to a file for a non-SQLite URL (#309), and `okl doctor`, which counted an empty
value as set while the client counted it unset (#380). Writing the variable, or removing it from
an environment handed to a child, is not reading it.
"""
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
READS = re.compile(r"""environ\.get\(\s*["']OKL_DATABASE_URL["']"""
                   r"""|getenv\(\s*["']OKL_DATABASE_URL["']"""
                   r"""|environ\[\s*["']OKL_DATABASE_URL["']\s*\](?!\s*=[^=])"""
                   r"""|["']OKL_DATABASE_URL["']\s+in\s+(?:os\.)?environ""")
ALLOWED = {"src/okl/client.py": 1, "src/okl/store.py": 1}   # the resolver, and Store's own default


def readers(files: list[str]) -> dict[str, int]:
    """How many times each file reads the variable."""
    out = {}
    for f in files:
        n = len(READS.findall((REPO / f).read_text(errors="replace")))
        if n:
            out[f] = n
    return out


def test_only_the_resolver_and_the_store_read_the_storage_variable():
    """Every committed Python file outside tests, the evals and CI scripts included."""
    files = [f for f in subprocess.run(["git", "-C", str(REPO), "ls-files", "*.py"], capture_output=True,
                                       text=True, check=True).stdout.split() if not f.startswith("tests/")]
    assert len(files) > 100, "the scan found too few files to mean anything"
    assert readers(files) == ALLOWED, ("read OKL_DATABASE_URL through okl.client.store_url(), "
                                       "never directly (lesson n_02cc84da158d)")


def test_the_pattern_tells_a_read_from_a_write():
    """Each form of read is caught; a write or a key filter is not."""
    cases = {'url = os.environ.get("OKL_DATABASE_URL")': 1, "os.getenv('OKL_DATABASE_URL', '')": 1,
             'url = os.environ["OKL_DATABASE_URL"]': 1, 'if "OKL_DATABASE_URL" in os.environ: pass': 1,
             'os.environ["OKL_DATABASE_URL"] = url': 0, '{k: v for k, v in env.items() if k != "OKL_DATABASE_URL"}': 0}
    for text, n in cases.items():
        assert len(READS.findall(text)) == n, text


def test_the_resolver_reads_an_empty_value_as_unset(tmp_path, monkeypatch):
    """#380's divergence: an empty variable is unset, here and in every caller."""
    from okl.client import store_url
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKL_DATABASE_URL", "")
    assert store_url() is None
    (tmp_path / ".okl").mkdir(); (tmp_path / ".okl" / "config.json").write_text("{}")
    assert store_url() == f"sqlite:///{(tmp_path / '.okl' / 'okl.db').resolve()}"
    monkeypatch.setenv("OKL_DATABASE_URL", "sqlite:///elsewhere.db")
    assert store_url() == "sqlite:///elsewhere.db"


def test_a_linked_worktree_uses_its_main_checkouts_store(tmp_path, monkeypatch):
    """git ignores .okl/, so a worktree added beside the checkout has none, and okl refused there: the
    `cd <worktree> && okl check --change` the Stop hook names for work done in one could never run. It
    now finds the main checkout's config, and so its store. A worktree with its own config keeps it, and
    a submodule, whose `.git` file names a git directory with no `commondir`, is not taken for one."""
    import shutil

    import pytest

    from okl.client import _find_config, store_url
    if shutil.which("git") is None:
        pytest.skip("git not available")
    monkeypatch.delenv("OKL_DATABASE_URL", raising=False)
    main = tmp_path / "main"; main.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    (main / "a.py").write_text("a\n"); (main / ".gitignore").write_text(".okl/\n")
    subprocess.run([*git, "-C", str(main), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-qm", "a"], check=True)
    (main / ".okl").mkdir(); (main / ".okl" / "config.json").write_text('{"repo": "r"}')
    beside = tmp_path / "beside"
    subprocess.run([*git, "-C", str(main), "worktree", "add", "-q", "-b", "w", str(beside)], check=True)
    (beside / "sub").mkdir()
    monkeypatch.chdir(beside / "sub")
    assert store_url() == f"sqlite:///{(main / '.okl' / 'okl.db').resolve()}"
    # Its own config, when it has one, wins.
    (beside / ".okl").mkdir(); (beside / ".okl" / "config.json").write_text('{"repo": "r"}')
    assert _find_config() == (beside / ".okl" / "config.json").resolve()
    # A submodule's .git file names a git directory with no commondir: no main checkout is guessed.
    sub = tmp_path / "submodule"; sub.mkdir(); (tmp_path / "modules" / "s").mkdir(parents=True)
    (sub / ".git").write_text("gitdir: ../modules/s\n")
    assert _find_config(sub) is None
    # A .git file okl cannot decode is not a worktree either: okl resolves as it did before, not crash.
    (sub / ".git").write_bytes(b"gitdir: \xff\xfe\n")
    assert _find_config(sub) is None
    # The main checkout itself, and a directory outside any repository, resolve as before.
    assert _find_config(main) == (main / ".okl" / "config.json").resolve()
    assert _find_config(tmp_path) is None


def test_okl_works_on_the_worktree_it_runs_in_with_the_main_checkouts_store(tmp_path, monkeypatch):
    """The store is the main checkout's, the repository is the worktree's. Taking the config's folder as
    the repository ran `okl reverify` in the main checkout from a worktree beside it: it stamped the main
    checkout's commit and rewrote its okl-drift.json. A worktree nested inside the checkout, where
    Claude Code puts its own, finds the config by walking up, and had the same fault."""
    import shutil

    import pytest

    from okl.cli.verification import _snapshot_path
    from okl.client import project_root
    if shutil.which("git") is None:
        pytest.skip("git not available")
    monkeypatch.delenv("OKL_DATABASE_URL", raising=False)
    main = tmp_path / "main"; main.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    (main / "a.py").write_text("a\n"); (main / ".gitignore").write_text(".okl/\n.claude/worktrees/\n")
    subprocess.run([*git, "-C", str(main), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-qm", "a"], check=True)
    (main / ".okl").mkdir(); (main / ".okl" / "config.json").write_text('{"repo": "r"}')
    beside, nested = tmp_path / "beside", main / ".claude" / "worktrees" / "agent-1"
    for i, wt in enumerate((beside, nested)):
        subprocess.run([*git, "-C", str(main), "worktree", "add", "-q", "-b", f"w{i}", str(wt)], check=True)
        (wt / "pkg").mkdir()
        monkeypatch.chdir(wt / "pkg")
        assert project_root() == wt.resolve(), wt
        assert _snapshot_path() == wt.resolve() / "okl-drift.json"
    # The main checkout, and a subdirectory of it, are the repository as before.
    (main / "pkg").mkdir(); monkeypatch.chdir(main / "pkg")
    assert project_root() == main.resolve()
    # A worktree with a config of its own is its own repository either way.
    (beside / ".okl").mkdir(); (beside / ".okl" / "config.json").write_text('{"repo": "r"}')
    monkeypatch.chdir(beside / "pkg")
    assert project_root() == beside.resolve()


def test_init_in_a_worktree_of_a_set_up_checkout_refuses_rather_than_start_an_empty_store(
        tmp_path, monkeypatch, capsys):
    """Since #492 okl in a git worktree reads its main checkout's store. `okl init` there wrote a config
    of the worktree's own beside a new, empty store, which every later command read instead, and said
    nothing. It now refuses (exit 2) and names the checkout to run it in, for a worktree beside the
    checkout and one nested in it; a worktree of a checkout never set up is set up as before."""
    import shutil

    import pytest

    from okl.cli import main
    if shutil.which("git") is None:
        pytest.skip("git not available")
    monkeypatch.delenv("OKL_DATABASE_URL", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    checkout = tmp_path / "main"; checkout.mkdir()
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
    (checkout / "a.py").write_text("a\n"); (checkout / ".gitignore").write_text(".okl/\n.claude/worktrees/\n")
    subprocess.run([*git, "-C", str(checkout), "add", "-A"], check=True)
    subprocess.run([*git, "-C", str(checkout), "commit", "-qm", "a"], check=True)
    (checkout / ".okl").mkdir(); (checkout / ".okl" / "config.json").write_text('{"repo": "r"}')
    beside, nested = tmp_path / "beside", checkout / ".claude" / "worktrees" / "agent-1"

    def init(*args: str) -> int:
        try:
            return main(["init", *args])
        except SystemExit as e:
            return e.code if isinstance(e.code, int) else 1

    for i, wt in enumerate((beside, nested)):
        subprocess.run([*git, "-C", str(checkout), "worktree", "add", "-q", "-b", f"w{i}", str(wt)], check=True)
        monkeypatch.chdir(wt)
        for args in (["--repo", "r", "--no-seed"], ["--dry-run"]):
            capsys.readouterr()
            assert init(*args) == 2, (wt, args)
            err = capsys.readouterr().err
            assert f"okl init: this is a git worktree of {checkout.resolve()}" in err, err
            assert not (wt / ".okl").exists(), "a refused init must not start a store"
    # The guide's troubleshooting row quotes this refusal (lesson doc-claim-governs-doc-and-code).
    guide = (Path(__file__).resolve().parents[1] / "docs" / "GETTING-STARTED.md").read_text()
    assert "| `okl init: this is a git worktree of <checkout>…` (exit 2) |" in guide
    # A main checkout okl cannot read is not one it uses: no traceback (is-file-raises-in-unreadable-dir).
    from okl.cli import install

    real_is_file = Path.is_file

    def unreadable(self):
        if self == checkout.resolve() / ".okl" / "config.json":
            raise PermissionError(13, "Permission denied")
        return real_is_file(self)
    with monkeypatch.context() as m:
        m.setattr(install, "_find_config", lambda start=None: None)    # walking up found none
        m.setattr(Path, "is_file", unreadable)
        assert install._worktree_of_a_set_up_checkout() is None
    # A worktree of a checkout never set up is set up as before.
    shutil.rmtree(checkout / ".okl")
    monkeypatch.chdir(beside)
    assert init("--dry-run", "--repo", "r") == 0
