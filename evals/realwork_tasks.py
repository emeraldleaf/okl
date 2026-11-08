#!/usr/bin/env python3
"""Build REPORT §4al's real-work tasks: merged pull requests, frozen as their code was first written.

Follows the pre-registration exactly. Eligible: this repository's merged pull requests created on
or after 2026-09-15. Drawn by the order of sha256("4al:" + number), smallest first: forty with at
least one resolved review thread, ten with none. Each task is frozen at the last commit of the pull
request made before its first review comment (with no review, its last commit before merging):

- the change is `git diff <merge base>..<that commit>`, rebuilt from the shas this file records;
- the issues it closes count only if opened before that commit;
- the title is the pull request's, written with the code;
- the store is the lessons recorded before that commit, retired ones only if retired after it,
  read from a snapshot of this machine's store (copied to evals/bench/private/realwork/, never
  committed; its sha256 goes in the receipt).

A task whose issue or title names a lesson's id or repeats a lesson's title is left out and
reported. Calls no model; reads GitHub through gh.

    python3 evals/realwork_tasks.py      # writes evals/realwork/tasks.jsonl and a receipt
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from okl import intake  # noqa: E402

GH_REPO = "emeraldleaf/okl"
SINCE = "2026-09-15"
WITH_REVIEW, WITHOUT_REVIEW = 40, 10
OUT = REPO / "evals" / "realwork" / "tasks.jsonl"
PRIVATE = REPO / "evals" / "bench" / "private" / "realwork"
CLOSES = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")


def git(*args: str) -> str:
    """git's stdout in this repository, or '' when it fails."""
    r = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def order(n: int) -> str:
    """The pre-registered draw order of pull request `n`."""
    return hashlib.sha256(f"4al:{n}".encode()).hexdigest()


def ms(iso: str) -> int:
    """An ISO-8601 time as epoch milliseconds."""
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def snapshot_store() -> tuple[Path, str]:
    """Copy this machine's store to the private folder; its path and sha256."""
    PRIVATE.mkdir(parents=True, exist_ok=True)
    src = REPO / ".okl" / "okl.db"
    with sqlite3.connect(src) as live, sqlite3.connect(PRIVATE / "store.db") as copy:
        live.backup(copy)
    digest = hashlib.sha256((PRIVATE / "store.db").read_bytes()).hexdigest()
    return PRIVATE / "store.db", digest


def lessons_at(db: Path, at_ms: int) -> list[dict]:
    """The lessons a store held at `at_ms`: recorded before it, and not yet retired then."""
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    retired_at = {r["node_id"]: r["t"] for r in con.execute(
        "select node_id, max(at) t from retirement group by node_id")}
    rows = con.execute("select id, type, title, status, created_at from node where type != 'Vocabulary'").fetchall()
    con.close()
    keep = []
    for r in rows:
        if (r["created_at"] or 0) >= at_ms:
            continue
        if r["status"] in ("superseded", "obsolete", "retracted") and retired_at.get(r["id"], 0) <= at_ms:
            continue
        keep.append({"id": r["id"], "title": r["title"] or ""})
    return keep


def frozen_commit(pr: dict) -> tuple[str | None, str]:
    """The commit a task is frozen at, and why: the last before the first review comment, or the
    last before merging when nothing was reviewed."""
    commits = sorted(((c["commit"]["oid"], c["commit"]["committedDate"]) for c in pr["commits"]["nodes"]),
                     key=lambda c: c[1])
    firsts = [t["comments"]["nodes"][0]["createdAt"] for t in pr["reviewThreads"]["nodes"]
              if t.get("comments", {}).get("nodes")]
    if firsts:
        first = min(firsts)
        before = [c for c in commits if c[1] < first]
        return (before[-1][0], "last commit before the first review comment") if before else (None, "no commit before review")
    return (commits[-1][0], "last commit, no review") if commits else (None, "no commits")


