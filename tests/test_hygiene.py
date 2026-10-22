"""Hygiene: trace-shaped and over-scoped records, the rates `okl metric` reports (#252),
and the warning `okl seed` prints or fails on (#255)."""
import json
import sqlite3

from okl import core, hygiene
from okl.store import Store


def test_trace_shaped_records_are_detected_and_prose_is_not():
    """Diff markers, tracebacks, shell prompts and sheer length flag a record; a long but prose-shaped one passes."""
    assert hygiene.trace_signals({"body": "diff --git a/x b/x\n+++ b/x\n@@ -1 +1 @@"}) == ["diff markers"]
    assert "stack-trace lines" in hygiene.trace_signals({"fix": 'Traceback (most recent call last)\n  File "a.py", line 3'})
    assert "shell prompt lines" in hygiene.trace_signals({"body": "$ pytest -q\n3 passed"})
    assert hygiene.trace_signals({"body": "The cause is a race between two writers. " * 20}) == []
    assert any(s.startswith("over") for s in hygiene.trace_signals({"body": "x\n" * 20}))


def test_over_scope_reads_subject_fields_of_org_records_only():
    """An absolute path, a deep file path or a known repo name in title/symptom/fix flags an org record; the body and repo-scoped records are left alone."""
    assert hygiene.overscope_signals({"scope": "org", "fix": "edit /Users/me/proj/app.py"}) == ["an absolute path"]
    assert hygiene.overscope_signals({"scope": "org", "symptom": "see src/okl/cli/parser.py"}) == ["a repository-deep file path"]
    assert hygiene.overscope_signals({"scope": "org", "title": "the Quartz pipeline drops rows"}, ["quartz"]) == ["a repository's name: quartz"]
    assert hygiene.overscope_signals({"scope": "org", "body": "found in src/okl/cli/parser.py"}) == []
    assert hygiene.overscope_signals({"scope": "repo:x", "fix": "edit /Users/me/proj/app.py"}) == []
    assert hygiene.overscope_signals({"scope": "org", "fix": "pin it in pyproject.toml"}) == []


def test_the_log_keeps_which_briefed_lessons_were_stale(tmp_path):
    """The exposure log records the drift marks the briefing carried, and the report rates them."""
    s = Store(f"sqlite:///{tmp_path}/okl.db")
    a = core.record(s, type="Rule", title="pin the gating linter version", scope="org")
    b = core.record(s, type="Rule", title="close the sqlite connection you open", scope="org")
    s.log_briefing("app", [a, b], drifted_ids=[a])
    s.log_briefing("app", [a, b])
    assert [x.drifted_ids for x in s.briefings("app")] == [(a,), ()]
    report = core.hygiene_report(s, "app")
    assert report["stale_use"]["briefings"] == 2
    assert report["stale_use"]["with_drifted"] == 1
    assert report["stale_use"]["lessons"][0]["id"] == a


def test_a_store_from_before_the_drift_column_reads_old_rows_as_not_drifted(tmp_path):
    """Opening an older store adds the column; its existing rows read back with no drifted ids."""
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE briefing(at INTEGER NOT NULL, repo TEXT NOT NULL, node_ids TEXT NOT NULL)")
    con.execute("INSERT INTO briefing VALUES(1, 'app', ?)", (json.dumps(["x"]),))
    con.commit(); con.close()
    s = Store(f"sqlite:///{db}")
    assert [(x.node_ids, x.drifted_ids) for x in s.briefings("app")] == [(("x",), ())]
    s.log_briefing("app", ["y"], drifted_ids=["y"])
    assert s.briefings("app")[-1].drifted_ids == ("y",)


def test_record_briefing_logs_the_drift_marks_the_briefing_carries():
    """core.record_briefing writes the ids the annotated result marks as drifted."""
    s = Store("sqlite:///:memory:")
    a = core.record(s, type="Rule", title="pin the gating linter version", scope="org")
    result = core.check(s, repo="app", task="pin the linter version in CI")
    for rec in result["rules"]:
        if rec["id"] == a:
            rec["drift"] = {"reason": "changed since last verified"}
    assert core.record_briefing(s, "app", result)
    assert s.briefings("app")[0].drifted_ids == (a,)


def test_over_scope_rate_counts_live_org_lessons(tmp_path):
    """The rate's denominator is live org lessons; flagged ones are listed with their signals."""
    s = Store(f"sqlite:///{tmp_path}/okl.db")
    core.record(s, type="Rule", title="pin the gating linter version", scope="org")
    core.record(s, type="Rule", title="the order service's scraper", scope="org",
                fix="edit /Users/me/orders/app.py")
    core.record(s, type="Rule", title="a repo's own rule", scope="repo", repo="orders",
                fix="edit /Users/me/orders/app.py")
    report = core.hygiene_report(s, "orders")
    assert report["over_scope"]["org_lessons"] == 2
    assert report["over_scope"]["flagged"] == 1
    assert report["over_scope"]["lessons"][0]["signals"][0] == "an absolute path"


def test_seed_warns_and_strict_refuses(tmp_path, monkeypatch, capsys):
    """okl seed prints one warning per flagged org record and still imports; --strict imports nothing and exits 2."""
    import argparse

    from okl.cli.packs import cmd_seed
    from okl.client import Client
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OKL_DATABASE_URL", raising=False)
    monkeypatch.delenv("OKL_SERVICE_URL", raising=False)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "t"}))
    pack = tmp_path / "pack.json"
    pack.write_text(json.dumps({"nodes": [
        {"key": "ok", "type": "Rule", "title": "pin the gating linter", "scope": "org", "repo": "a"},
        {"key": "trace", "type": "Defect", "title": "the import failed", "scope": "org", "repo": "a",
         "body": "diff --git a/x b/x\n+++ b/x\n@@ -1 +1 @@"},
        {"key": "deep", "type": "Rule", "title": "scoped rule", "scope": "org", "repo": "a",
         "fix": "edit src/orders/api/views.py"},
    ]}))
    args = argparse.Namespace(path=str(pack), all=False, strict=False)
    assert cmd_seed(args) == 0
    err = capsys.readouterr().err
    assert "trace: trace-shaped" in err and "deep: over-scoped" in err and "ok:" not in err
    assert len(Client().all_nodes()) == 3
    strict = argparse.Namespace(path=str(pack), all=False, strict=True)
    assert cmd_seed(strict) == 2
    assert "nothing imported" in capsys.readouterr().err


def test_records_without_a_symptom_are_warned_about_once_per_batch():
    """Advice records with no symptom earn one aggregated line; a Decision needs none."""
    recs = [{"key": "a", "type": "Rule", "title": "pin it", "scope": "org"},
            {"key": "b", "type": "Defect", "title": "it broke", "scope": "org", "symptom": "x fails"},
            {"key": "c", "type": "Decision", "title": "we chose y", "scope": "org"},
            {"key": "d", "type": "Gate", "title": "run the check", "scope": "org"}]
    lines = hygiene.hygiene_warnings(recs)
    assert len(lines) == 1 and lines[0].startswith("2 record(s) have no symptom (a, d)")
    assert hygiene.hygiene_warnings([recs[1], recs[2]]) == []
