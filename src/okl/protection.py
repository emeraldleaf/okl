"""Is the owner's approval on okl's owner-approved paths enforced? `okl doctor`'s answer (#329).

`okl init --owner` names a person as code owner of the thesis and of every CODEOWNERS location
(okl.codeowners). That holds only if, on the default branch, GitHub reads a CODEOWNERS that
gives each path to that person alone, a rule requires code-owner review and dismisses an
approval when new commits are pushed, the rule binds the identity the agent runs as, and that
identity can neither change the rule nor approve as the owner. This asks GitHub through `gh`
and answers "enforced" only when it has read and recognised every one of those; anything it
could not read or did not recognise is "unknown", with what it was, and anything it read as
missing is "not enforced", with the reason. It changes nothing.

Ownership is read without evaluating the team's patterns where it can be: okl's block is the
last rule in the file (init moves it there), so its lines win for the paths they name, and a
rule after it is counted as able to override it. Only a path left to a team's own line is
matched against the team's patterns, and there a pattern okl cannot rule out is "unknown".

Run it as the agent's identity (`GH_TOKEN=<its token> okl doctor`): as an administrator it says
"not enforced", correctly, because that identity can change the rule. Imports only
okl.codeowners, which imports nothing from okl.
"""
from __future__ import annotations

import fnmatch
import json
import shutil
import subprocess
from base64 import b64decode
from collections.abc import Callable
from typing import NamedTuple

from . import codeowners

ENFORCED, NOT_ENFORCED, UNKNOWN = "enforced", "not enforced", "unknown"
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
    owners: dict[str, list[str] | None]     # None: okl could not tell who owns it


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
    """The repo gh sees here (name, default branch, the viewer's role, visibility) and the
    viewer's login, which an App's token does not have."""
    if shutil.which("gh") is None:
        return None
    try:
        r = subprocess.run(["gh", "repo", "view", "--json",
                            "nameWithOwner,defaultBranchRef,viewerPermission,visibility"],
                           capture_output=True, text=True, timeout=30)
        info = json.loads(r.stdout) if r.returncode == 0 else None
        if isinstance(info, dict):
            who = subprocess.run(["gh", "api", "user", "--jq", ".login"], capture_output=True, text=True,
                                 timeout=30)
            info["viewerLogin"] = who.stdout.strip() if who.returncode == 0 else None
        return info
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _matches(pattern: str, path: str) -> str:
    """Whether a CODEOWNERS pattern (gitignore rules) covers the file `path`: "yes", "no" only
    when that is certain, or "maybe" for a form okl does not evaluate as GitHub does.

    A pattern with a leading or inner slash is anchored to the root; otherwise it matches a file
    or directory of that name at any depth. A directory match covers everything under it."""
    if "**" in pattern or pattern.startswith(("!", "\\")):
        return "maybe"
    dir_only, core = pattern.endswith("/"), pattern.strip("/")
    if not core:
        return "maybe"
    if core == "*" and not pattern.startswith("/") and not dir_only:
        return "yes"
    parts = path.split("/")
    anchored = pattern.startswith("/") or "/" in core
    # What the pattern is compared with: the path and each directory above it, from the root
    # when anchored, else each name in it; a directory match covers the file below.
    candidates = ["/".join(parts[:i + 1]) for i in range(len(parts))] if anchored else parts
    glob = any(c in core for c in "*?[")
    for i, candidate in enumerate(candidates):
        if dir_only and i == len(candidates) - 1:
            continue                                  # a directory pattern never names the file
        # fnmatch's * also crosses '/', so it matches at least what gitignore does: a miss is a miss.
        if glob and fnmatch.fnmatchcase(candidate, core):
            return "maybe"
        if not glob and candidate == core:
            return "yes"
    return "no"


def _owner_of(rules: list[tuple[str, list[str]]], path: str) -> list[str] | None:
    """The owners GitHub gives the file `path`: the last rule that matches ([] when none does),
    or None when a rule okl cannot evaluate might be the last match."""
    for pattern, owners in reversed(rules):
        hit = _matches(pattern, path)
        if hit == "yes":
            return owners
        if hit == "maybe":
            return None
    return []


