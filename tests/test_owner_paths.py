"""Owner-approved paths (#329): the CODEOWNERS block `okl init --owner` writes, and what
`okl doctor` says about whether GitHub enforces it.

A thesis an agent keeps updating is safe only if a person approves each change, and only the
forge can make that hold: these tests cover okl's half, writing the code-owner lines without
clobbering a team's file, and reporting honestly whether the branch rule behind them is real.
"""
from base64 import b64encode
from pathlib import Path

import pytest

from okl import codeowners, protection

TEAM = "# the platform team owns everything by default\n* @acme/platform\n/docs/ @acme/docs\n"


def test_a_new_file_names_the_owner_for_each_path_and_itself():
    """With no CODEOWNERS, okl writes only its block."""
    text, notes = codeowners.merge("", "@ana", ["docs/THESIS.md", ".github/CODEOWNERS"])

    assert notes == []
    assert codeowners.owned(text) == {"docs/THESIS.md": ["@ana"], ".github/CODEOWNERS": ["@ana"]}
    assert text.startswith(codeowners.BEGIN) and text.rstrip().endswith(codeowners.END)


def test_an_existing_file_keeps_every_line_and_okl_goes_last():
    """CODEOWNERS applies the last matching line, so okl's block goes after the team's rules:
    `* @acme/platform` above it does not take the thesis back."""
    text, _ = codeowners.merge(TEAM, "@ana", ["docs/THESIS.md"])

    assert text.startswith(TEAM.rstrip("\n"))
    assert text.index("* @acme/platform") < text.index("docs/THESIS.md @ana")


def test_a_path_the_team_already_owns_is_left_to_its_line_and_named():
    """okl never rewrites a team's own line for a path; it says whose the path is."""
    text, notes = codeowners.merge(TEAM + "docs/THESIS.md @acme/leads\n", "@ana", ["docs/THESIS.md", "ADR/"])

    assert "docs/THESIS.md @ana" not in text
    assert codeowners.owned(text) == {"ADR/": ["@ana"]}
    assert notes == ["docs/THESIS.md is already owned by @acme/leads on a line of its own; okl leaves it"]


def test_a_second_run_rewrites_the_block_and_nothing_else():
    """Idempotent: the same run twice is one block; a new owner replaces the old one."""
    once, _ = codeowners.merge(TEAM, "@ana", ["docs/THESIS.md"])
    twice, _ = codeowners.merge(once, "@ana", ["docs/THESIS.md"])
    moved, _ = codeowners.merge(once, "@ben", ["docs/THESIS.md"])

    assert twice == once
    assert codeowners.owned(moved) == {"docs/THESIS.md": ["@ben"]}
    assert moved.count(codeowners.BEGIN) == 1


def test_remove_takes_out_okls_block_and_only_it():
    """Uninstall leaves the team's file exactly as it was, and an okl-only file empty."""
    text, _ = codeowners.merge(TEAM, "@ana", ["docs/THESIS.md"])

    assert codeowners.remove(text) == TEAM
    assert codeowners.remove(codeowners.merge("", "@ana", ["docs/THESIS.md"])[0]) == ""


@pytest.mark.parametrize(("given", "owner"), [
    ("ana", "@ana"), ("@ana", "@ana"), ("@acme/platform-team", "@acme/platform-team"),
    ("ana@example.com", "ana@example.com"), ("@-bad", None), ("two words", None), ("", None),
])
def test_an_owner_is_one_codeowners_accepts(given, owner):
    """A user, a team or an email; a bare name gets its @."""
    assert codeowners.normalise_owner(given) == owner


def test_the_file_is_the_one_github_reads(tmp_path):
    """GitHub reads .github/CODEOWNERS, then CODEOWNERS, then docs/CODEOWNERS: okl writes into the
    one it reads, and creates .github/CODEOWNERS when there is none."""
    assert codeowners.location(tmp_path) == Path(".github/CODEOWNERS")
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "CODEOWNERS").write_text(TEAM)
    assert codeowners.location(tmp_path) == Path("docs/CODEOWNERS")
    (tmp_path / "CODEOWNERS").write_text(TEAM)
    assert codeowners.location(tmp_path) == Path("CODEOWNERS")


