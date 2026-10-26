"""The relevance floor: a briefing is not twelve records chosen by one word in common.

The search is an OR of the task's subject words, so before the floor a short or generic
task filled every slot with records sharing a single word with it (#257, measured in
evals/results/probe-rephrase-20261021.txt). These tests pin the rule and what it reports.
"""
from okl import core, semantic
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
    res = core.check(s, decision="floor", repo="r", task="this seems like a major point to scrutinize")
    assert res["match_count"] == 0
    assert res["weak_matches"] == 1
    assert "1 record(s) sharing a single word" in core.render_check_for_agent(res)
    assert core.briefing_notice(res) == ("okl · nothing briefed: 1 weak match(es) on a "
                                         "single word were left out")


def test_two_shared_words_pass_and_the_words_travel_in_the_json():
    """Two shared subject words clear the floor, and the JSON names them per record."""
    s = _store()
    res = core.check(s, decision="floor", repo="r", task="add a CI step that installs a linter")
    titles = [r["title"] for r in res["rules"]]
    assert "Pin every tool that gates CI" in titles
    pinned = next(r for r in res["rules"] if r["title"].startswith("Pin"))
    assert set(pinned["matched_terms"]) >= {"ci", "linter"}
    assert res["weak_matches"] == 0


def test_one_shared_word_in_the_title_is_enough():
    """One shared word is enough when it is the record's subject: in its title or symptom."""
    s = _store()
    res = core.check(s, decision="floor", repo="r", task="add endpoint that sets a price")
    assert [d["title"] for d in res["relevant_defects"]] == ["price tamper"]


def test_a_one_word_task_needs_one_shared_word():
    """A one-word task lowers the floor to one word."""
    s = _store()
    res = core.check(s, decision="floor", repo="r", task="price")
    assert [d["title"] for d in res["relevant_defects"]] == ["price tamper"]


def test_a_weak_hit_linked_to_a_kept_hit_stays():
    """A gate below the floor stays when it CATCHES a defect above it."""
    s = Store("sqlite:///:memory:")
    d = core.record(s, type="Defect", title="temporal decoder axes", scope="org")
    g = core.record(s, type="Gate", title="laptop dry-run decoder shapes", scope="org")
    core.link(s, g, "CATCHES", d)
    res = core.check(s, decision="floor", repo="r", task="temporal segmentation decoder axes")
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
        res = core.check(s, decision="floor", repo="okl", task=t["task"], interests=None)
        ids = {r["id"] for b in ("rules", "relevant_defects", "armed_gates") for r in res[b]}
        if t["defect_node"] not in ids:
            missing.append(t["id"])
    assert not missing, missing


def test_the_fetch_widens_when_the_floor_empties_a_full_window():
    """When ranking puts forty single-word matches ahead of the one record that shares both
    words, the first window holds only weak matches; the fetch widens until the qualifying
    record is seen (review on #259). A store subclass stands in for that ranking, since
    BM25 would put the two-word match first on its own."""

    class WeakFirst(Store):
        def search(self, query, limit=20, **kw):
            rows = super().search(query, limit=200, **kw)
            rows.sort(key=lambda n: n.title == "money handling")   # the strong one last
            return rows[:limit]

    s = WeakFirst("sqlite:///:memory:")
    for i in range(40):
        core.record(s, type="Rule", title=f"filler rule {i}", scope="org", body="the price is set")
    wanted = core.record(s, type="Rule", title="money handling", scope="org",
                         body="the catalogue sets the price")
    assert wanted not in {n.id for n in s.search("price catalogue", limit=36)}
    res = core.check(s, decision="floor", repo="r", task="price catalogue")
    assert wanted in {r["id"] for r in res["rules"]}
    assert res["match_count"] == 1


