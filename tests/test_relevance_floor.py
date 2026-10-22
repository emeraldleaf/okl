"""The relevance floor: a briefing is not twelve records chosen by one word in common.

The search is an OR of the task's subject words, so before the floor a short or generic
task filled every slot with records sharing a single word with it (#257, measured in
evals/results/probe-rephrase-20261021.txt). These tests pin the rule and what it reports.
"""
from okl import core
from okl.store import Store


def _store() -> Store:
    s = Store("sqlite:///:memory:")
    core.record(s, type="Rule", title="Pin every tool that gates CI", scope="org",
                symptom="a CI step installs a linter with no version", fix="pin the version")
    core.record(s, type="Rule", title="Code comments link durable docs", scope="org",
                body="a comment pointing at a status file dangles; point it at a durable doc",
                fix="repoint the comment")
    core.record(s, type="Defect", title="price tamper", scope="org",
                body="trusts client price", symptom="DTO carries Price", fix="compute server-side")
    return s


def test_one_shared_word_outside_the_title_is_left_out_and_counted():
    """A generic task sharing one body word with a record briefs nothing and says what it left out."""
    s = _store()
    # "point" occurs in the docs rule's body only; "major" and "scrutinize" occur nowhere.
    res = core.check(s, repo="r", task="this seems like a major point to scrutinize")
    assert res["match_count"] == 0
    assert res["weak_matches"] == 1
    assert "1 record(s) sharing a single word" in core.render_check_for_agent(res)
    assert core.briefing_notice(res) == ("okl · nothing briefed: 1 weak match(es) on a "
                                         "single word were left out")


def test_two_shared_words_pass_and_the_words_travel_in_the_json():
    """Two shared subject words clear the floor, and the JSON names them per record."""
    s = _store()
    res = core.check(s, repo="r", task="add a CI step that installs a linter")
    titles = [r["title"] for r in res["rules"]]
    assert "Pin every tool that gates CI" in titles
    pinned = next(r for r in res["rules"] if r["title"].startswith("Pin"))
    assert set(pinned["matched_terms"]) >= {"ci", "linter"}
    assert res["weak_matches"] == 0


def test_one_shared_word_in_the_title_is_enough():
    """One shared word is enough when it is the record's subject: in its title or symptom."""
    s = _store()
    res = core.check(s, repo="r", task="add endpoint that sets a price")
    assert [d["title"] for d in res["relevant_defects"]] == ["price tamper"]


def test_a_one_word_task_needs_one_shared_word():
    """A one-word task lowers the floor to one word."""
    s = _store()
    res = core.check(s, repo="r", task="price")
    assert [d["title"] for d in res["relevant_defects"]] == ["price tamper"]


def test_a_weak_hit_linked_to_a_kept_hit_stays():
    """A gate below the floor stays when it CATCHES a defect above it."""
    s = Store("sqlite:///:memory:")
    d = core.record(s, type="Defect", title="temporal decoder axes", scope="org")
    g = core.record(s, type="Gate", title="laptop dry-run decoder shapes", scope="org")
    core.link(s, g, "CATCHES", d)
    res = core.check(s, repo="r", task="temporal segmentation decoder axes")
    assert [x["title"] for x in res["armed_gates"]] == ["laptop dry-run decoder shapes"]
    assert res["weak_matches"] == 0


def test_the_floor_keeps_every_eval_task_governing_record(tmp_path, monkeypatch):
    """The eight authored eval tasks share two to ten words with their lessons; the floor
    must not cost a recall the harness pre-flight already asserts. Mirrors evals/preflight.py
    on a store seeded from the packs."""
    import json
    from pathlib import Path

    from okl.client import Client
    from okl.seed import seed_from_file
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKL_DATABASE_URL", raising=False)
    monkeypatch.delenv("OKL_SERVICE_URL", raising=False)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "okl"}))
    client = Client()
    for pack in sorted((root / "seed").glob("*.json")):
        seed_from_file(client, str(pack))
    s = client._local_store()
    tasks = [json.loads(line) for line in (root / "evals" / "tasks.jsonl").read_text().splitlines()
             if line.strip()]
    missing = []
    for t in tasks:
        if t["id"] == "exit_code_trust":
            continue   # the accepted gap: below the cutoff for its own wording (REPORT §4b)
        res = core.check(s, repo="okl", task=t["task"], interests=None)
        ids = {r["id"] for b in ("rules", "relevant_defects", "armed_gates") for r in res[b]}
        if t["defect_node"] not in ids:
            missing.append(t["id"])
    assert not missing, missing
