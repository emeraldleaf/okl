"""`okl intake pr <n>`: a merged or open PR's resolved review findings, put to the encoding loop.

The Stop hook asks what a session learned, and nothing else asks at all: a finding a reviewer
made on a PR reached the store only when the agent that fixed it recorded it by hand, and a PR
no session opened was never asked (#376). This lists a PR's resolved review threads, each with
the commit that resolved it, and prints the encoding-loop question for each with the `okl
record` and `okl verify` commands that would encode it, for an agent or a person to decide on.
Unresolved threads are left out: a finding nobody acted on is not yet a lesson.

GitHub does not say which commit resolved a thread, so it is read two ways: a commit of the PR
named in a reply ("Fixed in 328d0ba"), which is how a fix is usually reported, or else the
first commit after the finding that touched its file, marked as a guess.

Imports nothing from okl: the CLI passes the store's search in, and the tests pass recorded
`gh` JSON, so none of it needs the network.
"""
from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass

# Paged, both connections: a PR with more threads or commits than one page holds was read only
# in part, and shown as if whole (CodeRabbit on #388). A thread's comments come 100 at a time,
# and a thread with more is named in a warning rather than followed.
THREADS_QUERY = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number title url state
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved path line originalLine
          resolvedBy { login }
          comments(first: 100) { pageInfo { hasNextPage } nodes { author { login } body createdAt url } }
        }
      }
    }
  }
}"""
COMMITS_QUERY = """query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      commits(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes { commit { oid committedDate messageHeadline } }
      }
    }
  }
}"""
_MAX_PAGES = 50                    # 5,000 threads or commits: past that, something is wrong

_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


class IntakeError(Exception):
    """gh could not read the PR: not installed, not signed in, or no such PR."""


@dataclass
class Finding:
    """One resolved review thread, and what encoding it would take."""

    path: str
    line: int | None
    author: str
    summary: str
    url: str
    resolved_by: str | None
    commit: str | None             # the resolving commit's short sha, when one is known
    commit_title: str | None
    found_how: str | None          # "named in a reply", or the guess
    briefed: list[str] | None = None   # "[id] title" of each lesson a briefing on it would show

    def where(self) -> str:
        """`path:line`, or the path alone for a comment on the whole file."""
        return f"{self.path}:{self.line}" if self.line else self.path


def summary_of(body: str) -> str:
    """The finding in one line: a review bot's bold title when it gives one, else the first
    line of prose, without HTML comments, tags or a leading severity badge."""
    text = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    titles = [t.strip(" .") for t in re.findall(r"\*\*(.+?)\*\*", text)]
    # A CodeRabbit finding opens with badges (**Minor**, **Quick win**); its title is the
    # first bold phrase that is a sentence, not a label.
    for t in titles:
        if len(t.split()) >= 4:
            return _clip(t)
    for line in text.splitlines():
        line = line.strip().lstrip("#>-* ").strip()
        if line and not line.startswith("```"):
            return _clip(line)
    return "(no text)"


def _clip(s: str, n: int = 160) -> str:
    """`s` on one line, cut to `n` characters with an ellipsis."""
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def findings(pr: dict, files_of: Callable[[str], set[str]]) -> list[Finding]:
    """The resolved threads of `pr` (GitHub's pullRequest object, as fetch() returns it), oldest
    first. `files_of(sha)` gives the paths a commit changed; it is asked only for a thread no
    reply names a commit for."""
    commits = sorted(((c["commit"]["oid"], c["commit"]["committedDate"], c["commit"]["messageHeadline"])
                      for c in pr.get("commits", {}).get("nodes", [])), key=lambda c: c[1])
    out: list[tuple[str, int, Finding]] = []
    for t in pr.get("reviewThreads", {}).get("nodes", []):
        comments = t.get("comments", {}).get("nodes", [])
        if not t.get("isResolved") or not comments:
            continue
        first = comments[0]
        sha, title, how = _resolving_commit(comments, commits, t.get("path") or "", files_of)
        url = first.get("url") or ""
        out.append((first.get("createdAt") or "", _comment_number(url), Finding(
            path=t.get("path") or "", line=t.get("line") or t.get("originalLine"),
            author=(first.get("author") or {}).get("login") or "?",
            summary=summary_of(first.get("body") or ""), url=url,
            resolved_by=(t.get("resolvedBy") or {}).get("login"),
            commit=sha[:7] if sha else None, commit_title=title, found_how=how)))
    # When each finding was made, then its comment number: a URL sorts discussion_r10 before
    # discussion_r9 (CodeRabbit on #388).
    return [f for _at, _n, f in sorted(out, key=lambda e: (e[0], e[1]))]


def _comment_number(url: str) -> int:
    """The review comment's number at the end of its URL (#discussion_r4503195153), or 0."""
    m = re.search(r"(\d+)$", url)
    return int(m.group(1)) if m else 0


def _resolving_commit(comments: list[dict], commits: list[tuple[str, str, str]], path: str,
                      files_of: Callable[[str], set[str]]) -> tuple[str | None, str | None, str | None]:
    """(sha, headline, how it was found) of the commit that resolved a thread, or Nones."""
    for c in comments[1:]:
        for word in _SHA.findall(c.get("body") or ""):
            for oid, _at, headline in commits:
                if oid.startswith(word):
                    return oid, headline, "named in a reply"
    after = comments[0].get("createdAt") or ""
    for oid, at, headline in commits:
        if at > after and path in files_of(oid):
            return oid, headline, f"a guess: the first commit after the finding to touch {path}"
    return None, None, None


def record_command(f: Finding, pr: int) -> str:
    """The `okl record` that would encode `f`, with what the thread says filled in and the
    lesson's own words left as placeholders: a review comment says what was wrong once, and a
    lesson says what to do every time."""
    args = ["okl", "record", "--type", "Defect", "--scope", "repo", "--id", "<a-short-stable-id>",
            "--title", "<the lesson, as a rule>", "--symptom", "<what you would see>",
            "--body", "cause: <why it happened>", "--fix", "<what to do>"]
    if f.path:
        args += ["--files", f.path]
    args += ["--found-by", f"review on PR #{pr}" + (f", fixed in {f.commit}" if f.commit else ""),
             "--trigger", f.summary]
    return shlex.join(args)


def verify_command() -> str:
    """The check that proves a recorded lesson, as placeholders."""
    return shlex.join(["okl", "verify", "<a-short-stable-id>", "--run",
                       "<a check that fails if this breaks>", "--expect", "<its success text>"])


QUESTION = ("Encode it? Where would it be held: a test, a CI check, a rule, or a lesson "
            "(okl record)? If not, say why not.")


def render(fs: list[Finding], pr: dict) -> str:
    """The worksheet: each resolved finding, the question, and the commands to answer it."""
    n = int(pr.get("number") or 0)
    head = f"okl intake pr {n}: {len(fs)} resolved review thread(s) on \"{pr.get('title', '')}\""
    warned = [f"  ! {w}" for w in pr.get("warnings", [])]
    if not fs:
        return "\n".join([head + ".", *warned, "Nothing to ask: no review thread on it was resolved."]) + "\n"
    lines = [head, *warned, ""]
    for i, f in enumerate(fs, 1):
        lines.append(f"[{i}] {f.where()} · {f.author}"
                     + (f" · resolved by {f.resolved_by}" if f.resolved_by else ""))
        lines.append(f"    {f.summary}")
        if f.commit:
            lines.append(f"    resolved in {f.commit} \"{f.commit_title}\" ({f.found_how})")
        else:
            lines.append("    no resolving commit found: read the thread")
        if f.url:
            lines.append(f"    {f.url}")
        if f.briefed:
            lines.append("    a briefing on it already shows: " + "; ".join(f.briefed))
            lines.append("    (if one of these covers it, refine that one: okl update <id>)")
        lines += [f"    {QUESTION}", f"    {record_command(f, n)}", f"    {verify_command()}", ""]
    return "\n".join(lines).rstrip() + "\n"


def as_json(fs: list[Finding], pr: dict) -> str:
    """The same, for an agent: each finding with its commands."""
    n = int(pr.get("number") or 0)
    return json.dumps({"pr": n, "title": pr.get("title"), "url": pr.get("url"), "question": QUESTION,
                       "warnings": pr.get("warnings", []),
                       "findings": [{**asdict(f), "record": record_command(f, n), "verify": verify_command()}
                                    for f in fs]}, indent=2)


# --- reading GitHub, through gh ------------------------------------------------------------

def _gh(*args: str) -> str:
    """gh's output for `args`, or IntakeError saying why gh could not give it."""
    if shutil.which("gh") is None:
        raise IntakeError("gh is not installed: okl intake reads the PR through it (https://cli.github.com)")
    try:
        r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise IntakeError(f"gh did not run: {e}") from e
    if r.returncode != 0:
        raise IntakeError((r.stderr.strip().splitlines() or ["gh failed"])[-1])
    return r.stdout


def _pages(query: str, key: str, owner: str, name: str, number: int) -> tuple[dict | None, list[dict]]:
    """The PR object of the first page, and every node of its `key` connection, page by page;
    (None, []) when GitHub has no such PR."""
    nodes: list[dict] = []
    head: dict | None = None
    after: str | None = None
    for _ in range(_MAX_PAGES):
        args = ["api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}", "-F", f"name={name}",
                "-F", f"number={number}"] + (["-f", f"after={after}"] if after else [])
        data = json.loads(_gh(*args))
        pr = ((data.get("data") or {}).get("repository") or {}).get("pullRequest")
        if not pr:
            return None, []
        head = head or pr
        conn = pr.get(key) or {}
        nodes += conn.get("nodes", [])
        info = conn.get("pageInfo") or {}
        if not info.get("hasNextPage"):
            return head, nodes
        after = info.get("endCursor")
    raise IntakeError(f"more than {_MAX_PAGES} pages of {key}: stopped rather than read on")


def fetch(number: int, repo: str | None = None) -> tuple[dict, Callable[[str], set[str]]]:
    """PR `number` of `repo` (OWNER/NAME, else the repo gh sees here), every review thread and
    commit of it, in the shape findings() reads, with a `warnings` list for anything read only
    in part; and a reader of the files a commit changed."""
    if not repo:
        repo = json.loads(_gh("repo", "view", "--json", "nameWithOwner"))["nameWithOwner"]
    owner, _, name = (repo or "").partition("/")
    pr, threads = _pages(THREADS_QUERY, "reviewThreads", owner, name, number)
    if not pr:
        raise IntakeError(f"no PR #{number} in {repo}")
    _head, commits = _pages(COMMITS_QUERY, "commits", owner, name, number)
    pr = {**pr, "reviewThreads": {"nodes": threads}, "commits": {"nodes": commits},
          "warnings": [f"a thread on {t.get('path') or 'the PR'} has more than 100 comments; only "
                       "the first 100 were read" for t in threads
                       if ((t.get("comments") or {}).get("pageInfo") or {}).get("hasNextPage")]}
    cache: dict[str, set[str]] = {}

    def files_of(sha: str) -> set[str]:
        """The paths commit `sha` changed, read once."""
        if sha not in cache:
            info = json.loads(_gh("api", f"repos/{owner}/{name}/commits/{sha}"))
            cache[sha] = {f["filename"] for f in info.get("files", [])}
        return cache[sha]

    return pr, files_of
