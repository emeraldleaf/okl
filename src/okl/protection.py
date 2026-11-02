"""Is the owner's approval on okl's owner-approved paths enforced? `okl doctor`'s answer (#329).

`okl init --owner` names a person as code owner of the thesis and of CODEOWNERS itself
(okl.codeowners). That holds only if GitHub requires code-owner review on the default branch,
the rule binds administrators, and the identity the agent runs as cannot change the rule. This
asks GitHub, through `gh`, and answers "enforced", "not enforced" with the reason, or "unknown"
with what could not be read. It never stays silent and changes nothing.

Run it as the agent's identity (`GH_TOKEN=<its token> okl doctor`): run as an administrator it
answers "not enforced", correctly, because that identity can change the rule. This module
imports nothing from okl.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from base64 import b64decode
from collections.abc import Callable

ENFORCED, NOT_ENFORCED, UNKNOWN = "enforced", "not enforced", "unknown"
# GitHub's answer when the identity can get past a ruleset (REST: current_user_can_bypass).
BYPASSES = ("always", "pull_requests_only", "exempt")

# One `gh api` call: (HTTP status or None when gh could not run, parsed JSON body or None).
Get = Callable[[str], tuple[int | None, object]]


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


def _codeowners_problem(get: Get, name: str, branch: str, *, path: str, paths: list[str],
                        owner: str) -> str | None:
    """Why the base branch's CODEOWNERS does not yet give `owner` the paths, or None. GitHub reads
    CODEOWNERS from the base branch, so a local edit counts for nothing until it is merged."""
    status, body = get(f"repos/{name}/contents/{path}?ref={branch}")
    if status == 404:
        return f"{path} is not on {branch} yet: commit and merge it"
    if status == 200 and isinstance(body, dict):
        text = b64decode(body.get("content", "")).decode("utf-8", "replace")
        missing = [p for p in paths if not any(line.split()[:1] == [p] and owner in line.split()[1:]
                                               for line in text.splitlines())]
        if missing:
            return f"{path} on {branch} does not name {owner} for {', '.join(missing)} yet"
    status, body = get(f"repos/{name}/codeowners/errors?ref={branch}")
    if status == 200 and isinstance(body, dict) and body.get("errors"):
        return f"GitHub reports {len(body['errors'])} error(s) in {path} on {branch}"
    return None


def _owner_rules(get: Get, name: str, branch: str) -> list[dict]:
    """The ruleset rules on `branch` that require code-owner review (readable without admin)."""
    status, rules = get(f"repos/{name}/rules/branches/{branch}")
    if status != 200 or not isinstance(rules, list):
        return []
    return [r for r in rules if r.get("type") == "pull_request"
            and (r.get("parameters") or {}).get("require_code_owner_review")]


def _ruleset_gap(get: Get, name: str, rules: list[dict]) -> tuple[str, str] | None:
    """A ruleset this identity can bypass, or cannot tell whether it can; None when it cannot."""
    for rule in rules:
        rid = rule.get("ruleset_id")
        status, ruleset = get(f"repos/{name}/rulesets/{rid}?includes_parents=true")
        can = ruleset.get("current_user_can_bypass") if status == 200 and isinstance(ruleset, dict) else None
        if can is None:
            return UNKNOWN, f"cannot read whether this identity can bypass ruleset {rid}"
        if can in BYPASSES:
            return NOT_ENFORCED, f"this identity can bypass ruleset {rid} ({can})"
    return None


def _classic(get: Get, name: str, branch: str) -> tuple[int | None, bool, bool]:
    """Classic branch protection: (status, requires code-owner review, binds administrators).
    Only an administrator can read it; anyone else gets a 404 whether or not it exists."""
    status, body = get(f"repos/{name}/branches/{branch}/protection")
    if status != 200 or not isinstance(body, dict):
        return status, False, False
    return (status, bool((body.get("required_pull_request_reviews") or {}).get("require_code_owner_reviews")),
            bool((body.get("enforce_admins") or {}).get("enabled")))


def _no_rule(info: dict, branch: str, status: int | None) -> tuple[str, str]:
    """No rule found: not enforced when this identity could have seen one, else unknown."""
    if info.get("viewerPermission") == "ADMIN" or status == 200:
        return NOT_ENFORCED, f"no rule on {branch} requires code-owner review"
    if status == 403 and info.get("visibility") == "PRIVATE":
        return UNKNOWN, ("branch protection is not readable here; a private repository needs GitHub Pro "
                         "or a paid organization plan for code-owner review")
    return UNKNOWN, (f"no ruleset on {branch} requires code-owner review, and classic branch protection "
                     "is readable by an administrator only")


def check(paths: list[str], codeowners_path: str, owner: str,
          get: Get = _gh_get, repo: Callable[[], dict | None] = _gh_repo) -> tuple[str, str]:
    """(state, why) for the owner-approved `paths`, which `codeowners_path` names for `owner`."""
    info = repo()
    if not info:
        return UNKNOWN, "gh cannot read this repository (install gh and run `gh auth login`)"
    name, branch = info["nameWithOwner"], (info.get("defaultBranchRef") or {}).get("name") or "main"
    if problem := _codeowners_problem(get, name, branch, path=codeowners_path, paths=paths, owner=owner):
        return NOT_ENFORCED, problem
    rules = _owner_rules(get, name, branch)
    status, classic_owner, admins_bound = _classic(get, name, branch)
    gap = _ruleset_gap(get, name, rules) or (
        (NOT_ENFORCED, f"branch protection on {branch} requires code-owner review but lets administrators "
                       "bypass it (turn on 'Do not allow bypassing the above settings')")
        if classic_owner and not admins_bound else None)
    if gap or not (rules or classic_owner):
        return gap or _no_rule(info, branch, status)
    if info.get("viewerPermission") == "ADMIN":
        return NOT_ENFORCED, ("this identity is an administrator, so it can change or remove the rule: "
                              "run the agent as an identity without admin (docs/AGENT-IDENTITY.md)")
    return ENFORCED, f"code-owner review is required on {branch}, and this identity cannot bypass or change it"
