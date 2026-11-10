"""`okl changes` (#398): what a change did to the files lessons name, read from git alone."""
import json
import subprocess

import pytest

from okl import changes
from okl.cli import main
from okl.client import Client
from okl.store import Node

# A block worth tracking when it moves. The comment line reads as a diff header ("--- ...") once
# git marks it removed, and must not be taken for one.
BLOCK = """def total_of(rows):
-- select the rows that changed since the last run
    kept = [row for row in rows if row.changed]
    weights = {row.key: row.weight for row in kept}
    scaled = sum(weights[key] * factor_for(key) for key in weights)
    return round(scaled, places_for(kept))
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """main, and a branch `work` that renames, deletes, moves a block into a new file and adds one."""
    r = tmp_path / "r"; r.mkdir()
    git = ["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]

    def run(*a):
        return subprocess.run([*git, *a], capture_output=True, text=True, check=True).stdout.strip()

    def write(path, text):
        (r / path).parent.mkdir(parents=True, exist_ok=True)
        (r / path).write_text(text)

    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    write("src/engine.py", "import os\n\n" + BLOCK + "\ndef run():\n    return total_of(load())\n")
    write("src/legacy.py", "def old_path():\n    return 'kept as it was, only renamed'\n")
    write("docs/old.md", "# Old notes\nThese go away.\n")
    write("README.md", "See docs/old.md and src/legacy.py.\n")
    run("add", "-A"); run("commit", "-qm", "base")
    run("switch", "-qc", "work")
    run("mv", "src/legacy.py", "src/kept.py")
    run("rm", "-q", "docs/old.md")
    write("src/engine.py", "import os\nfrom .helpers import total_of\n\ndef run():\n    return total_of(load())\n")
    write("src/helpers.py", BLOCK)
    write("tests/test_new.py", "def test_it():\n    assert True\n")
    run("add", "-A"); run("commit", "-qm", "work")
    monkeypatch.chdir(r)
    (r / ".okl").mkdir()
    (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    return r


def _lesson(id, files, **kw):
    return Node(id=id, type="Rule", title=f"lesson {id}", scope=kw.pop("scope", "repo:r"), files=files, **kw)


LESSONS = [
    _lesson("renamed", "src/legacy.py"),
    _lesson("deleted", "docs/old.md"),
    _lesson("moved", "src/engine.py"),
    _lesson("folder", "src/"),
    _lesson("tests", "tests/"),
    _lesson("elsewhere", "src/legacy.py", scope="org", repo="other"),
    _lesson("retired", "src/legacy.py", status="obsolete"),
]


def test_it_reads_each_kind_of_change(repo):
    """New, deleted and renamed files, the moved block, and where a removed path is still named."""
    found = changes.read("main", "work", str(repo))
    assert sorted(found.new) == ["src/helpers.py", "tests/test_new.py"]
    assert found.deleted == ["docs/old.md"]
    assert [(x.old, x.new, x.similarity) for x in found.renamed] == [("src/legacy.py", "src/kept.py", 100)]
    assert [(m.source, m.dest) for m in found.moved] == [("src/engine.py", "src/helpers.py")]
    assert found.moved[0].lines == 6
    assert found.named_in == {"docs/old.md": ["README.md:1"], "src/legacy.py": ["README.md:1"]}


def test_each_owned_lesson_the_change_leaves_behind_gets_a_proposal(repo):
    """A rename re-points, a move adds the destination, a deletion is left to the person; a
    folder that still covers everything, another repo's lesson and a retired one get none."""
    rep = changes.report(changes.read("main", "work", str(repo)), LESSONS, "r")
    by_id = {p["id"]: p for p in rep["proposals"]}
    assert set(by_id) == {"renamed", "deleted", "moved"}       # a folder still covers all; others are not this repo's
    assert by_id["renamed"]["files"] == "src/kept.py"
    assert "now matches nothing" in by_id["renamed"]["reasons"][0]
    assert by_id["moved"]["files"] == "src/engine.py,src/helpers.py"
    assert by_id["deleted"]["files"] is None                     # only the person can re-point it
    assert "re-point it, drop it, or retire" in by_id["deleted"]["reasons"][0]
    governed = {f["path"]: f["governed_by"] for f in rep["new"]}
    assert governed["tests/test_new.py"] == ["[tests] lesson tests"]
    assert governed["src/helpers.py"] == ["[folder] lesson folder"]


def test_slight_lines_are_never_a_move(repo):
    """Braces, `pass` and blank lines repeat everywhere, so they never make a block."""
    trivial = [["}", "end", "pass", "", "  )", "]"]]
    assert changes._moves({"a.py": trivial}, {"b.py": trivial}, []) == []


def test_a_renamed_files_own_edits_are_not_moves():
    """Lines that leave the old name and arrive under the new one are the rename, not a move."""
    rows = [["alpha beta gamma", "delta epsilon zeta", "eta theta iota", "kappa lambda mu", "nu xi omicron"]]
    assert changes._moves({"old.py": rows}, {"new.py": rows}, [changes.Renamed("old.py", "new.py", 80)]) == []
    assert len(changes._moves({"old.py": rows}, {"new.py": rows}, [])) == 1


def test_a_quoted_path_reads_back():
    """git quotes a name with special bytes and ends one holding a space with a tab."""
    assert changes._side('"b/odd\\tname.py"', "b/") == "odd\tname.py"
    assert changes._side("b/with space.py\t", "b/") == "with space.py"
    assert changes._side("/dev/null", "a/") is None


def test_the_command_proposes_and_writes_nothing(repo, capsys):
    """End to end through the CLI: the proposals print as commands, and no lesson changes."""
    store = Client()._local_store()
    for n in LESSONS:
        store.add_node(n)
    before = {n.id: n.files for n in store.all_nodes()}
    assert main(["changes", "--base", "main", "--head", "work"]) == 0
    out = capsys.readouterr().out
    assert "src/legacy.py → src/kept.py (100% alike)" in out
    assert "6 lines from src/engine.py to src/helpers.py" in out
    assert "→ okl update renamed --files src/kept.py" in out
    assert "→ okl update moved --files src/engine.py,src/helpers.py" in out
    assert "still named in README.md:1" in out
    assert {n.id: n.files for n in Client()._local_store().all_nodes()} == before
    assert main(["changes", "--base", "main", "--head", "work", "--format", "json"]) == 0
    rep = json.loads(capsys.readouterr().out)
    assert {p["id"] for p in rep["proposals"]} == {"renamed", "deleted", "moved"}


def test_no_store_still_lists_the_events(repo, capsys):
    """With no store named, the events still print and no store is created (#21)."""
    (repo / ".okl" / "config.json").unlink()
    assert main(["changes", "--base", "main", "--head", "work"]) == 0
    got = capsys.readouterr()
    assert "no lessons are matched" in got.err
    assert "1 renamed" in got.out
    assert not (repo / ".okl" / "okl.db").exists()


def test_a_change_with_nothing_structural_says_so(repo, capsys):
    """An empty range says so rather than printing nothing."""
    assert main(["changes", "--base", "work", "--head", "work"]) == 0
    assert "nothing structural" in capsys.readouterr().out


def test_a_base_git_cannot_find_is_refused(repo, capsys):
    """A base git cannot resolve is exit 2, said on stderr."""
    assert main(["changes", "--base", "no-such-branch"]) == 2
    assert "okl changes:" in capsys.readouterr().err
