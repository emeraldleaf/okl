"""Standing lessons (REPORT §4am): the ones a repo names on every task briefing, one line each."""
import json

import pytest

from okl import core
from okl.cli import main
from okl.client import Client
from okl.store import Node


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A configured repo whose store holds lessons of every kind standing has to sort."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "interests": ["python"]}, indent=2) + "\n")
    store = Client()._local_store()
    for node in [
        Node(id="claims", type="Rule", title="Wire a doc claim to a check that governs the doc and the code",
             scope="org", fix="Record a rule with files on the doc. Then verify it."),
        Node(id="exits", type="Rule", title="Exit codes are this CLI's public API", scope="repo:r",
             fix="0 clean, 1 findings, 2 refused."),
        Node(id="gone", type="Rule", title="A retired lesson", scope="org", status="obsolete"),
        Node(id="theirs", type="Rule", title="Another repo's lesson", scope="repo:other"),
        Node(id="sqlite", type="Defect", title="Close every sqlite connection a test opens", scope="org",
             fix="Use contextlib.closing."),
    ]:
        store.add_node(node)
    return tmp_path


def _stand(repo, ids):
    path = repo / ".okl" / "config.json"
    path.write_text(json.dumps({**json.loads(path.read_text()), "standing": ids}, indent=2) + "\n")


def test_a_task_briefing_names_each_standing_lesson_once(repo):
    """Retired, another repo's and missing ids are skipped; one the task matched is not repeated."""
    _stand(repo, ["claims", "exits", "gone", "theirs", "nowhere", "sqlite"])
    result = Client().check("close the sqlite connection this test opens")
    assert "sqlite" in core.briefed_ids(result) or "sqlite" in {e["id"] for e in result.get("also_matched") or []}
    assert [e["id"] for e in result["standing"]] == ["claims", "exits"]
    text = core.render_check_for_agent(result)
    assert "### Standing lessons in this repo (2)" in text
    assert "- [claims] Wire a doc claim to a check that governs the doc and the code" in text
    assert "standing" not in core.briefed_ids(result)        # named, not shown, as the second tier is


def test_they_reach_a_task_nothing_else_matched(repo):
    """The case they exist for: words that match no lesson still get the standing ones, in both forms."""
    _stand(repo, ["claims"])
    result = Client().check("tidy the release notes wording")
    assert [e["id"] for e in result["standing"]] == ["claims"]
    assert "[claims]" in core.render_check_for_agent(result)
    assert "[claims]" in core.render_actions_only(result)


def test_off_by_default_and_by_switch(repo, monkeypatch):
    """No list, no section; OKL_STANDING=0 leaves a configured list out, for a measurement without it."""
    assert "standing" not in Client().check("tidy the release notes wording")
    _stand(repo, ["claims"])
    monkeypatch.setenv("OKL_STANDING", "0")
    assert "standing" not in Client().check("tidy the release notes wording")


def test_a_file_briefing_gets_none(repo):
    """A file briefing repeats on every read, so standing lessons are for task briefings only."""
    _stand(repo, ["claims"])
    (repo / "a.py").write_text("x = 1\n")
    assert "standing" not in Client().check("", paths=["a.py"])


def test_at_most_the_measured_ten(repo):
    """Twelve listed, ten named: the size §4am measured."""
    store = Client()._local_store()
    ids = [f"s{i}" for i in range(core.STANDING_CAP + 2)]
    for i in ids:
        store.add_node(Node(id=i, type="Rule", title=f"standing lesson {i}", scope="org"))
    _stand(repo, ids)
    assert len(Client().check("tidy the release notes wording")["standing"]) == core.STANDING_CAP


def test_the_command_adds_lists_and_removes_keeping_the_rest_of_the_config(repo, capsys):
    """Add is idempotent and keeps every other key; removing the last drops the key."""
    assert main(["standing", "add", "claims", "exits", "claims"]) == 0
    config = json.loads((repo / ".okl" / "config.json").read_text())
    assert config == {"repo": "r", "interests": ["python"], "standing": ["claims", "exits"]}
    assert "[exits] Exit codes are this CLI's public API" in capsys.readouterr().out
    assert main(["standing", "remove", "claims", "exits"]) == 0
    assert "standing" not in json.loads((repo / ".okl" / "config.json").read_text())
    assert "No standing lessons" in capsys.readouterr().out


def test_the_command_refuses_an_unknown_id_and_the_eleventh(repo, capsys):
    """Exit 2, and the config left as it was, for an id with no lesson and for an add past ten."""
    before = (repo / ".okl" / "config.json").read_text()
    assert main(["standing", "add", "nowhere"]) == 2
    assert "no lesson with id nowhere" in capsys.readouterr().err
    store = Client()._local_store()
    for i in range(core.STANDING_CAP + 1):
        store.add_node(Node(id=f"s{i}", type="Rule", title=f"lesson {i}", scope="org"))
    assert main(["standing", "add", *[f"s{i}" for i in range(core.STANDING_CAP + 1)]]) == 2
    assert "at most 10" in capsys.readouterr().err
    assert (repo / ".okl" / "config.json").read_text() == before


def test_the_command_needs_a_config(tmp_path, monkeypatch, capsys):
    """With no .okl/config.json there is nowhere to keep the list."""
    monkeypatch.chdir(tmp_path)
    assert main(["standing"]) == 2
    assert "run okl init first" in capsys.readouterr().err