# okl doctor's answer, from recorded GitHub API answers: the shapes the REST docs give for
# repos/{repo}/rules/branches/{branch}, rulesets/{id} (current_user_can_bypass) and classic
# branches/{branch}/protection, so no test touches the network.
REPO = {"nameWithOwner": "acme/app", "defaultBranchRef": {"name": "main"}, "viewerPermission": "WRITE",
        "visibility": "PUBLIC"}
FILE = ".github/CODEOWNERS"
LINES = "docs/THESIS.md @ana\n.github/CODEOWNERS @ana\n"
PATHS = ["docs/THESIS.md", ".github/CODEOWNERS"]
OWNER_RULE = [{"type": "pull_request", "ruleset_id": 7, "parameters": {"require_code_owner_review": True}}]


def _github(*, codeowners=LINES, errors=(), rules=(), bypass="never", classic=(404, None), viewer="WRITE",
            visibility="PUBLIC"):
    """A recorded GitHub: each API path okl doctor reads, and its (status, body)."""
    answers = {
        f"repos/acme/app/contents/{FILE}?ref=main":
            (200, {"content": b64encode(codeowners.encode()).decode()}) if codeowners is not None else (404, None),
        "repos/acme/app/codeowners/errors?ref=main": (200, {"errors": list(errors)}),
        "repos/acme/app/rules/branches/main": (200, list(rules)),
        "repos/acme/app/rulesets/7?includes_parents=true": (200, {"id": 7, "current_user_can_bypass": bypass}),
        "repos/acme/app/branches/main/protection": classic,
    }
    info = {**REPO, "viewerPermission": viewer, "visibility": visibility}
    return dict(get=lambda path: answers[path], repo=lambda: info)


@pytest.mark.parametrize(("github", "state", "says"), [
    (dict(rules=OWNER_RULE), "enforced", "cannot bypass or change it"),
    (dict(rules=OWNER_RULE, viewer="ADMIN"), "not enforced", "is an administrator"),
    (dict(rules=OWNER_RULE, bypass="always"), "not enforced", "can bypass ruleset 7"),
    (dict(classic=(200, {"required_pull_request_reviews": {"require_code_owner_reviews": True},
                         "enforce_admins": {"enabled": False}}), viewer="ADMIN"),
     "not enforced", "lets administrators bypass it"),
    (dict(classic=(200, {"required_pull_request_reviews": {"require_code_owner_reviews": True},
                         "enforce_admins": {"enabled": True}}), viewer="MAINTAIN"),
     "enforced", "cannot bypass or change it"),
    (dict(viewer="ADMIN"), "not enforced", "no rule on main requires code-owner review"),
    (dict(), "unknown", "readable by an administrator only"),
    (dict(classic=(403, None), visibility="PRIVATE"), "unknown", "needs GitHub Pro"),
    (dict(codeowners=None, rules=OWNER_RULE), "not enforced", "is not on main yet"),
    (dict(codeowners="* @team\n", rules=OWNER_RULE), "not enforced", "does not name @ana"),
    (dict(errors=[{"line": 2}], rules=OWNER_RULE), "not enforced", "1 error(s)"),
])
def test_doctor_says_enforced_not_enforced_with_the_reason_or_unknown(github, state, says):
    """Each answer okl doctor can give, and the reason it names (#329): never silent, and never
    'enforced' while the identity running it could change or bypass the rule."""
    got_state, why = protection.check(PATHS, FILE, "@ana", **_github(**github))

    assert (got_state, says in why) == (state, True), why


