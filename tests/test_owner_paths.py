"""Owner-approved paths (#329): the CODEOWNERS block `okl init --owner` writes, and what
`okl doctor` says about whether GitHub enforces it.

A thesis an agent keeps updating is safe only if a person approves each change, and only the
forge can make that hold: these tests cover okl's half, writing the code-owner lines without
clobbering a team's file, and saying "enforced" only on what it read and recognised.
"""
import json
import subprocess
from base64 import b64encode
from pathlib import Path

import pytest

from okl import codeowners, protection
from okl.cli.install import OWNER_DENY

TEAM = "# the platform team owns everything by default\n* @acme/platform\n/docs/ @acme/docs\n"


# --- CODEOWNERS: okl's block, merged and removed ------------------------------------------------

def test_a_new_file_names_the_owner_for_each_path_and_itself():
    """With no CODEOWNERS, okl writes only its block."""
    text, notes = codeowners.merge("", "@ana", ["docs/THESIS.md", ".github/CODEOWNERS"])

    assert notes == []
    assert codeowners.owned(text) == {"docs/THESIS.md": ["@ana"], ".github/CODEOWNERS": ["@ana"]}
    assert text.startswith(codeowners.BEGIN) and text.rstrip().endswith(codeowners.END)


def test_the_owner_approves_every_place_github_reads_codeowners_from():
    """GitHub reads the first of .github/, the root and docs/: owning only the one in use would
    let a new CODEOWNERS earlier in that order take over unowned (the review of #329)."""
    assert codeowners.owner_paths(["ADR/"]) == ["docs/THESIS.md", ".github/CODEOWNERS", "CODEOWNERS",
                                                "docs/CODEOWNERS", "ADR/"]


def test_an_existing_file_keeps_every_line_and_okl_goes_last():
    """CODEOWNERS applies the last matching line, so okl's block goes after the team's rules:
    `* @acme/platform` above it does not take the thesis back."""
    text, _ = codeowners.merge(TEAM, "@ana", ["docs/THESIS.md"])

    assert text.startswith(TEAM)
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


@pytest.mark.parametrize("original", [
    TEAM,                                                   # LF, final newline
    TEAM.replace("\n", "\r\n"),                             # CRLF: the block is written in CRLF too
    "\n\n" + TEAM + "\n\n",                                 # blank lines at either end
    "",                                                     # a file okl creates
])
def test_remove_restores_the_file_byte_for_byte(original):
    """Uninstall leaves every byte of the team's file as it was (the review of #329 found the
    first version turned CRLF into LF and dropped blank edges)."""
    merged, _ = codeowners.merge(original, "@ana", ["docs/THESIS.md"])

    assert codeowners.remove(merged) == original
    if "\r\n" in original:
        assert merged.count("\r\n") == merged.count("\n")


def test_a_file_without_a_final_newline_gets_one_and_keeps_every_other_byte():
    """okl's block needs its own line, so the team's last line is ended; nothing else changes."""
    merged, _ = codeowners.merge(TEAM.rstrip("\n"), "@ana", ["docs/THESIS.md"])

    assert codeowners.remove(merged) == TEAM


@pytest.mark.parametrize("broken", [
    f"{TEAM}{codeowners.BEGIN}\ndocs/THESIS.md @ana\nsrc/ @acme/core\n",          # END deleted by hand
    f"{codeowners.END}\n{TEAM}{codeowners.BEGIN}\n",                            # out of order
    f"{codeowners.BEGIN}\n{codeowners.END}\n{codeowners.BEGIN}\n{codeowners.END}\n",  # repeated
])
def test_markers_that_do_not_pair_are_refused_never_guessed(broken):
    """With END deleted, everything after BEGIN looked like okl's and was cut (the review of #329):
    okl now refuses, and the file is the team's to fix."""
    with pytest.raises(codeowners.MalformedBlockError):
        codeowners.merge(broken, "@ana", ["docs/THESIS.md"])
    with pytest.raises(codeowners.MalformedBlockError):
        codeowners.remove(broken)