def test_the_floor_changes_no_eval_briefing(tmp_path, monkeypatch):
    """REPORT §4n rests on this: on the eight eval tasks the briefed ids are the same with
    the floor and without it, so the A/B instrument cannot observe the change. The day this
    fails, the floor has reached an eval briefing and a live run is due."""
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
    # §4n measured the packs before they carried triggers (they do since §4w); the claim
    # under test is that one, so the store is that one.
    import dataclasses
    for node in s.all_nodes():
        if node.triggers:
            s.add_node(dataclasses.replace(node, triggers=None))
    tasks = [json.loads(line) for line in (root / "evals" / "tasks.jsonl").read_text().splitlines()
             if line.strip()]
    changed = {}
    for t in tasks:
        with_floor = core.briefed_ids(core.check(s, decision="floor", repo="okl", task=t["task"], interests=None))
        hits, _, _, _ = core._live_hits(s, t["task"], 12, "repo:okl", None)
        without = [n.id for n in hits[:12]]
        # briefed_ids reads bucket order, _live_hits rank order: compare the sets.
        if set(with_floor) != set(without):
            changed[t["id"]] = (sorted(set(without) - set(with_floor)), sorted(set(with_floor) - set(without)))
    assert not changed, changed


def test_no_neighbour_lookup_when_nothing_clears_the_floor():
    """With no strong hit there is nothing a link could attach to, so the floor returns
    without asking the store for neighbours (review on #259)."""

    class NoNeighbours(Store):
        def neighbors(self, node_id, rels=None):
            raise AssertionError("neighbors() must not be called when no hit is strong")

    s = NoNeighbours("sqlite:///:memory:")
    for i in range(3):
        core.record(s, type="Rule", title=f"filler {i}", scope="org", body="the price is set")
    res = core.check(s, decision="floor", repo="r", task="price catalogue")
    assert res["match_count"] == 0 and res["weak_matches"] == 3


def test_exhaustion_is_judged_against_the_window_last_asked_for():
    """Three full windows each holding retired lessons leave the loop having widened its
    next window after the last search; exhaustion must compare the last result with the
    window that produced it, or check() skips the floor's widening (review on #259)."""
    import dataclasses

    class InOrder(Store):
        order: list[str] = []

        def search(self, query, limit=20, **kw):
            rows = super().search(query, limit=200, **kw)
            # Insertion order, by id: created_at ties within a millisecond and BM25 ties on
            # identical text, so neither orders the same way on every machine (CI on #259).
            rows.sort(key=lambda n: self.order.index(n.id))
            return rows[:limit]

    s = InOrder("sqlite:///:memory:")
    ids = [core.record(s, type="Rule", title="pin the linter", scope="org") for _ in range(8)]
    InOrder.order = ids
    for i in (0, 3, 5):   # one retired lesson inside each of the windows 3, 4 and 6
        s._impl.upsert_node(dataclasses.replace(s.get_node(ids[i]), status="obsolete"))
    live, _replaced, exhausted, _ = core._live_hits(s, "pin the linter", 1, "repo:r", None)
    assert len(live) == 3
    assert exhausted is False


def test_a_semantic_only_hit_passes_by_two_shared_words_only_when_the_knob_says_so(monkeypatch):
    """With SEMANTIC_WORD_FLOOR set, a record only the semantic arm returned is judged by the
    same two-word rule as a full-text one; one word, even in its title, is still not enough
    for it, and a cosine at the line admits it on its own (§4q). Shipped at None (REPORT
    §4u measured 2 and reverted it): then words alone admit no semantic-only record."""
    s = Store("sqlite:///:memory:")
    two = core.record(s, type="Rule", title="exit codes lie", scope="org",
                      symptom="the data job said it succeeded and wrote nothing")
    one = core.record(s, type="Rule", title="data retention", scope="org", symptom="old rows never leave")
    near = core.record(s, type="Rule", title="unrelated words entirely", scope="org", symptom="none")
    hits = [s.get_node(two), s.get_node(one), s.get_node(near)]
    cand = core.Candidates(hits, {near: semantic.SUBJECT_SIMILARITY}, frozenset(), None, False)
    assert core.SEMANTIC_WORD_FLOOR is None
    kept, matched, weak = core._apply_floor(s, hits, ["data", "job", "export"], cand)
    assert [n.id for n in kept] == [near] and weak == 2
    monkeypatch.setattr(core, "SEMANTIC_WORD_FLOOR", 2)
    kept, matched, weak = core._apply_floor(s, hits, ["data", "job", "export"], cand)
    assert [n.id for n in kept] == [two, near] and weak == 1
    assert matched[two] == ["data", "job"] and matched[one] == ["data"]
    s.close()


