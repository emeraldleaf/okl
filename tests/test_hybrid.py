"""The semantic arm beside the full-text search (#258): fusion, the floor's semantic pass, and
its fail-open fallback, tested with a stub model so the suite needs no ML stack."""
from __future__ import annotations

import hashlib
import math
import re

import pytest

from okl import core, semantic
from okl.client import hybrid_setting
from okl.store import Store

# Words the stub treats as one concept, so a paraphrase lands near its lesson the way a real
# embedding would, while unrelated text does not.
_CONCEPTS = {"token": "C_TOKEN", "credential": "C_TOKEN", "jwt": "C_TOKEN",
             "storage": "C_STORE", "localstorage": "C_STORE", "saved": "C_STORE",
             "refresh": "C_RELOAD", "reload": "C_RELOAD",
             "logged": "C_SIGN", "signed": "C_SIGN", "out": "C_OUT", "off": "C_OUT"}
_STOP = {"the", "a", "an", "is", "on", "to", "in", "of", "every", "and", "or"}


class FakeModel:
    """Bag of concepts hashed into 64 dimensions, unit length, in model2vec's encode shape."""

    def encode(self, texts: list[str], normalize: bool = True) -> list[list[float]]:
        """Unit vectors for `texts`; `normalize` is accepted for the real model's signature."""
        out = []
        for text in texts:
            v = [0.0] * 64
            for w in re.findall(r"[a-z0-9]+", text.lower()):
                if w in _STOP:
                    continue
                w = _CONCEPTS.get(w, w)
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 64] += 1.0  # noqa: S324 - a hash, not a secret
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


@pytest.fixture
def store():
    """A fresh in-memory store, closed after the test."""
    s = Store("sqlite:///:memory:")
    yield s
    s.close()


@pytest.fixture
def fake_model(monkeypatch):
    """The stub model in place of the real one, so no extra or download is needed."""
    monkeypatch.setattr(semantic, "load_model", lambda *a, **k: FakeModel())


def _seed(store):
    a = core.record(store, type="Rule", title="token storage", scope="org",
                    symptom="an access token written to web storage", fix="keep it in memory",
                    aliases="logged out on refresh")
    b = core.record(store, type="Rule", title="pagination", scope="org",
                    symptom="an offset-based query over a large table", fix="use a cursor")
    return a, b


def test_build_index_embeds_each_record_once_and_only_changed_text_again(store, fake_model):
    """`okl embed` writes one vector per record and skips records whose text is unchanged."""
    a, _ = _seed(store)
    first = semantic.build_index(store)
    assert (first["embedded"], first["unchanged"], first["removed"], first["dim"]) == (2, 0, 0, 64)
    again = semantic.build_index(store)
    assert (again["embedded"], again["unchanged"]) == (0, 2)
    core.update(store, a, fix="keep it in memory, never in web storage")
    assert semantic.build_index(store)["embedded"] == 1


def test_semantic_search_ranks_by_cosine_and_round_trips_the_vectors(store, fake_model):
    """Nearest first by cosine over the stored vectors, which read back as they were written."""
    a, b = _seed(store)
    semantic.build_index(store)
    ranked = semantic.search(store, "where should the JWT be saved", limit=5)
    assert [i for i, _ in ranked] == [a, b] and ranked[0][1] > 0.4 > ranked[1][1]
    assert semantic.unpack(semantic.pack([0.5, -1.0, 0.25])) == [0.5, -1.0, 0.25]


def test_a_paraphrase_with_no_shared_word_is_briefed_through_the_semantic_arm(store, fake_model):
    """The case the whole arm exists for: the task and the lesson share meaning but no words.
    Full-text finds nothing; the semantic arm scores the lesson above the subject line, so the
    floor keeps it, with no matched words and its score on the record."""
    a, _ = _seed(store)
    semantic.build_index(store)
    task = "the signed-in credential is lost on every reload"
    assert core.check(store, repo="r", task=task)["rules"] == []            # full-text only
    for method in ("rrf", "linear"):
        res = core.check(store, repo="r", task=task, hybrid=method)
        assert [r["id"] for r in res["rules"]] == [a], method
        assert res["rules"][0]["matched_terms"] == [] and res["rules"][0]["semantic_score"] >= semantic.SUBJECT_SIMILARITY
        assert res["hybrid"] == method and "hybrid_unavailable" not in res