@pytest.mark.parametrize(("given", "owner"), [
    ("ana", "@ana"), ("@ana", "@ana"), ("@acme/platform-team", "@acme/platform-team"), ("ana_acme", "@ana_acme"),
    ("ana@example.com", "ana@example.com"), ("@-bad", None), ("two words", None), ("", None),
])
def test_an_owner_is_one_codeowners_accepts(given, owner):
    """A user (an Enterprise Managed User's has an underscore), a team or an email."""
    assert codeowners.normalise_owner(given) == owner


@pytest.mark.parametrize(("path", "ok"), [
    ("ADR/", True), ("docs/rules.md", True), ("*.md", True), ("", False), ("my docs/x.md", False),
    ("a\n* @evil", False), ("x # c", False), ("!keep", False),
])
def test_an_owned_path_is_one_pattern_and_nothing_more(path, ok):
    """An --owned value becomes one CODEOWNERS pattern: a space, a comment or a newline would
    write a broken or a second line (the review of #329 injected `* @evil` that way)."""
    assert codeowners.valid_path(path) is ok


def test_the_file_is_the_one_github_reads(tmp_path):
    """okl writes into the CODEOWNERS GitHub reads, and creates .github/CODEOWNERS when there is none."""
    assert codeowners.location(tmp_path) == Path(".github/CODEOWNERS")
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "CODEOWNERS").write_text(TEAM)
    assert codeowners.location(tmp_path) == Path("docs/CODEOWNERS")
    (tmp_path / "CODEOWNERS").write_text(TEAM)
    assert codeowners.location(tmp_path) == Path("CODEOWNERS")


# --- okl doctor's answer, from GitHub API answers in the shapes its REST docs give -----------
# (rules/branches, rulesets/{id} current_user_can_bypass, classic branches/{b}/protection,
# contents, codeowners/errors). Hand-written from the docs, so no test touches the network.

REPO = {"nameWithOwner": "acme/app", "defaultBranchRef": {"name": "main"}, "viewerPermission": "WRITE",
        "visibility": "PUBLIC", "viewerLogin": "agent-bot"}
PATHS = ["docs/THESIS.md", ".github/CODEOWNERS"]
BLOCK = codeowners.merge("", "@ana", PATHS)[0]
RULE = {"type": "pull_request", "ruleset_id": 7,
        "parameters": {"require_code_owner_review": True, "dismiss_stale_reviews_on_push": True,
                       "required_approving_review_count": 1}}
STALE_RULE = {**RULE, "parameters": {"require_code_owner_review": True, "require_last_push_approval": True,
                                     "required_approving_review_count": 1}}
CLASSIC = {"required_pull_request_reviews": {"require_code_owner_reviews": True, "dismiss_stale_reviews": True,
                                             "required_approving_review_count": 1},
           "enforce_admins": {"enabled": True}}


def _with(**changes):
    """CLASSIC with some of its review settings changed."""
    return {**CLASSIC, "required_pull_request_reviews": {**CLASSIC["required_pull_request_reviews"], **changes}}


def _github(*, files=None, errors=(200, {"errors": []}), rules=(200, []), bypass=(200, "never"),
            classic=(404, None), info=None, **who):
    """A GitHub: each API path okl doctor reads, and its (status, body)."""
    files = {".github/CODEOWNERS": BLOCK} if files is None else files
    answers = {
        "repos/acme/app/codeowners/errors?ref=main": errors,
        "repos/acme/app/rules/branches/main?per_page=100": rules,
        "repos/acme/app/rulesets/7?includes_parents=true": (bypass[0], {"id": 7, "current_user_can_bypass": bypass[1]}),
        "repos/acme/app/branches/main/protection": classic,
    }
    for location in codeowners.LOCATIONS:
        found = files.get(location.as_posix())
        answers[f"repos/acme/app/contents/{location.as_posix()}?ref=main"] = (
            found if isinstance(found, tuple)
            else (200, {"content": b64encode(found.encode()).decode()}) if found is not None else (404, None))
    repo = {**REPO, **who} if info is None else info
    return dict(get=lambda path: answers[path], repo=lambda: repo)