def main() -> int:
    """Draw, freeze and write the tasks; print the receipt."""
    prs = json.loads(subprocess.run(
        ["gh", "pr", "list", "-R", GH_REPO, "--state", "merged", "--limit", "500",
         "--json", "number,createdAt,title,body,mergeCommit"], capture_output=True, text=True, check=True).stdout)
    eligible = sorted((p for p in prs if p["createdAt"][:10] >= SINCE), key=lambda p: order(p["number"]))
    db, digest = snapshot_store()
    tasks, skipped, leaks = [], [], []
    want = {"review": WITH_REVIEW, "none": WITHOUT_REVIEW}
    got = {"review": 0, "none": 0}
    for p in eligible:
        if got == want:
            break
        n = p["number"]
        try:
            pr, _files_of = intake.fetch(n, GH_REPO)
        except intake.IntakeError as e:
            skipped.append({"pr": n, "why": f"gh: {e}"})
            continue
        resolved = any(t.get("isResolved") for t in pr["reviewThreads"]["nodes"])
        group = "review" if resolved else "none"
        if got[group] >= want[group]:
            continue
        sha, why = frozen_commit(pr)
        merge = (p.get("mergeCommit") or {}).get("oid")
        if not sha or not merge or not git("cat-file", "-t", sha) or not git("cat-file", "-t", merge):
            skipped.append({"pr": n, "why": why if not sha else "commit not in local history"})
            continue
        base = git("merge-base", sha, f"{merge}^1")
        if not base:
            skipped.append({"pr": n, "why": "no merge base"})
            continue
        at = int(git("show", "-s", "--format=%ct", sha)) * 1000
        issues = []
        for num in sorted({int(x) for x in CLOSES.findall(p.get("body") or "")}):
            r = subprocess.run(["gh", "issue", "view", str(num), "-R", GH_REPO, "--json", "title,body,createdAt"],
                               capture_output=True, text=True)
            if r.returncode == 0:
                i = json.loads(r.stdout)
                if ms(i["createdAt"]) < at:
                    issues.append({"number": num, "title": i["title"], "body": i["body"] or ""})
        lessons = lessons_at(db, at)
        text = " ".join([p["title"], *(i["title"] + " " + i["body"] for i in issues)]).lower()
        named = [lesson["id"] for lesson in lessons
                 if lesson["id"].lower() in text or (len(lesson["title"]) > 20 and lesson["title"].lower() in text)]
        if named:
            leaks.append({"pr": n, "names": named})
            continue
        paths = [f for f in git("diff", "--name-only", f"{base}..{sha}").splitlines() if f]
        size = len(git("diff", f"{base}..{sha}"))
        tasks.append({"pr": n, "group": group, "base": base, "commit": sha, "frozen": why,
                      "at": datetime.fromtimestamp(at / 1000, UTC).strftime("%Y-%m-%dT%H:%MZ"),
                      "title": p["title"], "issues": issues, "paths": paths, "change_chars": size,
                      "cut": size > 60000, "lessons": [lesson["id"] for lesson in lessons]})
        got[group] += 1
        print(f"  #{n} {group:6} frozen at {sha[:7]} · {len(paths)} files · {size} chars · "
              f"{len(issues)} issue(s) · {len(lessons)} lessons", file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in tasks))
    receipt = {"section": "4al", "built": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
               "okl_commit": git("rev-parse", "--short", "HEAD"), "store_sha256": digest,
               "eligible": len(eligible), "drawn": got, "wanted": want, "skipped": skipped, "leaks": leaks,
               "cut_at_60000": sum(t["cut"] for t in tasks),
               "lessons_per_task": [len(t["lessons"]) for t in tasks]}
    path = REPO / "evals" / "results" / f"realwork-tasks-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    path.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "lessons_per_task"}, indent=1))
    print(f"receipt: {path.relative_to(REPO)}")
    return 0 if got == want else 1


if __name__ == "__main__":
    raise SystemExit(main())
