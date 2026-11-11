"""A model's review of the lessons nothing re-checks: `okl review` (#315, REPORT §4ai).

Drift re-runs a lesson's check when its governed files change, and CI runs the checks of
lessons that govern no files (#39). A lesson with neither is never re-read, and the briefing
marks it UNCHECKED (#222). This review has a model read each one against the repository at
HEAD and answer on §4ai's six-way scale: current, detail wrong, outlived, stale, no claim or
unsure. A verdict that questions a lesson quotes the words that no longer hold and what the
repository has instead, for the person to `okl update` or `okl retire`.

It is opt-in and outside the loop. The briefing, the hooks and the gate call no model (the
README's promise); only the person running `okl review` does, and it never writes. The prompt
and the default judge are the ones §4ai measured, and a test holds them equal to the
instrument's, so the catch rates its help quotes are this command's own. Another judge
command has no measured catch rate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .core import bundled_packs, from_bundled_pack
from .drift import _NOT_ADVICE  # never advice; one definition (tests/test_single_source.py)
from .store import RETIRED_STATUSES, Node, has_observed_check

# The judge §4ai measured: read-only tools, and --restricted ignores every settings file, so no
# okl hook briefs it. --allowedTools takes the rest of the line, so it comes last and the prompt
# goes on stdin.
JUDGE = ["claude", "-p", "--model", "opus", "--restricted", "--strict-mcp-config", "--output-format", "json",
         "--tools", "Read,Grep,Glob", "--allowedTools", "Read", "Grep", "Glob"]
PROMPT = """You are checking whether a lesson a software project recorded about itself still holds.
The project's repository is your working directory, at the commit the project is at now. Read
whatever you need with your tools. Do not change anything.

The lesson:
Title: {title}
Symptom: {symptom}
Fix: {fix}
Body: {body}

Choose one verdict:
- "current": the lesson's point holds of this repository, and so does every detail it states about it.
- "detail wrong": the point holds, but a detail it states about this repository (a path, name,
  command, flag, default or count) is wrong now.
- "outlived": the lesson advises a workaround, an interim step or a caution that a later change in
  this repository has made unnecessary.
- "stale": the lesson's point no longer holds of this repository.
- "no claim": it says nothing this repository can confirm or contradict (advice in general, or a
  fact about another project).
- "unsure": you cannot decide.