TEAM_THEN_BLOCK = TEAM + "\n" + BLOCK
LEFT_TO_TEAM = codeowners.merge("", "@ana", [".github/CODEOWNERS"])[0]     # okl's block lacks the thesis


@pytest.mark.parametrize(("github", "state", "says"), [
    # enforced: every condition read and recognised
    (dict(rules=(200, [RULE])), "enforced", "cannot bypass or change the rule"),
    (dict(classic=(200, CLASSIC), viewerPermission="MAINTAIN"), "enforced", "cannot bypass or change the rule"),
    (dict(files={"docs/CODEOWNERS": BLOCK}, rules=(200, [RULE])), "enforced", "cannot bypass"),
    (dict(files={".github/CODEOWNERS": BLOCK.replace("@ana", "@ANA")}, rules=(200, [RULE])), "enforced", "cannot"),
    (dict(files={".github/CODEOWNERS": TEAM_THEN_BLOCK}, rules=(200, [RULE])), "enforced", "cannot bypass"),
    (dict(files={".github/CODEOWNERS": "docs/THESIS.md @ana\n" + LEFT_TO_TEAM}, rules=(200, [RULE])),
     "enforced", "cannot bypass"),
    (dict(rules=(200, ["not a rule", RULE])), "enforced", "cannot bypass"),
    # not enforced: read, and missing
    (dict(rules=(200, [RULE]), viewerPermission="ADMIN"), "not enforced", "is an administrator"),
    (dict(rules=(200, [RULE]), viewerLogin="Ana"), "not enforced", "this identity is @ana, the owner"),
    (dict(rules=(200, [STALE_RULE]), classic=(200, {})), "not enforced", "approval of the most recent push alone"),
    (dict(rules=(200, [RULE]), bypass=(200, "always"), classic=(200, {})), "not enforced", "can bypass ruleset 7 (always)"),
    (dict(rules=(200, [RULE]), bypass=(200, "pull_requests_only"), classic=(200, {})), "not enforced", "can bypass"),
    (dict(rules=(200, [RULE]), bypass=(200, "exempt"), classic=(200, {})), "not enforced", "can bypass ruleset 7"),
    (dict(classic=(200, {**CLASSIC, "enforce_admins": {"enabled": False}}), viewerPermission="ADMIN"),
     "not enforced", "lets administrators bypass it"),
    (dict(classic=(200, _with(dismiss_stale_reviews=False, require_last_push_approval=True)),
          viewerPermission="MAINTAIN"), "not enforced", "keeps an approval when new commits are pushed"),
    (dict(classic=(200, _with(bypass_pull_request_allowances={"apps": [{"slug": "bot"}]})),
          viewerPermission="MAINTAIN"), "not enforced", "lets listed users, teams or apps bypass"),
    (dict(viewerPermission="ADMIN"), "not enforced", "no rule on main requires code-owner review"),
    (dict(classic=(200, {"required_status_checks": {}}), viewerPermission="MAINTAIN"), "not enforced", "no rule on"),
    (dict(files={}), "not enforced", "no CODEOWNERS on main yet"),
    (dict(files={".github/CODEOWNERS": BLOCK + "docs @eve\n"}, rules=(200, [RULE])), "not enforced",
     "1 rule(s) after okl's block"),
    (dict(files={".github/CODEOWNERS": "docs/THESIS.md @acme/leads\n" + LEFT_TO_TEAM}, rules=(200, [RULE])),
     "not enforced", "docs/THESIS.md is owned by @acme/leads, not @ana alone"),
    (dict(files={".github/CODEOWNERS": "docs/THESIS.md @ana @bob\n" + LEFT_TO_TEAM}, rules=(200, [RULE])),
     "not enforced", "owned by @ana @bob, not @ana alone"),
    (dict(files={".github/CODEOWNERS": BLOCK.replace("docs/THESIS.md @ana", "docs/THESIS.md @ana @bob")},
          rules=(200, [RULE])), "not enforced", "owned by @ana @bob"),
    (dict(files={".github/CODEOWNERS": "docs/THESIS.md # @ana\n" + LEFT_TO_TEAM}, rules=(200, [RULE])),
     "not enforced", "docs/THESIS.md is owned by no one"),
    (dict(files={".github/CODEOWNERS": "THESIS.md @eve\n" + LEFT_TO_TEAM}, rules=(200, [RULE])),
     "not enforced", "owned by @eve"),
    (dict(files={".github/CODEOWNERS": "/docs @eve\n" + LEFT_TO_TEAM}, rules=(200, [RULE])),
     "not enforced", "owned by @eve"),
    (dict(files={".github/CODEOWNERS": f"{TEAM}{codeowners.BEGIN}\ndocs/THESIS.md @ana\n"}, rules=(200, [RULE])),
     "not enforced", "unmatched or repeated"),
    (dict(errors=(200, {"errors": [{"line": 2}]}), rules=(200, [RULE])), "not enforced", "1 error(s)"),
    # unknown: something not read, or not recognised
    (dict(), "unknown", "branch protection could not be read as this identity"),
    (dict(rules=(200, [RULE]), bypass=(200, "always")), "unknown", "can bypass ruleset 7 (always); branch protection"),
    (dict(classic=(403, None), visibility="PRIVATE"), "unknown", "needs GitHub Pro"),
    (dict(rules=(200, [RULE]), viewerPermission=None), "unknown", "no role okl knows"),
    (dict(rules=(200, [RULE]), bypass=(200, "sometimes")), "unknown", "cannot tell whether this identity can bypass"),
    (dict(rules=(200, [RULE]), bypass=(404, None)), "unknown", "cannot tell whether this identity can bypass"),
    (dict(rules=(500, None), viewerPermission="ADMIN"), "unknown", "the rulesets on main could not be read"),
    (dict(rules=(200, [{**RULE, "parameters": {**RULE["parameters"], "required_approving_review_count": 0}}])),
     "unknown", "requires 0 approvals"),
    (dict(files={".github/CODEOWNERS": (403, {"message": "Resource not accessible by integration"})},
          rules=(200, [RULE])), "unknown", "cannot read .github/CODEOWNERS"),
    (dict(files={".github/CODEOWNERS": (None, None)}, rules=(200, [RULE])), "unknown", "cannot read .github/CODEOWNERS"),
    (dict(files={".github/CODEOWNERS": (200, {"content": None})}, rules=(200, [RULE])), "unknown", "cannot read"),
    # only a 200 is the file: a body that carries content under any other status is not read as it
    (dict(files={".github/CODEOWNERS": (500, {"content": b64encode(BLOCK.encode()).decode()})},
          rules=(200, [RULE])), "unknown", "cannot read .github/CODEOWNERS"),
    (dict(errors=(None, None), rules=(200, [RULE])), "unknown", "cannot read GitHub's check"),
    (dict(files={".github/CODEOWNERS": "*.md @eve\n" + LEFT_TO_TEAM}, rules=(200, [RULE])), "unknown",
     "a rule okl cannot evaluate may own docs/THESIS.md"),
    (dict(info={"defaultBranchRef": {"name": "main"}}), "unknown", "gh cannot read this repository"),
])
def test_doctor_says_enforced_only_on_what_it_read_and_recognised(github, state, says):
    """Each answer okl doctor can give and the reason it names (#329): 'enforced' only when every
    condition was read and recognised; an unread or unknown value is 'unknown', never a pass (two
    reviews of #329 found fifteen ways earlier versions said 'enforced' when it was not)."""
    verdict = protection.check(PATHS, "@ana", **_github(**github))

    assert (verdict.state, says in verdict.why) == (state, True), verdict.why