def test_a_record_only_the_semantic_arm_found_is_on_the_subject_only_by_meaning(store, fake_model):
    """REPORT §4q, first pass: the fused window is wider than the full-text one, so the
    one-word title-or-symptom rule admitted records full-text would never have reached. A
    semantic-only candidate below the line stays out even when it shares a title word."""
    a, _ = _seed(store)
    # "pagination" is in the record's title, so by the word rules alone one shared word would
    # make it the subject; the stub gives it a low cosine for this task.
    task = "paginate the admin screen without a credential leak on reload"
    semantic.build_index(store)
    res = core.check(store, repo="r", task=task, hybrid="linear")
    titles = [r["title"] for r in res["rules"]]
    assert "pagination" not in titles, titles
    assert res["weak_matches"] >= 1


def test_hybrid_falls_back_to_full_text_and_says_why_when_the_model_is_missing(store, monkeypatch):
    """A briefing never fails on the optional arm: no extra or no cached model means the
    full-text briefing, with the reason in the result for the person to act on."""
    a, _ = _seed(store)
    res = core.check(store, repo="r", task="an access token written to web storage", hybrid="rrf")
    assert [r["id"] for r in res["rules"]] == [a]
    assert res["hybrid"] is None and "okl embed" in res["hybrid_unavailable"]   # no vectors yet

    def missing(*a, **k):
        raise semantic.SemanticUnavailableError("the hybrid extra is not installed")
    monkeypatch.setattr(semantic, "load_model", missing)
    store.put_embedding(a, semantic.MODEL_ID, "h", semantic.pack([1.0]))
    res = core.check(store, repo="r", task="an access token written to web storage", hybrid="rrf")
    assert [r["id"] for r in res["rules"]] == [a] and "extra" in res["hybrid_unavailable"]


def test_a_task_with_no_subject_words_does_not_report_the_arm_as_on(store, fake_model):
    """"ok go" has no subject words, so neither arm runs; the result says the arm did not
    run rather than reporting hybrid as on (review on #267)."""
    _seed(store)
    semantic.build_index(store)
    res = core.check(store, repo="r", task="ok go", hybrid="linear")
    assert res["hybrid"] is None and "subject words" in res["hybrid_unavailable"]
    assert res["match_count"] == 0


def test_fusion_orders_candidates_by_rank_fusion_or_convex_combination(store):
    """RRF sums reciprocal ranks; linear mixes a rank-normalised full-text score with the
    min-max-normalised cosine. A record only one arm found still takes its place."""
    a, b = _seed(store)
    c = core.record(store, type="Rule", title="third", scope="org", symptom="unrelated")
    fts = [store.get_node(a), store.get_node(b)]
    nearest = [(b, 0.9), (c, 0.8)]
    assert [n.id for n in core._fuse(store, fts, nearest, "rrf")] == [b, a, c]
    assert [n.id for n in core._fuse(store, fts, nearest, "linear")] == [b, a, c]
    with pytest.raises(ValueError, match="rrf"):
        core._fuse(store, fts, nearest, "cosine")
    # Tied cosines: the raw score stands in for the zero-range min-max, so a record only the
    # semantic arm found still carries weight instead of falling to the end (review on #267).
    tied = core._fuse(store, fts, [(b, 0.6), (c, 0.6)], "linear")
    assert [n.id for n in tied] == [b, a, c]   # c weighs 0.3, not 0; a's full-text rank still beats it


def test_hybrid_setting_reads_the_environment_over_the_config():
    """OKL_HYBRID wins over the config key; off and empty disable; 1 and rrf mean rank fusion."""
    assert hybrid_setting(None, None) is None and hybrid_setting(None, "rrf") == "rrf"
    assert hybrid_setting("off", "rrf") is None and hybrid_setting("1", None) == "linear"
    assert hybrid_setting(None, "linear") == "linear" and hybrid_setting("", "linear") is None
    with pytest.raises(ValueError, match="hybrid"):
        hybrid_setting("cosine", None)


def test_embed_command_exits_2_with_the_remedy_when_the_arm_cannot_run(tmp_path, monkeypatch, capsys):
    """`okl embed` without the extra (or the model) names what to install, and writes nothing."""
    from okl.cli import main
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")
    monkeypatch.chdir(tmp_path)

    def missing(*a, **k):
        raise semantic.SemanticUnavailableError("the hybrid extra is not installed: pip install 'observed-knowledge-ledger[hybrid]'")
    monkeypatch.setattr(semantic, "load_model", missing)
    assert main(["embed"]) == 2
    assert "NOT EMBEDDED" in capsys.readouterr().err