def _ownership(text: str, paths: list[str], owner: str, branch: str) -> Verdict | None:
    """Not enforced, or unknown, when the default branch's CODEOWNERS does not give every path
    to `owner` alone; None when it does."""
    try:
        span = codeowners.block_span(text)
    except codeowners.MalformedBlockError as e:
        return Verdict(NOT_ENFORCED, f"{e} on {branch}", {})
    if span is not None and (after := codeowners.rules(text[span[1]:])):
        return Verdict(NOT_ENFORCED, f"{len(after)} rule(s) after okl's block in CODEOWNERS on {branch} can "
                                     "override it: re-run `okl init`, which moves the block last", {})
    block = {p.lstrip("/"): o for p, o in codeowners.rules(text[span[0]:span[1]])} if span else {}
    every = codeowners.rules(text)
    owners: dict[str, list[str] | None] = {}
    for path in paths:
        if path in block:
            owners[path] = block[path]              # okl's line, last in the file: it wins
        elif not any(c in path for c in "*?[") and not path.endswith("/"):
            owners[path] = _owner_of(every, path)   # a file left to a team's line
        else:
            owners[path] = None                     # a pattern okl did not write: not evaluated
    alone = [owner.lower()]
    wrong = {p: o for p, o in owners.items() if o is not None and [x.lower() for x in o] != alone}
    if wrong:
        path, who = next(iter(wrong.items()))
        return Verdict(NOT_ENFORCED, f"on {branch}, {path} is owned by {' '.join(who) or 'no one'}"
                                     + ("" if not who else f", not {owner} alone"), owners)
    if unread := [p for p, o in owners.items() if o is None]:
        return Verdict(UNKNOWN, f"on {branch}, a rule okl cannot evaluate may own {', '.join(unread)}", owners)
    return None


def _codeowners_text(get: Get, name: str, branch: str) -> tuple[str | None, Verdict | None]:
    """The CODEOWNERS GitHub reads on `branch` (the first of its locations that exists)."""
    for location in codeowners.LOCATIONS:
        status, body = get(f"repos/{name}/contents/{location.as_posix()}?ref={branch}")
        if status == 404:
            continue
        content = body.get("content") if isinstance(body, dict) else None
        if status != 200 or not isinstance(content, str):
            return None, Verdict(UNKNOWN, f"cannot read {location.as_posix()} on {branch}", {})
        status, errors = get(f"repos/{name}/codeowners/errors?ref={branch}")
        if status != 200 or not isinstance(errors, dict) or not isinstance(errors.get("errors", []), list):
            return None, Verdict(UNKNOWN, f"cannot read GitHub's check of {location.as_posix()} on {branch}", {})
        if errors.get("errors"):
            return None, Verdict(NOT_ENFORCED, f"GitHub reports {len(errors['errors'])} error(s) in "
                                               f"{location.as_posix()} on {branch}", {})
        return b64decode(content).decode("utf-8", "replace"), None
    return None, Verdict(NOT_ENFORCED, f"there is no CODEOWNERS on {branch} yet: commit and merge okl's", {})


def _review_problem(stale_dismissed: object, count: object, where: str) -> tuple[str, bool] | None:
    """(problem, it is a gap okl could not settle) for a code-owner review rule, or None."""
    if not stale_dismissed:
        return (f"{where} keeps an approval when new commits are pushed (turn on dismissing stale "
                "approvals; approval of the most recent push alone keeps the owner's earlier approval)", False)
    if count == 0:
        return (f"{where} requires 0 approvals, and GitHub's docs do not say code-owner review holds then "
                "(require at least 1)", True)
    return None


def _rulesets(get: Get, name: str, branch: str) -> tuple[bool, list[str], bool]:
    """Ruleset rules on `branch` that require code-owner review: (one binds this identity and
    dismisses stale approvals, the problems found, whether anything could not be read)."""
    status, rules = get(f"repos/{name}/rules/branches/{branch}?per_page=100")
    if status != 200 or not isinstance(rules, list):
        return False, [], True
    binds, problems, unread = False, [], False
    for rule in rules:
        params = rule.get("parameters") if isinstance(rule, dict) else None
        if not isinstance(params, dict) or rule.get("type") != "pull_request" \
                or not params.get("require_code_owner_review"):
            continue
        rid = rule.get("ruleset_id")
        status, ruleset = get(f"repos/{name}/rulesets/{rid}?includes_parents=true")
        can = ruleset.get("current_user_can_bypass") if status == 200 and isinstance(ruleset, dict) else None
        review = _review_problem(params.get("dismiss_stale_reviews_on_push"),
                                 params.get("required_approving_review_count"), f"ruleset {rid}")
        if can not in BYPASS_VALUES:
            unread = True
            problems.append(f"cannot tell whether this identity can bypass ruleset {rid}")
        elif can != "never":
            problems.append(f"this identity can bypass ruleset {rid} ({can})")
        elif review:
            unread = unread or review[1]
            problems.append(review[0])
        else:
            binds = True
    return binds, problems, unread