@pytest.mark.parametrize(("pattern", "path", "hit"), [
    ("docs/THESIS.md", "docs/THESIS.md", "yes"), ("/docs/THESIS.md", "docs/THESIS.md", "yes"),
    ("THESIS.md", "docs/THESIS.md", "yes"), ("docs", "docs/THESIS.md", "yes"), ("/docs", "docs/THESIS.md", "yes"),
    ("docs/", "docs/THESIS.md", "yes"), (".github", ".github/CODEOWNERS", "yes"), ("*", "a/b", "yes"),
    ("/apps/github", "apps/github/x.md", "yes"),                       # GitHub's own CODEOWNERS example
    ("/docs/", "a/docs/x.md", "no"), ("src/", "docs/THESIS.md", "no"), ("README.md", "docs/THESIS.md", "no"),
    ("docs/THESIS.md/", "docs/THESIS.md", "no"),
    ("*.md", "docs/THESIS.md", "maybe"), ("*/", "docs/THESIS.md", "maybe"), ("?ocs/", "docs/THESIS.md", "maybe"),
    ("**/THESIS.md", "docs/THESIS.md", "maybe"), ("docs/*.txt", "docs/THESIS.md", "no"),
])
def test_a_pattern_is_ruled_out_only_when_it_cannot_match(pattern, path, hit):
    """CODEOWNERS follows gitignore rules: a name with no slash matches at any depth, a leading or
    inner slash anchors it, a directory covers everything under it. "no" only when certain."""
    assert protection._matches(pattern, path) == hit


