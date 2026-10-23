"""`aliases`: the words a developer uses when a lesson bites, on every surface that writes a lesson (#258)."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _okl(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the CLI against a throwaway store under tmp_path."""
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_SERVICE_URL", "OKL_TOKEN")}
    env["OKL_DATABASE_URL"] = f"sqlite:///{tmp_path / 'store.db'}"
    return subprocess.run([sys.executable, "-m", "okl", *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True)


def test_record_update_and_show_carry_aliases(tmp_path):
    """`--alias` is repeatable on record, replaces on update, clears with an empty value,
    and `okl show` prints the field; a prompt in the alias words is briefed the lesson."""
    # ARRANGE / ACT — record with two aliases
    r = _okl(tmp_path, "record", "--type", "Rule", "--title", "token storage", "--scope", "org",
             "--symptom", "an access token written to web storage", "--fix", "keep it in memory",
             "--alias", "logged out on refresh", "--alias", "session lost", "--alias", "JWT", "--id", "t1")
    assert r.returncode == 0, r.stdout + r.stderr

    # ASSERT — stored joined, shown, and found by a prompt sharing only an alias word
    shown = json.loads(_okl(tmp_path, "show", "t1", "--format", "json").stdout)
    assert shown["aliases"] == "logged out on refresh; session lost; JWT"
    assert "  aliases: logged out on refresh; session lost; JWT" in _okl(tmp_path, "show", "t1").stdout
    briefed = json.loads(_okl(tmp_path, "check", "--repo", "r", "--interests", "", "--format", "json",
                              "--task", "where should the JWT live in this app").stdout)
    assert [x["id"] for x in briefed["rules"]] == ["t1"]

    # ACT / ASSERT — update replaces; an empty value clears
    u = _okl(tmp_path, "update", "t1", "--alias", "kicked out after reload")
    assert u.returncode == 0, u.stdout + u.stderr
    assert json.loads(_okl(tmp_path, "show", "t1", "--format", "json").stdout)["aliases"] == "kicked out after reload"
    u = _okl(tmp_path, "update", "t1", "--alias", "")
    assert u.returncode == 0, u.stdout + u.stderr
    assert not json.loads(_okl(tmp_path, "show", "t1", "--format", "json").stdout).get("aliases")


def test_an_empty_alias_list_clears_on_update_and_a_list_records():
    """`core.update(aliases=[])` is an explicit clear, not "not given"; `core.record` takes a
    list the way a pack writes it (review on #266)."""
    from okl import core
    from okl.store import Store
    s = Store("sqlite:///:memory:")
    try:
        a = core.record(s, type="Rule", title="t", scope="org", aliases=["logged out", "session lost"])
        assert s.get_node(a).aliases == "logged out; session lost"
        assert core.update(s, a, aliases=[])["aliases"] in ("", None)
        assert not s.get_node(a).aliases
        b = core.record(s, type="Rule", title="u", scope="org", aliases=[])
        assert s.get_node(b).aliases is None
    finally:
        s.close()


def test_a_seed_pack_may_write_aliases_as_a_list(tmp_path):
    """Packs write `aliases` as a JSON list; the loader joins it the way the CLI does."""
    pack = tmp_path / "my-pack.json"
    pack.write_text(json.dumps({"nodes": [
        {"key": "a", "type": "Rule", "title": "token storage", "scope": "org", "repo": None,
         "symptom": "an access token written to web storage",
         "aliases": ["logged out on refresh", " session lost "]}]}))
    r = _okl(tmp_path, "seed", str(pack))
    assert r.returncode == 0, r.stdout + r.stderr
    shown = json.loads(_okl(tmp_path, "show", "seed:my-pack:a", "--format", "json").stdout)
    assert shown["aliases"] == "logged out on refresh; session lost"