def _classic(get: Get, name: str, branch: str, viewer: object) -> tuple[bool, list[str], int | None]:
    """Classic protection on `branch`: (it requires code-owner review and binds everyone, its
    problems, the read's status: None when a non-admin's 404 leaves it unknown)."""
    status, body = get(f"repos/{name}/branches/{branch}/protection")
    if status != 200 or not isinstance(body, dict):
        return False, [], None if status == 404 and viewer != "ADMIN" else status
    reviews = body.get("required_pull_request_reviews")
    if not isinstance(reviews, dict) or not reviews.get("require_code_owner_reviews"):
        return False, [], status
    allowances = reviews.get("bypass_pull_request_allowances")
    allowances = allowances if isinstance(allowances, dict) else {}
    admins = body.get("enforce_admins")
    review = _review_problem(reviews.get("dismiss_stale_reviews"), reviews.get("required_approving_review_count"),
                             f"branch protection on {branch}")
    problems = [msg for failed, msg in (
        (not (isinstance(admins, dict) and admins.get("enabled")),
         f"branch protection on {branch} lets administrators bypass it (turn on 'Do not allow bypassing "
         "the above settings')"),
        (review is not None, review[0] if review else ""),
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
    unread = [what for gap, what in ((rules_unread, f"the rulesets on {branch}"),
                                     (classic_status not in (200, 404), "branch protection")) if gap]
    if problems and not unread:
        return Verdict(NOT_ENFORCED, problems[0], {})
    if not problems and not unread:
        return Verdict(NOT_ENFORCED, f"no rule on {branch} requires code-owner review", {})
    plan = (" (a private repository needs GitHub Pro or a paid organization plan for this)"
            if classic_status == 403 and info.get("visibility") == "PRIVATE" else "")
    lead = f"{problems[0]}; " if problems else f"no readable rule on {branch} requires code-owner review; "
    return Verdict(UNKNOWN, f"{lead}{' and '.join(unread)} could not be read as this identity{plan}", {})


def _identity_verdict(info: dict, owner: str, branch: str, owners: dict) -> Verdict:
    """With a binding rule in place: enforced only for a role that cannot change it, and not the owner."""
    viewer, login = info.get("viewerPermission"), info.get("viewerLogin")
    if viewer == "ADMIN":
        return Verdict(NOT_ENFORCED, "the rule is in place, but this identity is an administrator, so it can "
                                     "change or remove it: run the agent as an identity without admin "
                                     "(docs/AGENT-IDENTITY.md)", owners)
    if viewer not in SAFE_ROLES:
        return Verdict(UNKNOWN, f"the rule is in place, but GitHub reports no role okl knows for this identity "
                                f"({viewer!r}); for an App, check it has no Administration write", owners)
    if isinstance(login, str) and f"@{login}".lower() == owner.lower():
        return Verdict(NOT_ENFORCED, f"this identity is {owner}, the owner, so its own approval counts: run the "
                                     "agent as an identity of its own (docs/AGENT-IDENTITY.md)", owners)
    return Verdict(ENFORCED, f"code-owner review is required on {branch}, a new push dismisses an approval, "
                             "and this identity cannot bypass or change the rule", owners)


def _from_block(text: str, branch: str) -> tuple[str | None, list[str], Verdict | None]:
    """The owner and paths okl's block on the default branch names, for a clone with no recorded
    owner (.okl/ is not committed)."""
    try:
        block = codeowners.owned(text)
    except codeowners.MalformedBlockError as e:
        return None, [], Verdict(NOT_ENFORCED, f"{e} on {branch}", {})
    names = {o.lower(): o for found in block.values() for o in found}
    if len(names) != 1:
        why = "is not there" if not block else "names no owner" if not names else "names more than one owner"
        return None, [], Verdict(NOT_ENFORCED, f"okl's block in CODEOWNERS on {branch} {why}", {})
    extra = [p for p in block if p not in codeowners.owner_paths([])]
    return next(iter(names.values())), codeowners.owner_paths(extra), None


def check(paths: list[str] | None, owner: str | None, get: Get = _gh_get,
          repo: Callable[[], dict | None] = _gh_repo) -> Verdict:
    """Whether GitHub enforces `owner`'s approval of `paths` against the identity running this.
    With no owner recorded here, both come from okl's block on the default branch."""
    info = repo()
    name = info.get("nameWithOwner") if isinstance(info, dict) else None
    if not isinstance(info, dict) or not isinstance(name, str):
        return Verdict(UNKNOWN, "gh cannot read this repository (install gh and run `gh auth login`)", {})
    ref = info.get("defaultBranchRef")
    branch = ref.get("name") if isinstance(ref, dict) else None
    if not isinstance(branch, str) or not branch:
        return Verdict(UNKNOWN, "this repository has no default branch yet", {})
    text, stop = _codeowners_text(get, name, branch)
    if owner is None and text is not None and stop is None:
        owner, paths, stop = _from_block(text, branch)
    if stop or text is None or owner is None:
        return stop or Verdict(UNKNOWN, f"cannot read who owns okl's paths on {branch}", {})
    paths = paths or codeowners.owner_paths([])
    if stop := _ownership(text, paths, owner, branch):
        return stop
    owners: dict[str, list[str] | None] = {p: [owner] for p in paths}
    rule = _rule_verdict(get, name, branch, info)
    return rule._replace(owners=owners) if rule else _identity_verdict(info, owner, branch, owners)