FULL_BLOCK = codeowners.merge("", "@ana", codeowners.owner_paths([]))[0]     # what init writes


@pytest.mark.parametrize(("files", "state", "says"), [
    ({".github/CODEOWNERS": FULL_BLOCK}, "enforced", "cannot bypass"),
    ({".github/CODEOWNERS": FULL_BLOCK.replace(".github/CODEOWNERS @ana", ".github/CODEOWNERS @bob")},
     "not enforced", "names more than one owner"),
    ({".github/CODEOWNERS": TEAM}, "not enforced", "okl's block in CODEOWNERS on main is not there"),
])
def test_with_no_owner_recorded_doctor_reads_it_from_okls_block_on_the_default_branch(files, state, says):
    """.okl/ is not committed, so the agent's clone and CI have no recorded owner: doctor takes the
    owner and paths from the merged block, not from the working tree (the second review of #329)."""
    github = _github(files=files, rules=(200, [RULE]))
    verdict = protection.check(None, None, **github)

    assert (verdict.state, says in verdict.why) == (state, True), verdict.why


def test_doctor_names_each_paths_owner_on_the_default_branch():
    """One line per path, read from the merged CODEOWNERS, not the working tree's."""
    verdict = protection.check(PATHS, "@ana", **_github(rules=(200, [RULE])))

    assert verdict.owners == {"docs/THESIS.md": ["@ana"], ".github/CODEOWNERS": ["@ana"]}


def test_doctor_says_unknown_when_gh_cannot_read_the_repo():
    """No gh, or no login: unknown, with what to do, never a silent pass."""
    verdict = protection.check(PATHS, "@ana", get=lambda p: (None, None), repo=lambda: None)

    assert verdict.state == "unknown" and "gh auth login" in verdict.why


# --- okl init --owner, its dry run and uninstall, and okl doctor, end to end -----------------

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """An empty git repo as cwd, its own home, and `okl(*args)` run in-process: (exit, output)."""
    from okl.cli import main
    root = tmp_path / "r"; root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))

    def okl(*args, capsys):
        code = main(list(args))
        return code, capsys.readouterr().out
    return root, okl