def test_a_common_title_word_admits_only_when_the_knob_allows_it(monkeypatch):
    """With COMMON_WORD_SHARE set, one shared word in a title admits a record only when the
    word is in at most that share of the store; two shared words and a one-word alias admit
    regardless; shipped at None, any title word admits (REPORT §4v)."""
    s = Store("sqlite:///:memory:")
    # "doc" sits in four of six titles (common); "pkce" in one (specific).
    ids = [core.record(s, type="Rule", title=f"doc rule {i} about nothing", scope="org") for i in range(4)]
    pkce = core.record(s, type="Rule", title="pkce for public clients", scope="org")
    aliased = core.record(s, type="Rule", title="browser token storage", scope="org", aliases="doc")
    hits = [s.get_node(i) for i in [*ids, pkce, aliased]]
    cand = core.Candidates(hits, {}, frozenset(n.id for n in hits), None, False)
    monkeypatch.setattr(core, "COMMON_WORD_SHARE", None)
    kept, _m, _w = core._apply_floor(s, hits, ["doc", "pkce"], cand)
    assert {n.id for n in kept} == {*ids, pkce, aliased}          # §4n's rule: any title word admits
    monkeypatch.setattr(core, "COMMON_WORD_SHARE", 0.5)
    kept, _m, _w = core._apply_floor(s, hits, ["doc", "pkce"], cand)
    assert {n.id for n in kept} == {*ids, pkce, aliased}          # four records is under the absolute minimum
    monkeypatch.setattr(core, "COMMON_WORD_MIN_RECORDS", 3)
    kept, _m, weak = core._apply_floor(s, hits, ["doc", "pkce"], cand)
    assert {n.id for n in kept} == {pkce, aliased} and weak == 4   # "doc" is in 4 of 6: too common; the alias still counts
    kept, _m, _w = core._apply_floor(s, hits, ["doc", "rule"], cand)
    assert set(ids) <= {n.id for n in kept}                        # two shared words always admit
    s.close()


def test_a_one_word_task_keeps_the_old_rule_even_for_a_common_word(monkeypatch):
    """§4v weighs the one-word match inside a longer task; a task of one subject word is its
    whole subject and still admits on that word, common or not, until a measured change says
    otherwise (#282, review on #280)."""
    s = Store("sqlite:///:memory:")
    ids = [core.record(s, type="Rule", title=f"doc rule {i}", scope="org") for i in range(8)]
    hits = [s.get_node(i) for i in ids]
    cand = core.Candidates(hits, {}, frozenset(ids), None, False)
    monkeypatch.setattr(core, "COMMON_WORD_SHARE", 0.05)
    monkeypatch.setattr(core, "COMMON_WORD_MIN_RECORDS", 3)
    kept, _m, weak = core._apply_floor(s, hits, ["doc"], cand)
    assert {n.id for n in kept} == set(ids) and weak == 0
    s.close()


def test_a_zero_common_word_share_makes_every_word_past_the_minimum_common(monkeypatch):
    """A share of 0 is a setting, not an unset knob: a word in more records than the minimum
    is common at any share above nothing, while one at the minimum still admits (review on
    #280: `COMMON_WORD_SHARE or 1.0` read 0 as unset and admitted every word)."""
    s = Store("sqlite:///:memory:")
    # "doc" sits in four of five titles, "pkce" in one; the minimum is set to three.
    ids = [core.record(s, type="Rule", title=f"doc rule {i} about nothing", scope="org") for i in range(4)]
    pkce = core.record(s, type="Rule", title="pkce for public clients", scope="org")
    hits = [s.get_node(i) for i in [*ids, pkce]]
    cand = core.Candidates(hits, {}, frozenset(n.id for n in hits), None, False)
    monkeypatch.setattr(core, "COMMON_WORD_SHARE", 0.0)
    monkeypatch.setattr(core, "COMMON_WORD_MIN_RECORDS", 3)
    kept, _m, weak = core._apply_floor(s, hits, ["doc", "pkce"], cand)
    assert {n.id for n in kept} == {pkce} and weak == 4   # "doc": 4 > 3 records, share > 0
    monkeypatch.setattr(core, "COMMON_WORD_MIN_RECORDS", 4)
    kept, _m, _w = core._apply_floor(s, hits, ["doc", "pkce"], cand)
    assert set(ids) <= {n.id for n in kept}                # 4 is not more than the minimum of 4
    s.close()