def test_doctor_says_unknown_when_gh_cannot_read_the_repo():
    """No gh, or no login: unknown, with what to do, never a silent pass."""
    state, why = protection.check(PATHS, FILE, "@ana", get=lambda p: (None, None), repo=lambda: None)

    assert state == "unknown" and "gh auth login" in why


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty git repo as cwd, its own home, and `okl(*args)` run in-process: (exit, output)."""
    import subprocess

    from okl.cli import main
    root = tmp_path / "r"; root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def okl(*args, capsys=None):
        code = main(list(args))
        return code, capsys.readouterr().out if capsys else ""
    return root, okl


def test_init_owner_writes_the_block_and_the_deny_rules_and_records_them(repo, capsys):
    """`okl init --owner` names the owner for the thesis, the --owned paths and CODEOWNERS itself,
    adds the Claude Code deny rules, and records both, so a plain re-run keeps them current."""
    import json

    from okl.cli.install import OWNER_DENY
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "ana", "--owned", "ADR/",
                    capsys=capsys)

    assert code == 0, out
    text = (root / ".github" / "CODEOWNERS").read_text()
    assert codeowners.owned(text) == {"docs/THESIS.md": ["@ana"], "ADR/": ["@ana"], ".github/CODEOWNERS": ["@ana"]}
    deny = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert set(OWNER_DENY) <= set(deny)
    cfg = json.loads((root / ".okl" / "config.json").read_text())
    assert (cfg["owner"], cfg["owned"]) == ("@ana", ["ADR/"])

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude", capsys=capsys)
    assert code == 0 and "owner-approved paths already current" in out, out
    assert (root / ".github" / "CODEOWNERS").read_text() == text


def test_init_owner_keeps_a_teams_file_and_uninstall_takes_out_only_okls_part(repo, capsys):
    """An existing CODEOWNERS keeps every line; uninstall restores it byte for byte and removes
    only okl's deny rules from settings."""
    import json
    root, okl = repo
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text(TEAM)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(rm -rf *)"]}}))

    from okl.cli.install import OWNER_DENY
    assert okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "@ana", capsys=capsys)[0] == 0
    written = (root / ".github" / "CODEOWNERS").read_text()
    assert written.startswith(TEAM.rstrip("\n")) and "docs/THESIS.md @ana" in written
    deny = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert deny == ["Bash(rm -rf *)", *OWNER_DENY]

    code, out = okl("init", "--uninstall", capsys=capsys)
    assert code == 0, out
    assert (root / ".github" / "CODEOWNERS").read_text() == TEAM
    settings = json.loads((root / ".claude" / "settings.json").read_text())
    assert settings.get("permissions") == {"deny": ["Bash(rm -rf *)"]}


def test_uninstall_removes_a_codeowners_file_that_held_only_okls_block(repo, capsys):
    """A CODEOWNERS okl created is removed whole, as the other files okl wrote are."""
    root, okl = repo
    assert okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owner", "ana", capsys=capsys)[0] == 0
    assert (root / ".github" / "CODEOWNERS").is_file()

    code, out = okl("init", "--uninstall", capsys=capsys)

    assert code == 0 and not (root / ".github" / "CODEOWNERS").exists(), out


def test_an_owner_codeowners_would_reject_stops_init_before_it_writes(repo, capsys):
    """A typo in --owner is said and nothing is written, not a CODEOWNERS GitHub reports errors in."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--no-seed", "--owner", "two words", capsys=capsys)

    assert code == 2 and "not an owner CODEOWNERS accepts" in out, out
    assert not (root / ".github").exists() and not (root / ".okl").exists()


def test_the_dry_run_lists_the_owner_files(repo, capsys):
    """--dry-run names CODEOWNERS and the settings deny rules, and writes neither."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--claude", "--owner", "ana", "--dry-run", capsys=capsys)

    assert code == 0 and ".github/CODEOWNERS" in out and "names @ana code owner" in out, out
    assert "deny rules for editing branch protection" in out
    assert not (root / ".github").exists()


def test_doctor_reports_the_owner_state_only_where_okl_wrote_a_block(repo, capsys, monkeypatch):
    """No block, no line and no API call; with one, doctor prints protection's answer."""
    root, okl = repo
    calls = []
    monkeypatch.setattr(protection, "check", lambda *a: calls.append(a) or ("not enforced", "no rule on main"))

    okl("doctor", capsys=capsys)
    assert calls == []

    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text(codeowners.merge("", "@ana", ["docs/THESIS.md"])[0])
    _, out = okl("doctor", capsys=capsys)
    assert "! owner-approved paths (docs/THESIS.md): not enforced. no rule on main" in out, out
    assert calls == [(["docs/THESIS.md"], ".github/CODEOWNERS", "@ana")]