def test_init_owner_writes_the_block_and_the_deny_rules_and_records_them(repo, capsys):
    """`okl init --owner` names the owner for the thesis, every CODEOWNERS location and the --owned
    paths, adds the Claude Code deny rules, and records both, so a plain re-run keeps them current."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "ana", "--owned", "ADR/",
                    capsys=capsys)

    assert code == 0, out
    text = (root / ".github" / "CODEOWNERS").read_text()
    assert codeowners.owned(text) == {p: ["@ana"] for p in codeowners.owner_paths(["ADR/"])}
    deny = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert set(OWNER_DENY) <= set(deny)
    cfg = json.loads((root / ".okl" / "config.json").read_text())
    assert (cfg["owner"], cfg["owned"]) == ("@ana", ["ADR/"])

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude", capsys=capsys)
    assert code == 0 and "owner-approved paths already current" in out, out
    assert (root / ".github" / "CODEOWNERS").read_text() == text


def test_init_owner_keeps_a_teams_file_and_uninstall_takes_out_only_okls_part(repo, capsys):
    """An existing CODEOWNERS keeps every byte (CRLF included); uninstall restores it, and removes
    only okl's deny rules from settings."""
    root, okl = repo
    team = TEAM.replace("\n", "\r\n").encode()
    (root / ".github").mkdir(); (root / ".github" / "CODEOWNERS").write_bytes(team)
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"deny": ["Bash(rm -rf *)"]}}))

    assert okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "@ana", capsys=capsys)[0] == 0
    written = (root / ".github" / "CODEOWNERS").read_bytes()
    assert written.startswith(team) and b"docs/THESIS.md @ana\r\n" in written
    deny = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert deny == ["Bash(rm -rf *)", *OWNER_DENY]

    code, out = okl("init", "--uninstall", capsys=capsys)
    assert code == 0, out
    assert (root / ".github" / "CODEOWNERS").read_bytes() == team
    assert json.loads((root / ".claude" / "settings.json").read_text()) == {"permissions": {"deny": ["Bash(rm -rf *)"]}}


def test_uninstall_removes_a_codeowners_file_that_held_only_okls_block(repo, capsys):
    """A CODEOWNERS okl created is removed whole, as the other files okl wrote are."""
    root, okl = repo
    assert okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owner", "ana", capsys=capsys)[0] == 0
    assert (root / ".github" / "CODEOWNERS").is_file()
    assert not (root / ".claude").exists()                  # --no-claude: no deny rules either

    code, out = okl("init", "--uninstall", capsys=capsys)

    assert code == 0 and not (root / ".github" / "CODEOWNERS").exists(), out


def test_markers_that_do_not_pair_keep_the_file_in_init_and_uninstall(repo, capsys):
    """A hand-broken block: init and uninstall both keep the file, named, and cut nothing."""
    root, okl = repo
    broken = f"{TEAM}{codeowners.BEGIN}\ndocs/THESIS.md @ana\nsrc/ @acme/core\n"
    (root / ".github").mkdir(); (root / ".github" / "CODEOWNERS").write_text(broken)

    code, out = okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owner", "ana", capsys=capsys)
    assert code == 0 and "! kept .github/CODEOWNERS" in out, out
    code, out = okl("init", "--uninstall", capsys=capsys)
    assert "unmatched or repeated" in out, out
    assert (root / ".github" / "CODEOWNERS").read_text() == broken


@pytest.mark.parametrize("args", [("--owner", "two words"), ("--owner", "ana", "--owned", "a\n* @evil"),
                                  ("--owner", "ana", "--owned", "my docs/x.md"), ("--owner", "ana", "--owned", "")])
@pytest.mark.parametrize("dry", [False, True])
def test_a_bad_owner_or_owned_path_stops_init_before_it_writes(repo, capsys, args, dry):
    """A typo in --owner or --owned is said and nothing is written, in the run and the dry run."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--no-seed", *args, *(["--dry-run"] if dry else []), capsys=capsys)

    assert code == 2 and "! --own" in out, out
    assert not (root / ".github").exists() and not (root / ".okl").exists()


def test_the_dry_run_lists_the_owner_files(repo, capsys):
    """--dry-run names CODEOWNERS, the paths, and the settings deny rules, and writes neither."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--claude", "--owner", "ana", "--dry-run", capsys=capsys)

    assert code == 0 and ".github/CODEOWNERS" in out and "names @ana code owner of docs/THESIS.md" in out, out
    assert "deny rules for editing branch protection" in out
    assert not (root / ".github").exists()