Answer with one JSON object and nothing else:
{{"verdict": "current|detail wrong|outlived|stale|no claim|unsure", "no_longer": "the lesson's words that no longer hold, or empty", "instead": "what the repository has instead, or empty", "evidence": ["path:line", ...], "reason": "one sentence", "checkable": true or false}}
"checkable" says whether a shell command could check what the lesson claims about this repository."""
VERDICTS = ("current", "detail wrong", "outlived", "stale", "no claim", "unsure")
QUESTIONED = ("detail wrong", "outlived", "stale")
TIMEOUT = 300   # seconds per lesson, as measured
# What §4ai measured, quoted by the help; a test recomputes each from the receipt.
MEASURED = {"receipt": "stale-review-20261102-2133.json", "planted": (8, 10), "over_called": (1, 10),
            "outlived": (2, 2)}


def unchecked(nodes: Iterable[Node]) -> list[Node]:
    """The lessons this review judges: the store's own live advice lessons (not a bundled pack's)
    that govern no files and that no observed check backs, the ones the briefing marks UNCHECKED
    and nothing ever re-reads. A lesson with files is drift's, which reports it until it has a
    check."""
    bundled = bundled_packs()
    return [n for n in nodes if n.status not in RETIRED_STATUSES and n.type not in _NOT_ADVICE and not from_bundled_pack(n.id, bundled)
            and not n.files and not has_observed_check({"verified_at": n.verified_at, "verified_by": n.verified_by,
                                                        "verified_commit": n.verified_commit})]


def parse(text: str) -> dict[str, Any] | None:
    """The judge's last valid answer in `text`, or None. A verdict that questions the lesson is
    valid only with the words that no longer hold and what the repository has instead."""
    def valid(o: dict[str, Any]) -> bool:
        if o.get("verdict") not in VERDICTS:
            return False
        return o["verdict"] not in QUESTIONED or all(
            isinstance(o.get(k), str) and o[k].strip() for k in ("no_longer", "instead"))
    dec, found = json.JSONDecoder(), None
    for m in re.finditer(r"\{", text):   # the last object, not first brace to last (review on #312)
        try:
            obj, _end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and valid(obj):
            found = obj
    return found


def _answer(stdout: str) -> str:
    """The judge's answer: the `result` of a `claude -p --output-format json` envelope, or the
    whole output of a judge command that prints its answer plainly."""
    try:
        envelope = json.loads(stdout)
    except ValueError:
        return stdout
    if isinstance(envelope, dict) and "result" in envelope:
        return str(envelope["result"] or "")
    return stdout


def _git_env() -> dict[str, str]:
    """This environment without the variables that locate a repository: run from inside a git
    hook, GIT_DIR and friends would point the worktree calls at that repository instead."""
    local = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
    return {k: v for k, v in os.environ.items() if k not in local}


def judge_one(n: Node, judge: list[str], cwd: Path, timeout: int = TIMEOUT,
              env: dict[str, str] | None = None) -> dict[str, Any]:
    """One lesson, judged once: the parsed answer with its id, or the reason there is none. It
    never raises, so one lesson's failure costs neither the others nor the calls already made."""
    text = {f: getattr(n, f) or "" for f in ("title", "symptom", "fix", "body")}
    out: dict[str, Any] = {"id": n.id, "type": n.type, "title": n.title}
    try:
        p = subprocess.run(judge, input=PROMPT.format(**text), capture_output=True, text=True,
                           timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired:
        return {**out, "error": f"no answer in {timeout} seconds"}
    except OSError as e:   # on PATH but not runnable, such as a bad interpreter line
        return {**out, "error": f"could not run the judge: {e}"}
    got = parse(_answer(p.stdout))
    if got is None:
        why = (p.stderr or p.stdout or "no output").strip().splitlines() or ["no output"]
        return {**out, "error": f"no valid answer (exit {p.returncode}): {why[-1][:200]}"}
    evidence = got.get("evidence")
    evidence = [evidence] if isinstance(evidence, str) else evidence if isinstance(evidence, list) else []
    return {**out, **{k: got.get(k) for k in ("verdict", "no_longer", "instead", "reason", "checkable")},
            "evidence": [str(x) for x in evidence]}


def review(nodes: list[Node], root: Path, *, judge: list[str] | None = None, workers: int = 3,
           timeout: int = TIMEOUT, progress: Callable[[dict[str, Any]], None] | None = None) -> list[dict[str, Any]]:
    """Judge each of `nodes` against the repository at `root`'s HEAD, in a scratch worktree, so
    the judge reads what is committed and never the working tree; the worktree holds no
    okl-drift.json, as measured. Nothing is written to the store or the checkout."""
    judge = judge or JUDGE
    env = _git_env()
    with tempfile.TemporaryDirectory(prefix="okl-review-") as room:
        wt = Path(room) / "repo"
        add = subprocess.run(["git", "-C", str(root), "worktree", "add", "-q", "--detach", str(wt), "HEAD"],
                             capture_output=True, text=True, env=env)
        if add.returncode != 0:
            raise ValueError(f"could not check out HEAD to review against: {add.stderr.strip()}")
        try:
            (wt / "okl-drift.json").unlink(missing_ok=True)   # the judge reads no check or file list

            def one(n: Node) -> dict[str, Any]:
                got = judge_one(n, judge, wt, timeout, env)
                if progress:
                    progress(got)
                return got
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                return list(pool.map(one, nodes))
        finally:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(wt)],
                           capture_output=True, text=True, env=env)
