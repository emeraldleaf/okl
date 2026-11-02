"""Is the owner's approval on okl's owner-approved paths enforced? `okl doctor`'s answer (#329).

`okl init --owner` names a person as code owner of the thesis and of every CODEOWNERS location
(okl.codeowners). That holds only if, on the default branch, GitHub reads a CODEOWNERS that
gives each path to that person, a rule requires code-owner review, an approval does not survive
a later push, the rule binds the identity the agent runs as, and that identity cannot change the
rule. This asks GitHub through `gh` and answers "enforced" only when it has read and recognised
every one of those; anything it could not read or did not recognise is "unknown", with what it
was, and anything it read as missing is "not enforced", with the reason. It changes nothing.

Run it as the agent's identity (`GH_TOKEN=<its token> okl doctor`): as an administrator it says
"not enforced", correctly, because that identity can change the rule. This module imports
nothing from okl.
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
from base64 import b64decode
from collections.abc import Callable
from typing import NamedTuple

ENFORCED, NOT_ENFORCED, UNKNOWN = "enforced", "not enforced", "unknown"
# Where GitHub looks for CODEOWNERS, in its order (okl.codeowners.LOCATIONS, kept apart so this
# module imports nothing from okl).
CODEOWNERS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")
# Repository roles that cannot edit branch protection or rulesets. An allow-list: a role GitHub
# reports that is not here, or none at all (an App's token may report none), is not assumed
# safe. A custom role granted "edit repository rules" reports its base role, which this cannot see.
SAFE_ROLES = ("WRITE", "MAINTAIN", "TRIAGE", "READ")
# current_user_can_bypass (REST: rulesets): only "never" binds this identity.
BYPASS_VALUES = ("always", "pull_requests_only", "exempt", "never")

# One `gh api` GET: (HTTP status or None when gh could not run, parsed JSON body or None).
Get = Callable[[str], tuple[int | None, object]]


class Verdict(NamedTuple):
    """okl doctor's answer, its reason, and each path's owners on the default branch."""
    state: str
    why: str
    owners: dict[str, list[str] | None]     # None: a glob okl cannot evaluate may own it


def _gh_get(path: str) -> tuple[int | None, object]:
    """GET one GitHub API path through gh, with the status line kept (`-i`), so a 404 is read
    from the status and never from the wording of an error message."""
    if shutil.which("gh") is None:
        return None, None
    try:
        out = subprocess.run(["gh", "api", "-i", "-H", "Accept: application/vnd.github+json", path],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    head, _, body = out.replace("\r\n", "\n").partition("\n\n")
    try:
        status = int(head.split()[1])
    except (IndexError, ValueError):
        return None, None
    try:
        return status, json.loads(body) if body.strip() else None
    except ValueError:
        return status, None


def _gh_repo() -> dict | None:
    """The repo gh sees here: name, default branch, the viewer's permission and visibility."""
    if shutil.which("gh") is None:
        return None
    try:
        r = subprocess.run(["gh", "repo", "view", "--json",
                            "nameWithOwner,defaultBranchRef,viewerPermission,visibility"],
                           capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _matches(pattern: str, path: str) -> str:
    """Whether a CODEOWNERS pattern covers `path`: "yes", "maybe" (a glob okl does not evaluate
    the way GitHub does), or "no"."""
    bare = pattern.lstrip("/")
    if bare in (path, "*", "**") or (bare.endswith("/") and f"/{path}".find(f"/{bare}") >= 0):
        return "yes"
    name = path.rsplit("/", 1)[-1]
    if any(c in bare for c in "*?[") and (fnmatch.fnmatchcase(path, bare) or fnmatch.fnmatchcase(name, bare)
                                          or "**" in bare):
        return "maybe"
    return "no"


def _owner_of(text: str, path: str) -> list[str] | None:
    """The owners GitHub gives `path` from this CODEOWNERS: the last line that matches ([] when
    none does), or None when a later glob might match instead."""
    rules = [(w[0], w[1:]) for line in text.splitlines() if (w := line.split("#", 1)[0].split())]
    for pattern, owners in reversed(rules):
        hit = _matches(pattern, path)
        if hit == "yes":
            return owners
        if hit == "maybe":
            return None
    return []


def _codeowners(get: Get, name: str, branch: str, paths: list[str]) -> tuple[Verdict | None, dict]:
    """The default branch's CODEOWNERS, read in GitHub's order, and each path's owners in it."""
    for location in CODEOWNERS:
        status, body = get(f"repos/{name}/contents/{location}?ref={branch}")
        if status == 404:
            continue
        if status != 200 or not isinstance(body, dict):
            return Verdict(UNKNOWN, f"cannot read {location} on {branch}", {}), {}
        text = b64decode(body.get("content", "")).decode("utf-8", "replace")
        status, errors = get(f"repos/{name}/codeowners/errors?ref={branch}")
        if status != 200 or not isinstance(errors, dict):
            return Verdict(UNKNOWN, f"cannot read GitHub's check of {location} on {branch}", {}), {}
        if errors.get("errors"):
            return Verdict(NOT_ENFORCED, f"GitHub reports {len(errors['errors'])} error(s) in {location} "
                                         f"on {branch}", {}), {}
        return None, {p: _owner_of(text, p) for p in paths}
    return Verdict(NOT_ENFORCED, f"there is no CODEOWNERS on {branch} yet: commit and merge okl's", {}), {}


def _rulesets(get: Get, name: str, branch: str) -> tuple[bool, list[str], bool]:
    """Ruleset rules on `branch` that require code-owner review: (one binds this identity and
    dismisses stale approvals, the problems found, whether anything could not be read)."""
    status, rules = get(f"repos/{name}/rules/branches/{branch}?per_page=100")
    if status != 200 or not isinstance(rules, list):
        return False, [], True
    binds, problems, unread = False, [], False
    for rule in rules:
        params = rule.get("parameters") or {}
        if rule.get("type") != "pull_request" or not params.get("require_code_owner_review"):
            continue
        rid = rule.get("ruleset_id")
        status, ruleset = get(f"repos/{name}/rulesets/{rid}?includes_parents=true")
        can = ruleset.get("current_user_can_bypass") if status == 200 and isinstance(ruleset, dict) else None
        if can not in BYPASS_VALUES:
            unread = True
            problems.append(f"cannot tell whether this identity can bypass ruleset {rid}")
        elif can != "never":
            problems.append(f"this identity can bypass ruleset {rid} ({can})")
        elif not (params.get("dismiss_stale_reviews_on_push") or params.get("require_last_push_approval")):
            problems.append(f"ruleset {rid} keeps an approval through later pushes (turn on dismissing stale "
                            "approvals, or approval of the most recent push)")
        else:
            binds = True
    return binds, problems, unread


def _classic(get: Get, name: str, branch: str, viewer: str | None) -> tuple[bool, list[str], int | None]:
    """Classic protection on `branch`: (it requires code-owner review and binds everyone, its
    problems, the read's status: None when a non-admin's 404 leaves it unknown)."""
    status, body = get(f"repos/{name}/branches/{branch}/protection")
    if status != 200 or not isinstance(body, dict):
        return False, [], None if status == 404 and viewer != "ADMIN" else status
    reviews = body.get("required_pull_request_reviews") or {}
    if not reviews.get("require_code_owner_reviews"):
        return False, [], status
    allowances = reviews.get("bypass_pull_request_allowances") or {}
    problems = [msg for failed, msg in (
        (not (body.get("enforce_admins") or {}).get("enabled"),
         f"branch protection on {branch} lets administrators bypass it (turn on 'Do not allow bypassing "
         "the above settings')"),
        (not (reviews.get("dismiss_stale_reviews") or reviews.get("require_last_push_approval")),
         f"branch protection on {branch} keeps an approval through later pushes"),
        (any(allowances.get(k) for k in ("users", "teams", "apps")),
         f"branch protection on {branch} lets listed users, teams or apps bypass pull request review"),
    ) if failed]
    return not problems, problems, status


def _rule_verdict(get: Get, name: str, branch: str, info: dict) -> Verdict | None:
    """Not enforced or unknown, from the rules; None when one rule requires code-owner review,
    dismisses stale approvals and binds this identity."""
    ruleset_binds, problems, rules_unread = _rulesets(get, name, branch)
    classic_binds, classic_problems, classic_status = _classic(get, name, branch, info.get("viewerPermission"))
    if ruleset_binds or classic_binds:
        return None
    problems += classic_problems
    unread = rules_unread or classic_status not in (200, 404)
    if problems:
        if unread:
            return Verdict(UNKNOWN, f"{problems[0]}; branch protection could not be read as this identity, "
                                    "so another rule may still apply", {})
        return Verdict(NOT_ENFORCED, problems[0], {})
    if not unread:
        return Verdict(NOT_ENFORCED, f"no rule on {branch} requires code-owner review", {})
    plan = (" (a private repository needs GitHub Pro or a paid organization plan for this)"
            if classic_status == 403 and info.get("visibility") == "PRIVATE" else "")
    return Verdict(UNKNOWN, f"no ruleset on {branch} requires code-owner review, and branch protection could "
                            f"not be read as this identity{plan}", {})


def _ownership_verdict(owners: dict, owner: str, branch: str) -> Verdict | None:
    """Not enforced when the default branch gives a path to someone else (or no one), unknown
    when a glob okl cannot evaluate might; None when every path is the owner's."""
    others = {p: o for p, o in owners.items() if o is not None and owner.lower() not in map(str.lower, o)}
    if others:
        path, who = next(iter(others.items()))
        return Verdict(NOT_ENFORCED, f"on {branch}, {path} is owned by {' '.join(who) or 'no one'}, not {owner}",
                       owners)
    if any(o is None for o in owners.values()):
        return Verdict(UNKNOWN, "a glob in CODEOWNERS may own "
                       + ", ".join(p for p, o in owners.items() if o is None), owners)
    return None


def _identity_verdict(info: dict, branch: str, owners: dict) -> Verdict:
    """With a binding rule in place: enforced only for a role that cannot change it."""
    viewer = info.get("viewerPermission")
    if viewer == "ADMIN":
        return Verdict(NOT_ENFORCED, "the rule is in place, but this identity is an administrator, so it can "
                                     "change or remove it: run the agent as an identity without admin "
                                     "(docs/AGENT-IDENTITY.md)", owners)
    if viewer not in SAFE_ROLES:
        return Verdict(UNKNOWN, f"the rule is in place, but GitHub reports no role okl knows for this identity "
                                f"({viewer!r}); for an App, check it has no Administration write", owners)
    return Verdict(ENFORCED, f"code-owner review is required on {branch}, a new push dismisses an approval, "
                             "and this identity cannot bypass or change the rule", owners)


def check(paths: list[str], owner: str, get: Get = _gh_get,
          repo: Callable[[], dict | None] = _gh_repo) -> Verdict:
    """Whether GitHub enforces `owner`'s approval of `paths` against the identity running this."""
    info = repo()
    if not info:
        return Verdict(UNKNOWN, "gh cannot read this repository (install gh and run `gh auth login`)", {})
    name, branch = info["nameWithOwner"], (info.get("defaultBranchRef") or {}).get("name")
    if not branch:
        return Verdict(UNKNOWN, "this repository has no default branch yet", {})
    stop, owners = _codeowners(get, name, branch, paths)
    stop = stop or _ownership_verdict(owners, owner, branch)
    if stop:
        return stop
    if rule := _rule_verdict(get, name, branch, info):
        return rule._replace(owners=owners)
    return _identity_verdict(info, branch, owners)