@pytest.mark.parametrize("target", [".github/CODEOWNERS", ".claude/settings.json"])
def test_a_symlinked_owner_file_is_refused_and_its_target_left_alone(repo, capsys, tmp_path, target):
    """okl writes only real files inside the repo (CWE-59): a CODEOWNERS or settings.json that
    links outside it is refused, and the file it points at keeps every byte."""
    root, okl = repo
    outside = tmp_path / "outside"; outside.write_text("{}\n")
    link = root / target; link.parent.mkdir(parents=True, exist_ok=True); link.symlink_to(outside)

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "ana", capsys=capsys)

    assert code == 0 and f"! refused {target}" in out, out
    assert outside.read_text() == "{}\n"
    code, out = okl("init", "--uninstall", capsys=capsys)
    assert code == 0 and outside.read_text() == "{}\n", out
    if target.endswith("CODEOWNERS"):
        assert "a symlink" in out, out


@pytest.mark.parametrize(("settings", "kept"), [({"permissions": None}, False),
                                                ({"permissions": {"deny": "Bash(rm *)"}}, True)])
def test_the_deny_merge_survives_settings_of_another_shape(repo, capsys, settings, kept):
    """`permissions: null` is filled in; a `deny` that is not a list is named and left alone,
    never a traceback after CODEOWNERS is already written (the review of #329)."""
    root, okl = repo
    (root / ".claude").mkdir(); (root / ".claude" / "settings.json").write_text(json.dumps(settings))

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "ana", capsys=capsys)

    assert code == 0, out
    saved = json.loads((root / ".claude" / "settings.json").read_text())
    if kept:
        assert saved["permissions"] == settings["permissions"] and "not in the shape" in out
    else:
        assert saved["permissions"]["deny"] == list(OWNER_DENY)


def test_doctor_reports_from_the_recorded_owner_or_a_committed_block(repo, capsys, monkeypatch):
    """No owner recorded and no committed block: no line, no API call, and a block only in the
    working tree changes nothing (audits read committed files). A committed block: doctor asks
    with no owner, so the default branch's block decides. A recorded owner: its paths, and each
    path's owner printed."""
    root, okl = repo
    calls = []
    verdict = protection.Verdict("not enforced", "no rule on main requires code-owner review",
                                 {"docs/THESIS.md": ["@ana"], "CODEOWNERS": [], "ADR/": None})
    monkeypatch.setattr(protection, "check", lambda *a: calls.append(a) or verdict)
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]

    okl("doctor", capsys=capsys)
    (root / ".github").mkdir()
    (root / ".github" / "CODEOWNERS").write_text(FULL_BLOCK)
    okl("doctor", capsys=capsys)
    assert calls == []

    subprocess.run([*git, "add", ".github/CODEOWNERS"], check=True)
    subprocess.run([*git, "commit", "-qm", "okl's block"], check=True)
    _, out = okl("doctor", capsys=capsys)
    assert calls == [(None, None)]
    assert "! owner-approved paths: not enforced. no rule on main" in out, out
    assert "    docs/THESIS.md: owned by @ana" in out and "    CODEOWNERS: no owner" in out
    assert "    ADR/: okl could not tell" in out

    okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owner", "ben", "--owned", "ADR/", capsys=capsys)
    _, out = okl("doctor", capsys=capsys)
    assert calls[-1] == (codeowners.owner_paths(["ADR/"]), "@ben")
    assert "owner-approved paths for @ben: not enforced" in out, out


