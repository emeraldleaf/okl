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


def check(paths: list[str], codeowners_path: str, owner: str,
          get: Get = _gh_get, repo: Callable[[], dict | None] = _gh_repo) -> tuple[str, str]:
    """(state, why) for the owner-approved `paths`, which `codeowners_path` names for `owner`."""
    info = repo()
    if not info:
        return UNKNOWN, "gh cannot read this repository (install gh and run `gh auth login`)"
    name, viewer = info["nameWithOwner"], info.get("viewerPermission")
    branch = (info.get("defaultBranchRef") or {}).get("name") or "main"

    # 1. GitHub reads CODEOWNERS from the base branch: the lines must be there, and valid.
    status, body = get(f"repos/{name}/contents/{codeowners_path}?ref={branch}")
    if status == 404:
        return NOT_ENFORCED, f"{codeowners_path} is not on {branch} yet: commit and merge it"
    if status == 200 and isinstance(body, dict):
        text = b64decode(body.get("content", "")).decode("utf-8", "replace")
        missing = [p for p in paths if not any(line.split()[:1] == [p] and owner in line.split()[1:]
                                               for line in text.splitlines())]
        if missing:
            return NOT_ENFORCED, f"{codeowners_path} on {branch} does not name {owner} for {', '.join(missing)} yet"
    status, body = get(f"repos/{name}/codeowners/errors?ref={branch}")
    if status == 200 and isinstance(body, dict) and body.get("errors"):
        return NOT_ENFORCED, f"GitHub reports {len(body['errors'])} error(s) in {codeowners_path} on {branch}"

    # 2. A rule that requires code-owner review: a ruleset (readable without admin) or classic
    #    branch protection (readable by an admin only).
    status, rules = get(f"repos/{name}/rules/branches/{branch}")
    owner_rules = [r for r in rules if r.get("type") == "pull_request"
                   and (r.get("parameters") or {}).get("require_code_owner_review")] \
        if status == 200 and isinstance(rules, list) else []
    for rule in owner_rules:
        rid = rule.get("ruleset_id")
        status, ruleset = get(f"repos/{name}/rulesets/{rid}?includes_parents=true")
        can = ruleset.get("current_user_can_bypass") if status == 200 and isinstance(ruleset, dict) else None
        if can in BYPASSES:
            return NOT_ENFORCED, f"this identity can bypass ruleset {rid} ({can})"
        if can is None:
            return UNKNOWN, f"cannot read whether this identity can bypass ruleset {rid}"
    status, classic = get(f"repos/{name}/branches/{branch}/protection")
    classic_owner = (status == 200 and isinstance(classic, dict)
                     and (classic.get("required_pull_request_reviews") or {}).get("require_code_owner_reviews"))
    if classic_owner and not (classic.get("enforce_admins") or {}).get("enabled"):
        return NOT_ENFORCED, (f"branch protection on {branch} requires code-owner review but lets "
                              "administrators bypass it (turn on 'Do not allow bypassing the above settings')")
    if not owner_rules and not classic_owner:
        if viewer == "ADMIN" or status == 200:
            return NOT_ENFORCED, f"no rule on {branch} requires code-owner review"
        if status == 403 and info.get("visibility") == "PRIVATE":
            return UNKNOWN, ("branch protection is not readable here; a private repository needs "
                             "GitHub Pro or a paid organization plan for code-owner review")
        return UNKNOWN, (f"no ruleset on {branch} requires code-owner review, and classic branch "
                         "protection is readable by an administrator only")

    # 3. The identity running this must not be able to change the rule.
    if viewer == "ADMIN":
        return NOT_ENFORCED, ("this identity is an administrator, so it can change or remove the rule: "
                              "run the agent as an identity without admin (docs/AGENT-IDENTITY.md)")
    return ENFORCED, f"code-owner review is required on {branch}, and this identity cannot bypass or change it"
