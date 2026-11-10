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