def test_a_rerun_moves_okls_block_back_after_a_team_line_added_below_it():
    """A rule after okl's block would win over it: init takes the block out and puts it back at
    the end, keeping the team's line byte for byte (the second review of #329)."""
    once, _ = codeowners.merge(TEAM, "@ana", ["docs/THESIS.md"])
    later = once + "docs/ @acme/docs\n"

    moved, _ = codeowners.merge(later, "@ana", ["docs/THESIS.md"])

    assert moved.index("docs/ @acme/docs") < moved.index(codeowners.BEGIN)
    assert codeowners.rules(moved[codeowners.block_span(moved)[1]:]) == []
    assert codeowners.remove(moved) == TEAM + "docs/ @acme/docs\n"
    assert codeowners.merge(moved, "@ana", ["docs/THESIS.md"])[0] == moved


@pytest.mark.parametrize("owned", ["/", "//"])
def test_owned_the_root_alone_is_refused(repo, capsys, owned):
    """`--owned /` stripped to nothing and wrote a line GitHub reads as no pattern (CodeRabbit and
    the second review of #329): it is validated as it will be written."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--no-seed", "--owner", "ana", "--owned", owned, capsys=capsys)

    assert code == 2 and "not the root alone" in out, out
    assert not (root / ".github").exists()


def test_owned_without_an_owner_says_it_waits_for_one(repo, capsys):
    """--owned alone is recorded and does nothing yet: init says so rather than nothing."""
    root, okl = repo

    code, out = okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owned", "ADR/", capsys=capsys)

    assert code == 0 and "takes effect once --owner" in out, out
    assert not (root / ".github" / "CODEOWNERS").exists()


def test_uninstall_leaves_an_empty_deny_list_the_team_had(repo, capsys):
    """okl cannot tell whether an empty `deny` was there before init, so it leaves it."""
    root, okl = repo
    (root / ".claude").mkdir()
    (root / ".claude" / "settings.json").write_text(json.dumps({"permissions": {"deny": []}}))

    okl("init", "--repo", "r", "--no-seed", "--claude", "--owner", "ana", capsys=capsys)
    okl("init", "--uninstall", capsys=capsys)

    assert json.loads((root / ".claude" / "settings.json").read_text()) == {"permissions": {"deny": []}}


def test_uninstall_finds_okls_block_in_a_file_github_no_longer_reads(repo, capsys):
    """init wrote into the root CODEOWNERS; a .github/CODEOWNERS added since is the one GitHub
    reads, and uninstall still takes okl's block out of the root file."""
    root, okl = repo
    (root / "CODEOWNERS").write_text(TEAM)
    okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owner", "ana", capsys=capsys)
    (root / ".github").mkdir(); (root / ".github" / "CODEOWNERS").write_text("* @acme/platform\n")

    code, out = okl("init", "--uninstall", capsys=capsys)

    assert (root / "CODEOWNERS").read_text() == TEAM, out
    assert (root / ".github" / "CODEOWNERS").read_text() == "* @acme/platform\n"


def test_the_dry_run_says_a_linked_codeowners_would_be_refused(repo, capsys, tmp_path):
    """The dry run says what the run will do: a CODEOWNERS that is a link is refused, not written."""
    root, okl = repo
    outside = tmp_path / "outside"; outside.write_text(TEAM)
    (root / ".github").mkdir(); (root / ".github" / "CODEOWNERS").symlink_to(outside)

    code, out = okl("init", "--repo", "r", "--owner", "ana", "--dry-run", capsys=capsys)

    assert "(no owner-approved paths: .github/CODEOWNERS is a symlink" in out, out
    assert outside.read_text() == TEAM


def test_a_dangling_link_at_codeowners_is_refused_and_nothing_is_created(repo, capsys, tmp_path):
    """A link to a file that does not exist: following it would create a file outside the repo."""
    root, okl = repo
    missing = tmp_path / "not-there"
    (root / ".github").mkdir(); (root / ".github" / "CODEOWNERS").symlink_to(missing)

    code, out = okl("init", "--repo", "r", "--no-seed", "--no-claude", "--owner", "ana", capsys=capsys)

    assert "! refused .github/CODEOWNERS" in out, out
    assert not missing.exists()
